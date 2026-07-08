#include "field_nav.hpp"

#include "osd-device.hpp"

#include <algorithm>
#include <array>
#include <cstdio>
#include <fstream>
#include <unistd.h>

namespace field_nav {

namespace {

// 复用人脸 demo 已验证的 OSD 设备封装，避免重新实现底层 OSD 初始化。
sst::device::osd::OsdDevice g_osd_device;

// 读取文件大小；输入路径，输出字节数，失败返回 -1。用于提前检查 LUT 是否存在且非空。
long FileSize(const std::string& path) {
    std::ifstream file(path.c_str(), std::ios::binary | std::ios::ate);
    if (!file) {
        return -1;
    }
    return static_cast<long>(file.tellg());
}

// 浮点数限幅；用于把 OSD 坐标限制在原始画面范围内。
float ClampFloat(float value, float low, float high) {
    return std::max(low, std::min(high, value));
}

// 规范化矩形框坐标。
// 输入 Box 可包含越界或 x/y 反向值；输出为 [x1,y1,x2,y2] 且限制在 720x1280 画面内。
std::array<float, 4> ClampBox(const Box& box) {
    float x1 = ClampFloat(static_cast<float>(box.x_min), 0.0f, static_cast<float>(kOriginalWidth - 1));
    float y1 = ClampFloat(static_cast<float>(box.y_min), 0.0f, static_cast<float>(kOriginalHeight - 1));
    float x2 = ClampFloat(static_cast<float>(box.x_max), 0.0f, static_cast<float>(kOriginalWidth - 1));
    float y2 = ClampFloat(static_cast<float>(box.y_max), 0.0f, static_cast<float>(kOriginalHeight - 1));
    if (x1 > x2) {
        std::swap(x1, x2);
    }
    if (y1 > y2) {
        std::swap(y1, y2);
    }
    return {x1, y1, x2, y2};
}

}  // namespace

// 初始化 OSD 叠加层。
// 输入 lut_path 为颜色查找表路径；成功后先画 3 秒测试框，便于确认 Aurora 画面叠加链路可用。
bool OsdOverlay::Initialize(const std::string& lut_path) {
    long lut_size = FileSize(lut_path);
    if (lut_size <= 0) {
        std::fprintf(stderr, "[field_nav] invalid OSD LUT: %s size=%ld\n", lut_path.c_str(), lut_size);
        return false;
    }

    g_osd_device.Initialize(kOriginalWidth, kOriginalHeight, lut_path.c_str());
    initialized_ = true;
    std::printf("[field_nav] osd initialized via face OsdDevice, layer=%dx%d lut=%s lut_size=%ld\n",
                kOriginalWidth, kOriginalHeight, lut_path.c_str(), lut_size);
    std::printf("[field_nav] osd startup test box should be visible for about 3 seconds\n");

    // 启动测试框位于中间摄像头画面，用于区分“OSD 链路失败”和“导航线无效”。
    std::vector<sst::device::osd::OsdQuadRangle> startup_box;
    sst::device::osd::OsdQuadRangle box{};
    box.box = {100.0f, 100.0f, 260.0f, 220.0f};
    box.border = 4;
    box.layer_id = 0;
    box.type = fdevice::TYPE_HOLLOW;
    box.alpha = fdevice::TYPE_ALPHA100;
    box.color = 1;
    startup_box.push_back(box);
    g_osd_device.Draw(startup_box, 0);
    usleep(3000000);
    Clear();
    usleep(200000);
    return true;
}

// 构造 OSD 矩形顶点。
// 输入 box/border，输出 out/in 两组顶点；当前实心/空心框都使用相同顶点。
void OsdOverlay::BuildBox(const Box& box, int border, fdevice::VERTEXS_S* out, fdevice::VERTEXS_S* in) const {
    if (out == nullptr || in == nullptr) {
        return;
    }

    Box expanded{
        box.x_min - border,
        box.y_min - border,
        box.x_max + border,
        box.y_max + border,
    };
    std::array<float, 4> clamped = ClampBox(expanded);
    int x1 = static_cast<int>(clamped[0]);
    int y1 = static_cast<int>(clamped[1]);
    int x2 = static_cast<int>(clamped[2]);
    int y2 = static_cast<int>(clamped[3]);

    out->points[0] = {x1, y1};
    out->points[1] = {x1, y2};
    out->points[2] = {x2, y2};
    out->points[3] = {x2, y1};
    *in = *out;
}

// 绘制一组矩形框。
// 输入 boxes/color/type；函数先清空本层再绘制新框，避免上一帧残留。
void OsdOverlay::DrawBoxes(const std::vector<Box>& boxes, int color, fdevice::QUADRANGLETYPE type) {
    if (!initialized_) {
        return;
    }

    std::vector<std::array<float, 4>> osd_boxes;
    osd_boxes.reserve(boxes.size());
    for (const auto& box : boxes) {
        std::array<float, 4> clamped = ClampBox(box);
        if ((clamped[2] - clamped[0]) >= 1.0f && (clamped[3] - clamped[1]) >= 1.0f) {
            osd_boxes.push_back(clamped);
        }
    }

    std::vector<std::array<float, 4>> empty;
    g_osd_device.Draw(empty, 0, 0, type, fdevice::TYPE_ALPHA100, color);
    if (osd_boxes.empty()) {
        return;
    }
    g_osd_device.Draw(osd_boxes, 0, 0, type, fdevice::TYPE_ALPHA100, color);
}

// 根据 NavLine 绘制导航线。
// 实现方式：沿拟合直线采样多个小方块，并在裁剪底部位置额外画大点标记近端控制点。
void OsdOverlay::DrawLine(const NavLine& line) {
    if (!line.valid) {
        Clear();
        return;
    }

    // 使用小方块近似线段，兼容当前 OsdDevice 的矩形绘制接口。
    std::vector<Box> boxes;
    const int half = 9;
    const int samples = 24;
    for (int i = 0; i < samples; ++i) {
        float t = static_cast<float>(i) / static_cast<float>(samples - 1);
        float y = kCropOffsetY + (kCropHeight - 1) * (1.0f - t);
        float x = line.slope * y + line.intercept;
        if (x >= 0.0f && x < kOriginalWidth && y >= 0.0f && y < kOriginalHeight) {
            boxes.push_back({static_cast<int>(x) - half, static_cast<int>(y) - half,
                             static_cast<int>(x) + half, static_cast<int>(y) + half});
        }
    }

    // 近端底部点最能反映偏航控制误差，因此单独加粗显示。
    float crop_bottom_y = static_cast<float>(kCropOffsetY + kCropHeight - 1);
    float crop_bottom_x = line.slope * crop_bottom_y + line.intercept;
    int bottom_x = static_cast<int>(
        ClampFloat(crop_bottom_x, 0.0f, static_cast<float>(kOriginalWidth - 1)));
    int bottom_y = kCropOffsetY + kCropHeight - 28;
    boxes.push_back({bottom_x - 18, bottom_y - 18, bottom_x + 18, bottom_y + 18});

    static int draw_count = 0;
    if ((draw_count++ % 30) == 0) {
        std::printf("[field_nav] osd draw line boxes=%zu crop_bottom=(%d,%d)\n",
                    boxes.size(), bottom_x, bottom_y);
    }

    DrawBoxes(boxes, 1, fdevice::TYPE_SOLID);
}

// 清空 OSD 当前层；用于无有效线、关闭或释放前，避免画面保留旧导航线。
void OsdOverlay::Clear() {
    if (!initialized_) {
        return;
    }
    std::vector<std::array<float, 4>> empty;
    g_osd_device.Draw(empty, 0, 0, fdevice::TYPE_SOLID, fdevice::TYPE_ALPHA100, 1);
}

// 释放 OSD 资源；先清屏再 Release，避免板端退出后残留叠加层。
void OsdOverlay::Release() {
    if (!initialized_) {
        return;
    }
    Clear();
    g_osd_device.Release();
    initialized_ = false;
}

}  // namespace field_nav
