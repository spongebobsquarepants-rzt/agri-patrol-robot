import csv
import hashlib
import html
import json
import re
import traceback
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, unquote, urljoin, urlparse
from urllib.request import Request, urlopen


BASE = "https://developer.d-robotics.cc"
ROOT_URL = "https://developer.d-robotics.cc/rdk_x_doc/RDK?v=3.5.0&p=RDK+X5"
OUT_ROOT = Path(r"D:\obsidian\20_Sources\D-Robotics")
LIB = OUT_ROOT / "RDK_X5_官方文档库"
PAGES_DIR = LIB / "pages"
DATA_DIR = LIB / "_data"
TOOLS_DIR = LIB / "_tools"
CAPTURED_AT = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S %z")
UA = "Mozilla/5.0 RDK-X5-ObsidianIndexer/1.0"

FILE_EXTS = {
    ".pdf", ".zip", ".rar", ".7z", ".tar", ".tgz", ".gz", ".xz", ".bz2", ".img", ".iso",
    ".bin", ".deb", ".rpm", ".whl", ".exe", ".msi", ".dmg", ".apk", ".doc", ".docx",
    ".xls", ".xlsx", ".ppt", ".pptx", ".csv", ".json", ".yaml", ".yml", ".dtb",
    ".dtbo", ".ko", ".patch", ".diff", ".onnx", ".hbm", ".so", ".a",
}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp"}
RESOURCE_KEYWORDS = [
    "download", "downloads", "os_images", "image", "镜像", "固件", "firmware", "sdk",
    "toolchain", "工具链", "datasheet", "规格", "规格书", "硬件资料", "原理图",
    "schematic", "pcb", "bom", "机械", "结构", "2d", "3d", "烧录", "ubuntu",
    "desktop", "minimal", "server", "release", "github.com", "archive.d-robotics", "filedata",
]
TAG_WORDS = {
    "RDK_X5": ["rdk_x5", "rdkx5", "x5"],
    "串口": ["uart", "串口", "ttys"],
    "GPIO": ["gpio", "40pin", "管脚"],
    "I2C_SPI_PWM": ["i2c", "spi", "pwm"],
    "烧录_镜像": ["system_burn", "nand_flash", "boot_system", "烧录", "镜像", "固件"],
    "视觉_摄像头": ["vision", "camera", "摄像头", "mipi", "usb_camera"],
    "多媒体": ["multimedia", "multi_media", "vio", "venc", "vdec", "codec"],
    "驱动开发": ["driver", "驱动", "kernel", "uboot"],
    "Python示例": ["pydev", "python", "hbm_runtime"],
    "机器人_ROS": ["robot", "tros", "ros"],
    "命令手册": ["command", "cmd_", "命令"],
}


def fetch_text(url, timeout=35):
    req = Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        ctype = resp.headers.get("content-type", "") or ""
    return raw.decode("utf-8", "replace"), ctype, len(raw)


def clean_space(text):
    text = html.unescape(text or "")
    text = text.replace("\r", "\n").replace("\t", " ")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \u00a0]{2,}", " ", text)
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line).strip()


def decode_js_string(raw):
    try:
        return json.loads('"' + raw + '"')
    except Exception:
        return raw


def yaml_quote(value):
    return json.dumps(value or "", ensure_ascii=False)


def md_escape_table(value):
    return (value or "").replace("|", "\\|").replace("\n", " ").strip()


def sanitize_filename(value):
    value = value or "untitled"
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value)
    value = re.sub(r"\s+", "_", value).strip("._ ")
    return value[:70] or "untitled"


class DocHtmlParser(HTMLParser):
    def __init__(self, mode="markdown"):
        super().__init__(convert_charrefs=True)
        self.mode = mode
        self.collect = False
        self.depth = 0
        self.skip_depth = 0
        self.parts = []
        self.headings = []
        self.links = []
        self.current_link = None
        self.h_tag = None
        self.h_text = []
        self.in_title = False
        self.title_text = []

    def want_start(self, tag, attrs):
        attrs = dict(attrs)
        classes = attrs.get("class", "") or ""
        if self.mode == "markdown" and tag == "div" and "theme-doc-markdown" in classes:
            return True
        return self.mode == "main" and tag == "main"

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "title":
            self.in_title = True
        if self.skip_depth:
            self.skip_depth += 1
            return
        if not self.collect and self.want_start(tag, attrs):
            self.collect = True
            self.depth = 1
            return
        if not self.collect:
            return
        self.depth += 1
        if tag in {"script", "style", "svg", "noscript"}:
            self.skip_depth = 1
            return
        if tag in {"p", "div", "section", "article", "li", "tr", "pre", "blockquote"}:
            self.parts.append("\n")
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self.parts.append("\n")
            self.h_tag = tag
            self.h_text = []
        if tag == "br":
            self.parts.append("\n")
        if tag == "a" and attrs.get("href"):
            self.current_link = {"url": attrs["href"], "text": "", "tag": "a"}
        if tag == "img" and attrs.get("src"):
            alt = attrs.get("alt", "")
            self.links.append({"url": attrs["src"], "text": alt, "tag": "img"})
            if alt:
                self.parts.append(f" [图片: {alt}] ")

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        if self.skip_depth:
            self.skip_depth -= 1
            return
        if not self.collect:
            return
        if tag == "a" and self.current_link:
            self.current_link["text"] = self.current_link["text"].strip()
            self.links.append(self.current_link)
            self.current_link = None
        if self.h_tag == tag:
            value = clean_space("".join(self.h_text))
            if value:
                self.headings.append({"level": int(tag[1]), "value": value})
            self.h_tag = None
            self.h_text = []
        self.depth -= 1
        if self.depth <= 0:
            self.collect = False
            self.depth = 0

    def handle_data(self, data):
        if self.in_title:
            self.title_text.append(data)
        if self.skip_depth or not self.collect or not data:
            return
        self.parts.append(data)
        if self.current_link is not None:
            self.current_link["text"] += data
        if self.h_tag:
            self.h_text.append(data)


def extract_html(html_text):
    parser = DocHtmlParser("markdown")
    parser.feed(html_text)
    if len(clean_space(" ".join(parser.parts))) < 40:
        fallback = DocHtmlParser("main")
        fallback.feed(html_text)
        if len(clean_space(" ".join(fallback.parts))) > len(clean_space(" ".join(parser.parts))):
            parser = fallback

    text = clean_space("\n".join(parser.parts))
    h1 = next((h["value"] for h in parser.headings if h.get("level") == 1), "")
    title = h1
    if not title:
        m = re.search(r'<meta[^>]+property="og:title"[^>]+content="([^"]*)"', html_text)
        if m:
            title = html.unescape(m.group(1)).replace(" | RDK X3/X5 DOC", "").strip()
    if not title and parser.title_text:
        title = clean_space(" ".join(parser.title_text)).replace(" | RDK X3/X5 DOC", "").strip()

    desc = ""
    m = re.search(r'<meta[^>]+name="description"[^>]+content="([^"]*)"', html_text)
    if m:
        desc = html.unescape(m.group(1)).strip()
    return {
        "title": title,
        "description": desc,
        "text": text,
        "headings": parser.headings,
        "links": parser.links,
    }


def js_strings(js_part):
    out = []
    for raw in re.findall(r'"((?:\\.|[^"\\])*)"', js_part):
        try:
            value = json.loads('"' + raw + '"')
        except Exception:
            continue
        if isinstance(value, str):
            out.append(value)
    return out


def extract_chunk(js_text):
    metadata = {}
    for raw in re.findall(r"JSON\.parse\('((?:\\.|[^'\\])*)'\)", js_text):
        try:
            obj = json.loads(raw)
        except Exception:
            continue
        if isinstance(obj, dict) and ("title" in obj or "permalink" in obj):
            metadata = obj
            break

    toc = []
    for raw, level in re.findall(r'\{value:"((?:\\.|[^"\\])*)",id:"(?:\\.|[^"\\])*",level:(\d+)\}', js_text):
        toc.append({"value": decode_js_string(raw), "level": int(level)})

    body = js_text
    idx = body.find("children:[")
    if idx >= 0:
        body = body[idx:]
    cut = body.find("function a(")
    if cut > 0:
        body = body[:cut]

    noise = {
        "a", "admonition", "code", "h1", "h2", "h3", "h4", "h5", "h6", "header", "img",
        "li", "ol", "ul", "p", "pre", "strong", "table", "tbody", "td", "th", "thead",
        "tr", "blockquote", "details", "summary", "Tabs", "TabItem",
    }
    kept = []
    for item in js_strings(body):
        item = item.strip()
        if not item or item in noise or item.startswith("@site/"):
            continue
        if item.startswith("{") and '"id"' in item:
            continue
        if item not in kept:
            kept.append(item)

    links = []
    for item in kept:
        if item.startswith(("http://", "https://", "/rdk_x_doc/", "/api/", "api/")):
            links.append({"url": item, "text": "", "tag": "js"})
        elif re.search(r"\.(pdf|zip|rar|7z|tar|gz|xz|img|iso|bin|deb|whl|exe|docx?|xlsx?|pptx?)(\?|$)", item, re.I):
            links.append({"url": item, "text": "", "tag": "js"})

    return {
        "title": metadata.get("title", ""),
        "description": metadata.get("description", ""),
        "text": clean_space("\n".join(kept)),
        "headings": toc,
        "links": links,
        "metadata": metadata,
    }


def load_main_runtime():
    html_text, _, _ = fetch_text(ROOT_URL)
    main_match = re.search(r'src="(/rdk_x_doc/assets/js/main\.[^"]+\.js)"', html_text)
    runtime_match = re.search(r'src="(/rdk_x_doc/assets/js/runtime~main\.[^"]+\.js)"', html_text)
    if not main_match or not runtime_match:
        raise RuntimeError("Cannot find Docusaurus JS entrypoints")
    main_url = urljoin(BASE, main_match.group(1))
    runtime_url = urljoin(BASE, runtime_match.group(1))
    main_js, _, _ = fetch_text(main_url)
    runtime_js, _, _ = fetch_text(runtime_url)
    (DATA_DIR / "source_main_js_url.txt").write_text(main_url + "\n" + runtime_url + "\n", encoding="utf-8")
    return main_js, runtime_js, main_url, runtime_url


def parse_routes(main_js):
    route_re = re.compile(r'\{"id":"((?:\\.|[^"\\])*)","path":"((?:\\.|[^"\\])*)","sidebar":"tutorialSidebar"\}')
    routes = []
    seen = set()
    for match in route_re.finditer(main_js):
        doc_id = decode_js_string(match.group(1))
        path = decode_js_string(match.group(2))
        if path in seen:
            continue
        seen.add(path)
        routes.append({"index": len(routes) + 1, "doc_id": doc_id, "path": path})
    if len(routes) != 275:
        raise RuntimeError(f"Expected 275 routes, got {len(routes)}")

    content_map = {}
    for match in re.finditer(r'"((?:\\.|[^"\\])+?)-[0-9a-f]{3}":\{"__comp":"[^"]+","content":"([0-9a-f]{8})"\}', main_js):
        content_map[decode_js_string(match.group(1))] = match.group(2)

    props_map = {}
    for match in re.finditer(r'"((?:\\.|[^"\\])+?)-[0-9a-f]{3}":\{"__comp":"[^"]+","__props":"([0-9a-f]{8})"\}', main_js):
        props_map[decode_js_string(match.group(1))] = match.group(2)

    registry = {}
    reg_re = re.compile(r'(?:"([0-9a-f]{8})"|([0-9a-f]{8})):\[\(\)=>([^"]+),"(@site/docs/[^"]+?\.md)",(\d+)\]', re.S)
    for match in reg_re.finditer(main_js):
        quoted_key, bare_key, loader, source_md, module_id = match.groups()
        key = quoted_key or bare_key
        registry[key] = {
            "content_hash": key,
            "chunk_ids": re.findall(r"n\.e\((\d+)\)", loader),
            "source_md": source_md,
            "module_id": module_id,
        }

    for route in routes:
        route["content_hash"] = content_map.get(route["path"])
        route["props_hash"] = props_map.get(route["path"])
        if route["content_hash"] in registry:
            route.update(registry[route["content_hash"]])
    return routes


def parse_runtime(runtime_js):
    match = re.search(
        r'r\.u=e=>"assets/js/"\+\(\{(.*?)\}\[e\]\|\|e\)\+"\."\+\{(.*?)\}\[e\]\+".js"',
        runtime_js,
        re.S,
    )
    if not match:
        raise RuntimeError("Cannot parse runtime chunk mapping")

    def parse_obj(body):
        out = {}
        token_re = re.compile(r'(?:(\d+)|([A-Za-z0-9_]+)|"([^"]+)")\s*:\s*"([^"]+)"')
        for item in token_re.finditer(body):
            key = item.group(1) or item.group(2) or item.group(3)
            out[str(key)] = item.group(4)
        return out

    first = parse_obj(match.group(1))
    second = parse_obj(match.group(2))

    def filename(chunk_id):
        cid = str(chunk_id)
        if cid not in second:
            return None
        return f"{first.get(cid, cid)}.{second[cid]}.js"

    return filename


def url_ext(url):
    name = unquote(urlparse(url).path).rsplit("/", 1)[-1]
    if "." not in name:
        return ""
    return ("." + name.rsplit(".", 1)[-1].lower())[:16]


def classify_resource(url, text=""):
    lower = (url + " " + (text or "")).lower()
    ext = url_ext(url)
    if ext == ".pdf":
        return "PDF/规格书"
    if ext in {".zip", ".rar", ".7z", ".tar", ".tgz", ".gz", ".xz", ".bz2"}:
        if any(k in lower for k in ["sdk", "toolchain", "工具链"]):
            return "SDK/工具链压缩包"
        if any(k in lower for k in ["hardware", "硬件", "schematic", "pcb", "datasheet", "规格"]):
            return "硬件资料包"
        return "压缩包/资料包"
    if ext in {".img", ".iso", ".bin"} or any(k in lower for k in ["os_images", "镜像", "image", "firmware", "固件", "ubuntu"]):
        return "系统镜像/固件"
    if any(k in lower for k in ["sdk", "toolchain", "工具链"]):
        return "SDK/工具链"
    if any(k in lower for k in ["datasheet", "规格", "规格书", "硬件资料", "原理图", "schematic", "pcb", "bom"]):
        return "硬件规格/资料"
    if "github.com" in lower or "gitee.com" in lower:
        return "源码/仓库"
    if ext in FILE_EXTS:
        return "外部文件"
    return "外部链接"


def is_resource(url, text=""):
    if not url or url.startswith(("#", "javascript:", "mailto:", "tel:")):
        return False
    lower = (url + " " + (text or "")).lower()
    ext = url_ext(url)
    if ext in IMAGE_EXTS and not any(k in lower for k in ["schematic", "规格", "datasheet", "原理图", "硬件"]):
        return False
    if ext in FILE_EXTS or any(k in lower for k in RESOURCE_KEYWORDS):
        return True
    host = urlparse(url if re.match(r"https?://", url) else urljoin(BASE, url)).netloc.lower()
    return bool(host and host not in {"developer.d-robotics.cc"})


def make_summary(title, desc, text, limit=420):
    chunks = []
    if desc and desc != "RDK X3/X5 DOC":
        chunks.append(desc)
    body = re.sub(r"\s+", " ", text or "").strip()
    if title and body.startswith(title):
        body = body[len(title):].strip()
    if body:
        chunks.append(body)
    joined = " ".join(chunks).strip()
    if not joined:
        return "未从静态页面或 chunk 中抽取到正文；保留官方链接用于后续人工核验。"
    if len(joined) <= limit:
        return joined
    cut = joined[:limit]
    pos = max(cut.rfind(x) for x in ["。", "；", ";", ".", "！", "？"])
    if pos > 120:
        return cut[: pos + 1]
    return cut.rstrip() + "..."


def path_group(path):
    value = path.replace("/rdk_x_doc/", "").strip("/")
    return value.split("/", 1)[0] if value else "RDK"


def tags_for(route, title, text):
    blob = (route.get("path", "") + " " + route.get("doc_id", "") + " " + (title or "") + " " + (text or "")[:1000]).lower()
    tags = ["RDK_X5", "D-Robotics", "官方文档"]
    for tag, words in TAG_WORDS.items():
        if any(word.lower() in blob for word in words):
            tags.append(tag)
    return list(dict.fromkeys(tags))


def page_worker(route, chunk_filename, chunk_cache):
    page_url = BASE + quote(route["path"], safe="/%") + "?v=3.5.0&p=RDK+X5"
    html_info = {"title": "", "description": "", "text": "", "headings": [], "links": []}
    html_error = ""
    try:
        html_text, _, _ = fetch_text(page_url, timeout=30)
        html_info = extract_html(html_text)
    except Exception as exc:
        html_error = repr(exc)

    chunk_info = {"title": "", "description": "", "text": "", "headings": [], "links": [], "metadata": {}}
    chunk_error = ""
    for cid in reversed(route.get("chunk_ids") or []):
        fname = chunk_filename(cid)
        if not fname:
            continue
        chunk_url = BASE + "/rdk_x_doc/assets/js/" + fname
        try:
            if chunk_url not in chunk_cache:
                js_text, _, _ = fetch_text(chunk_url, timeout=35)
                chunk_cache[chunk_url] = js_text
            candidate = extract_chunk(chunk_cache[chunk_url])
            if candidate.get("metadata") or len(candidate.get("text", "")) > len(chunk_info.get("text", "")):
                chunk_info = candidate
                chunk_info["chunk_url"] = chunk_url
        except Exception as exc:
            chunk_error = repr(exc)

    html_len = len(html_info.get("text") or "")
    chunk_len = len(chunk_info.get("text") or "")
    if html_len >= 80:
        chosen = dict(html_info)
        mode = "html"
        if chunk_info.get("title") and (not chosen.get("title") or chosen.get("title") == "RDK X3/X5 DOC"):
            chosen["title"] = chunk_info["title"]
        if chunk_info.get("headings") and len(chosen.get("headings") or []) <= 1:
            chosen["headings"] = chunk_info["headings"]
        chosen["links"] = (html_info.get("links") or []) + (chunk_info.get("links") or [])
    elif chunk_len >= 30:
        chosen = dict(chunk_info)
        mode = "chunk"
    else:
        chosen = dict(html_info)
        mode = "empty_or_failed"

    title = clean_space(chosen.get("title") or chunk_info.get("title") or html_info.get("title") or route["doc_id"].split("/")[-1])
    title = title.replace(" | RDK X3/X5 DOC", "").strip() or route["path"].rsplit("/", 1)[-1]
    desc = clean_space(chosen.get("description") or chunk_info.get("description") or html_info.get("description") or "")
    text = clean_space(chosen.get("text") or "")
    headings = chosen.get("headings") or []

    page = dict(route)
    page.update({
        "url": page_url,
        "title": title,
        "description": desc,
        "summary": make_summary(title, desc, text),
        "text": text,
        "text_chars": len(text),
        "headings": headings,
        "extract_mode": mode,
        "html_error": html_error,
        "chunk_error": chunk_error,
        "chunk_url": chunk_info.get("chunk_url", ""),
        "group": path_group(route["path"]),
    })
    if page["extract_mode"] == "empty_or_failed" and page["text_chars"] > 0:
        page["extract_mode"] = "category_index"
        page["summary"] = (
            "该页是 Docusaurus 自动生成的分类索引页，官网静态内容主要是目录卡片和上下页导航；"
            "可作为章节入口使用，具体正文请打开其下级页面。"
            f" 页面可见文本：{page['text']}"
        )
    page["tags"] = tags_for(route, title, text)

    resources = []
    seen = set()
    for link in chosen.get("links") or []:
        url = (link.get("url") or "").strip()
        if url.startswith("//"):
            url = "https:" + url
        abs_url = urljoin(page_url, url)
        label = clean_space(link.get("text") or "")[:180]
        if is_resource(abs_url, label):
            key = (abs_url, label)
            if key in seen:
                continue
            seen.add(key)
            resources.append({
                "page_index": page["index"],
                "page_title": title,
                "page_path": route["path"],
                "kind": classify_resource(abs_url, label),
                "text": label,
                "url": abs_url,
                "extension": url_ext(abs_url),
            })
    return page, resources


def write_page_note(page, resources):
    fname = f"{page['index']:03d}_{sanitize_filename(page['title'])}_{hashlib.sha1(page['path'].encode('utf-8')).hexdigest()[:8]}.md"
    page["note_file"] = fname
    lines = [
        "---",
        "type: source_page",
        f"source: {yaml_quote(page['url'])}",
        f"doc_id: {yaml_quote(page.get('doc_id', ''))}",
        f"doc_path: {yaml_quote(page.get('path', ''))}",
        f"title: {yaml_quote(page.get('title', ''))}",
        f"created: {yaml_quote(CAPTURED_AT)}",
        f"tags: [{', '.join(page['tags'])}]",
        "---",
        "",
        f"# {page['title']}",
        "",
        "## 摘要",
        "",
        page["summary"],
        "",
        "## 官方链接",
        "",
        f"- [{page['path']}]({page['url']})",
    ]
    if page.get("source_md"):
        lines.append(f"- 源 Markdown：`{page['source_md']}`")
    lines.extend([
        f"- 抓取方式：`{page.get('extract_mode', 'unknown')}`；正文字符数：`{page.get('text_chars', 0)}`",
        "",
        "## 小节目录",
        "",
    ])
    if page.get("headings"):
        for heading in page["headings"][:40]:
            value = heading.get("value") or heading.get("title") or ""
            if value:
                lines.append(f"- H{heading.get('level', 2)} {value}")
    else:
        lines.append("- 未抽取到小节标题。")
    lines.extend(["", "## PDF/规格书/SDK/镜像等外部资源", ""])
    if resources:
        lines.extend(["| 类型 | 链接文字 | URL |", "|---|---|---|"])
        for item in resources[:80]:
            lines.append(f"| {md_escape_table(item['kind'])} | {md_escape_table(item.get('text') or '')} | {md_escape_table(item['url'])} |")
        if len(resources) > 80:
            lines.append(f"| 省略 | 本页还有 {len(resources) - 80} 条资源，见总资源清单。 |  |")
    else:
        lines.append("- 本页未识别到 PDF/规格书/SDK/镜像类外部文件链接。")
    excerpt = re.sub(r"\s+", " ", page.get("text", "")).strip()
    if len(excerpt) > 1400:
        excerpt = excerpt[:1400].rstrip() + "..."
    lines.extend(["", "## 检索摘录", "", excerpt or "无正文摘录。", ""])
    (PAGES_DIR / fname).write_text("\n".join(lines), encoding="utf-8")


def write_csv(path, rows, fields):
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_indexes(pages, resources, main_url, runtime_url):
    pages_by_group = defaultdict(list)
    for page in pages:
        pages_by_group[page["group"]].append(page)
    mode_counts = Counter(page["extract_mode"] for page in pages)
    resource_counts = Counter(item["kind"] for item in resources)
    x5_pages = [page for page in pages if "x5" in (page["path"] + " " + page["doc_id"] + " " + page["title"]).lower()]

    readme = [
        "---",
        "type: source_library",
        f"created: {yaml_quote(CAPTURED_AT)}",
        f"source: {yaml_quote(ROOT_URL)}",
        "tags: [RDK_X5, D-Robotics, 官方文档, Obsidian资料库]",
        "status: generated",
        "---",
        "",
        "# RDK X5 官方文档库",
        "",
        "这是从 D-Robotics RDK X3/X5 DOC 前端暴露的 `275` 个官方文档路由生成的可检索 Obsidian 资料库。每个页面都有独立笔记，包含标题、正文摘要、小节目录、官方链接和识别到的 PDF/规格书/SDK/镜像等外部资源。",
        "",
        "## 入口",
        "",
        "- [[RDK_X5_官方文档全量索引]]",
        "- [[RDK_X5_官方资料索引]]",
        "- [[RDK_X5_外部资源清单]]",
        "",
        "## 抓取状态",
        "",
        f"- 抓取时间：{CAPTURED_AT}",
        f"- 页面笔记：{len(pages)} 个",
        f"- RDK X5 路由相关页面：{len(x5_pages)} 个",
        f"- 外部/下载资源记录：{len(resources)} 条",
        f"- 提取方式统计：`{dict(mode_counts)}`",
        "",
        "## 数据文件",
        "",
        "- `_data/pages_index.json` / `_data/pages_index.csv`：页面索引",
        "- `_data/resources.json` / `_data/resources.csv`：外部资源清单",
        "- `_data/source_main_js_url.txt`：本次解析的 Docusaurus JS 入口",
        "",
    ]
    (LIB / "README.md").write_text("\n".join(readme), encoding="utf-8")

    res_lines = [
        "---",
        "type: source_index",
        f"created: {yaml_quote(CAPTURED_AT)}",
        f"source: {yaml_quote(ROOT_URL)}",
        "tags: [RDK_X5, D-Robotics, 下载资源, SDK, 镜像, 规格书]",
        "status: generated",
        "---",
        "",
        "# RDK X5 外部资源清单",
        "",
        f"- 资源记录：`{len(resources)}` 条",
        f"- 资源类型统计：`{dict(resource_counts)}`",
        "",
    ]
    for kind in sorted(resource_counts):
        res_lines.extend([f"## {kind}", "", "| 页面 | 链接文字 | URL |", "|---|---|---|"])
        for item in [r for r in resources if r["kind"] == kind]:
            page = pages[item["page_index"] - 1]
            res_lines.append(f"| [{md_escape_table(item['page_title'])}](pages/{page['note_file']}) | {md_escape_table(item.get('text') or '')} | {md_escape_table(item['url'])} |")
        res_lines.append("")
    (OUT_ROOT / "RDK_X5_外部资源清单.md").write_text("\n".join(res_lines), encoding="utf-8")
    (LIB / "RDK_X5_外部资源清单.md").write_text("\n".join(res_lines), encoding="utf-8")

    index = [
        "---",
        "type: source_index",
        f"created: {yaml_quote(CAPTURED_AT)}",
        f"source: {yaml_quote(ROOT_URL)}",
        "tags: [RDK_X5, D-Robotics, 官方文档, 全量索引, Obsidian资料库]",
        "status: generated_full",
        "---",
        "",
        "# RDK X3/X5 官方文档全量索引",
        "",
        "## 覆盖范围",
        "",
        f"- 官方入口：[D-Robotics RDK X3/X5 DOC]({ROOT_URL})。",
        f"- 路由来源：[Docusaurus main JS]({main_url})；runtime：[runtime JS]({runtime_url})。",
        f"- 抓取时间：{CAPTURED_AT}。",
        f"- 本资料库包含官网前端暴露的文档路由 `{len(pages)}` 个，并为每个路由生成逐页摘要笔记。",
        f"- 路径、标题或 ID 含 `x5` 的 RDK X5 相关页面 `{len(x5_pages)}` 个。",
        f"- PDF/规格书/SDK/镜像等外部资源记录 `{len(resources)}` 条，详见 [[RDK_X5_外部资源清单]]。",
        f"- 提取方式统计：`{dict(mode_counts)}`。",
        "",
        "> 注意：本库是官方网页的标题、摘要、目录和资源索引，不替代官网原文。涉及接口、管脚、烧录、系统、驱动、命令时，应打开对应官方链接核实当前版本。",
        "",
        "## 全站分组统计",
        "",
    ]
    for group, group_pages in sorted(pages_by_group.items()):
        index.append(f"- `{group}`：{len(group_pages)} 个")
    index.extend(["", "## RDK X5 相关页面", "", "| # | 标题 | 路径 | 摘要 |", "|---:|---|---|---|"])
    for page in x5_pages:
        note = f"RDK_X5_官方文档库/pages/{page['note_file']}"
        index.append(f"| {page['index']} | [{md_escape_table(page['title'])}]({note}) | `{md_escape_table(page['path'])}` | {md_escape_table(page['summary'][:180])} |")
    index.extend(["", "## 全量逐页索引", ""])
    for group in sorted(pages_by_group):
        index.extend([f"### {group}", "", "| # | 标题 | 路径 | 提取 | 资源 |", "|---:|---|---|---|---:|"])
        for page in pages_by_group[group]:
            note = f"RDK_X5_官方文档库/pages/{page['note_file']}"
            resource_count = sum(1 for item in resources if item["page_index"] == page["index"])
            index.append(f"| {page['index']} | [{md_escape_table(page['title'])}]({note}) | `{md_escape_table(page['path'])}` | `{page['extract_mode']}` | {resource_count} |")
        index.append("")
    (OUT_ROOT / "RDK_X5_官方文档全量索引.md").write_text("\n".join(index), encoding="utf-8")

    priority_paths = [
        "RDK",
        "Quick_start/download",
        "Quick_start/hardware_introduction/rdk_x5",
        "Quick_start/install_os/rdk_x5/system_burn",
        "Quick_start/install_os/rdk_x5/boot_system",
        "Quick_start/remote_login",
        "System_configuration/network_blueteeth",
        "Basic_Application/01_40pin_user_sample/40pin_define",
        "Basic_Application/01_40pin_user_sample/gpio",
        "Basic_Application/01_40pin_user_sample/uart",
        "Basic_Application/vision/RDK_X5/mipi_camera",
        "Basic_Application/vision/RDK_X5/usb_camera",
        "Basic_Application/multi_media_sp_dev_api/RDK_X5/overview",
        "Basic_Application/pydev_demo_sample/RDK_X5/overview",
        "Advanced_development/hardware_development/rdk_x5/hardware",
        "Advanced_development/linux_development/driver_development_x5",
        "Advanced_development/linux_development/driver_development_x5/driver_uart_dev",
        "Appendix/rdk-command-manual/cmd_rdkos_info",
        "Appendix/rdk-command-manual/cmd_hrut_boardid_rdkx5",
    ]
    by_suffix = {page["path"].replace("/rdk_x_doc/", "").rstrip("/"): page for page in pages}
    high = []
    for path in priority_paths:
        page = by_suffix.get(path.rstrip("/"))
        if page and page not in high:
            high.append(page)
    quick = [
        "---",
        "type: source_index",
        f"created: {yaml_quote(CAPTURED_AT)}",
        f"source: {yaml_quote(ROOT_URL)}",
        "tags: [RDK_X5, 地瓜机器人, D-Robotics, 官方文档, 嵌入式, 机器人]",
        "status: generated",
        "---",
        "",
        "# RDK X5 官方资料索引",
        "",
        "## 使用方式",
        "",
        "- 本页是 RDK X5 项目的高优先级官方资料入口；完整逐页库见 [[RDK_X5_官方文档全量索引]] 和 `RDK_X5_官方文档库/pages/`。",
        "- 后续做 RDK X5 项目时，先读本页，再按问题打开对应逐页笔记和官方链接核实。",
        "- 涉及接口、管脚、烧录、系统、驱动、命令时，不只看摘要，必须打开官方原文。",
        "",
        "## 快速入口",
        "",
        "| 场景 | 页面 | 摘要 |",
        "|---|---|---|",
    ]
    for page in high:
        note = f"RDK_X5_官方文档库/pages/{page['note_file']}"
        scene = " / ".join([t for t in page["tags"] if t not in {"RDK_X5", "D-Robotics", "官方文档"}][:3]) or page["group"]
        quick.append(f"| {md_escape_table(scene)} | [{md_escape_table(page['title'])}]({note}) | {md_escape_table(page['summary'][:220])} |")
    quick.extend([
        "",
        "## 本项目常用核查清单",
        "",
        "- 系统/镜像/烧录：先查下载资源汇总和 RDK X5 system_burn/boot_system。",
        "- 串口/GPIO/40Pin：先查 40Pin 管脚定义、GPIO 应用、串口应用，再结合项目现场笔记。",
        "- 摄像头/视觉：先区分 MIPI Camera、USB Camera、Python 示例、多媒体 API 和底层驱动开发。",
        "- 驱动/内核：先查 driver_development_x5 目录及具体 UART/GPIO/I2C/SPI/PWM 页面。",
        "- 下载资料：见 [[RDK_X5_外部资源清单]]；资源 URL 可能随官网更新，下载前以官网当前页面为准。",
        "",
        "## 相关链接",
        "",
        "- [[RDK_X5_官方文档全量索引]]",
        "- [[RDK_X5_外部资源清单]]",
        "- [[RDK_X5_官方文档库/README]]",
        "",
    ])
    (OUT_ROOT / "RDK_X5_官方资料索引.md").write_text("\n".join(quick), encoding="utf-8")


def main():
    for folder in (LIB, PAGES_DIR, DATA_DIR, TOOLS_DIR):
        folder.mkdir(parents=True, exist_ok=True)
    main_js, runtime_js, main_url, runtime_url = load_main_runtime()
    routes = parse_routes(main_js)
    chunk_filename = parse_runtime(runtime_js)
    chunk_cache = {}

    pages = []
    resources = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(page_worker, route, chunk_filename, chunk_cache) for route in routes]
        for future in as_completed(futures):
            page, page_resources = future.result()
            pages.append(page)
            resources.extend(page_resources)
    pages.sort(key=lambda item: item["index"])
    resources.sort(key=lambda item: (item["page_index"], item["kind"], item["url"]))

    for old in PAGES_DIR.glob("*.md"):
        old.unlink()
    by_page = defaultdict(list)
    for item in resources:
        by_page[item["page_index"]].append(item)
    for page in pages:
        write_page_note(page, by_page[page["index"]])

    compact_pages = []
    for page in pages:
        item = dict(page)
        item.pop("text", None)
        item["headings"] = (item.get("headings") or [])[:40]
        compact_pages.append(item)
    (DATA_DIR / "pages_index.json").write_text(json.dumps(compact_pages, ensure_ascii=False, indent=2), encoding="utf-8")
    (DATA_DIR / "resources.json").write_text(json.dumps(resources, ensure_ascii=False, indent=2), encoding="utf-8")
    write_csv(DATA_DIR / "pages_index.csv", compact_pages, ["index", "title", "path", "doc_id", "url", "group", "extract_mode", "text_chars", "summary", "note_file", "source_md", "content_hash", "props_hash", "chunk_url"])
    write_csv(DATA_DIR / "resources.csv", resources, ["page_index", "page_title", "page_path", "kind", "text", "url", "extension"])

    write_indexes(pages, resources, main_url, runtime_url)

    report = {
        "captured_at": CAPTURED_AT,
        "pages": len(pages),
        "page_notes": len(list(PAGES_DIR.glob("*.md"))),
        "resources": len(resources),
        "extract_modes": dict(Counter(page["extract_mode"] for page in pages)),
        "groups": dict(Counter(page["group"] for page in pages)),
        "resource_kinds": dict(Counter(item["kind"] for item in resources)),
        "empty_pages": [
            {"index": page["index"], "title": page["title"], "path": page["path"], "html_error": page.get("html_error"), "chunk_error": page.get("chunk_error")}
            for page in pages
            if page["extract_mode"] == "empty_or_failed"
        ],
    }
    (DATA_DIR / "build_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise
