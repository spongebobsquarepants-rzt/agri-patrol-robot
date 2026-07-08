#include "field_nav.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstddef>
#include <cstdio>
#include <cstdint>
#include <limits>
#include <vector>
#include <unistd.h>

namespace field_nav {

namespace {

// 模型概率转二值 mask 的阈值；调高会减少误检，调低会增加道路连通性。
constexpr float kMaskThreshold = 0.45f;
// 最小拟合点数；少于该值时直线最小二乘不稳定，直接判为无有效导航线。
constexpr int kMinValidPoints = 6;
// 串口诊断日志的打印间隔，避免每帧输出拖慢 Cortex-A7。
constexpr int kDiagIntervalFrames = 30;
// 低分辨率 mask 的纵向闭运算半径，用于修补田垄道路的短断裂。
constexpr int kMorphVerticalRadius = 3;
// 横向半径保持 0，避免把相邻垄沟横向错误粘连。
constexpr int kMorphHorizontalRadius = 0;
// 行带中心点提取高度；每 4 个 mask 像素合并成一个候选中心点。
constexpr int kBandHeight = 4;
// 连通域面积下限，小于该值的碎片视为噪声。
constexpr int kMinComponentArea = 30;
// 连续失败时最多沿用最近有效线 2 帧，避免瞬时抖动直接停车。
constexpr int kMaxFallbackFrames = 2;

// TensorStats 保存输出 tensor 的形状、数据类型和概率统计；只用于诊断日志。
struct TensorStats {
    int width = 0;
    int height = 0;
    uint8_t dtype = 0;
    int total = 0;
    float raw_min = 0.0f;
    float raw_max = 0.0f;
    float raw_mean = 0.0f;
    float prob_min = 0.0f;
    float prob_max = 0.0f;
    float prob_mean = 0.0f;
};

// LineDiag 记录每次后处理的关键计数，方便在 Aurora 串口日志中定位失败原因。
struct LineDiag {
    int scanned_rows = 0;
    int foreground_rows = 0;
    int points = 0;
    int component_count = 0;
    int main_area = 0;
    int band_points = 0;
    int fallback_count = 0;
    const char* reason = "not_run";
    const char* failure_reason = "none";
};

LineDiag g_line_diag;
// 最近一次可靠导航线；当前帧短暂失败时作为低置信度兜底输出。
NavLine g_last_valid_line;
// 是否已有可用于兜底的历史导航线。
bool g_has_last_valid_line = false;
// 连续失败帧数；超过 kMaxFallbackFrames 后停止兜底并输出 invalid。
int g_consecutive_failures = 0;

// Component 表示二值 mask 中的一个连通域，供主道路区域筛选使用。
struct Component {
    int label = -1;
    int area = 0;
    int min_x = 0;
    int max_x = 0;
    int min_y = 0;
    int max_y = 0;
    bool touches_bottom = false;
    bool touches_roi_top = false;
};

// ScratchBuffers 复用后处理临时内存，避免每帧频繁分配影响实时性。
struct ScratchBuffers {
    std::vector<float> probs;
    std::vector<uint8_t> mask;
    std::vector<uint8_t> morph_tmp;
    std::vector<uint8_t> closed_mask;
    std::vector<int> labels;
    std::vector<int> stack;
    std::vector<Component> components;
};

ScratchBuffers g_scratch;

// 计算两个 steady_clock 时间点的毫秒差；输入为起止时间，输出为 double 毫秒。
double ElapsedMs(std::chrono::steady_clock::time_point begin,
                 std::chrono::steady_clock::time_point end) {
    return std::chrono::duration_cast<std::chrono::microseconds>(end - begin).count() / 1000.0;
}

// 将模型原始输出转成概率。若输出已经在 0~1 范围内则原样返回，否则按 logit 做 sigmoid。
float Sigmoid(float value) {
    if (value >= 0.0f && value <= 1.0f) {
        return value;
    }
    return 1.0f / (1.0f + std::exp(-value));
}

// 把 SSNE tensor dtype 转成可读字符串；输入为 dtype 枚举，输出仅用于日志。
const char* DTypeName(uint8_t dtype) {
    if (dtype == SSNE_FLOAT32) {
        return "FLOAT32";
    }
    if (dtype == SSNE_INT8) {
        return "INT8";
    }
    if (dtype == SSNE_UINT8) {
        return "UINT8";
    }
    return "UNKNOWN_AS_UINT8";
}

// 从 tensor 原始内存中读取单个值；输入为 data/dtype/index，输出统一转为 float。
// 注意：INT8 这里先保留有符号原始值，后续 TensorProbabilityFromRaw 再映射到概率。
float TensorRawValueFromData(void* data, uint8_t dtype, int index) {
    if (data == nullptr) {
        return 0.0f;
    }

    if (dtype == SSNE_FLOAT32) {
        return static_cast<float*>(data)[index];
    }
    if (dtype == SSNE_INT8) {
        return static_cast<float>(static_cast<int>(static_cast<int8_t*>(data)[index]));
    }
    return static_cast<float>(static_cast<uint8_t*>(data)[index]);
}

// 读取 tensor 指定位置原始值；封装 dtype 和 data 查询，便于统计函数复用。
float TensorRawValue(const ssne_tensor_t& tensor, int index) {
    uint8_t dtype = get_data_type(tensor);
    void* data = get_data(tensor);
    return TensorRawValueFromData(data, dtype, index);
}

// 将 FLOAT32/INT8/UINT8 原始值统一映射到 0~1 概率。
// FLOAT32 视作 logit 或概率；INT8 按 [-128,127] 平移到 [0,255] 后归一化。
float TensorProbabilityFromRaw(float raw, uint8_t dtype) {
    if (dtype == SSNE_FLOAT32) {
        return Sigmoid(raw);
    }
    if (dtype == SSNE_INT8) {
        int value = static_cast<int>(raw) + 128;
        return std::max(0, std::min(255, value)) / 255.0f;
    }
    return std::max(0.0f, std::min(255.0f, raw)) / 255.0f;
}

// 读取 tensor 指定位置的道路概率；输出用于阈值分割和诊断统计。
float TensorProbability(const ssne_tensor_t& tensor, int index) {
    return TensorProbabilityFromRaw(TensorRawValue(tensor, index), get_data_type(tensor));
}

// 二维 mask 坐标转一维数组下标；调用方必须保证 x/y 在边界内。
int MaskIndex(int x, int y, int width) {
    return y * width + x;
}

// 对 ROI 内二值 mask 做纵向膨胀。
// 输入 mask/尺寸/ROI 起始行，输出 out；只处理 y_start 以下区域以忽略远处噪声。
void DilateMask(const std::vector<uint8_t>& mask,
                int width,
                int height,
                int y_start,
                std::vector<uint8_t>* out) {
    out->resize(mask.size());
    std::fill(out->begin(), out->end(), 0);
    for (int y = y_start; y < height; ++y) {
        for (int x = 0; x < width; ++x) {
            bool hit = false;
            for (int dy = -kMorphVerticalRadius; dy <= kMorphVerticalRadius && !hit; ++dy) {
                int yy = y + dy;
                if (yy < y_start || yy >= height) {
                    continue;
                }
                for (int dx = -kMorphHorizontalRadius; dx <= kMorphHorizontalRadius; ++dx) {
                    int xx = x + dx;
                    if (xx < 0 || xx >= width) {
                        continue;
                    }
                    if (mask[MaskIndex(xx, yy, width)] != 0) {
                        hit = true;
                        break;
                    }
                }
            }
            (*out)[MaskIndex(x, y, width)] = hit ? 1 : 0;
        }
    }
}

// 对 ROI 内二值 mask 做纵向腐蚀。
// 与 DilateMask 组合形成闭运算：先填小断裂，再收回边界。
void ErodeMask(const std::vector<uint8_t>& mask,
               int width,
               int height,
               int y_start,
               std::vector<uint8_t>* out) {
    out->resize(mask.size());
    std::fill(out->begin(), out->end(), 0);
    for (int y = y_start; y < height; ++y) {
        for (int x = 0; x < width; ++x) {
            bool keep = true;
            for (int dy = -kMorphVerticalRadius; dy <= kMorphVerticalRadius && keep; ++dy) {
                int yy = y + dy;
                if (yy < y_start || yy >= height) {
                    continue;
                }
                for (int dx = -kMorphHorizontalRadius; dx <= kMorphHorizontalRadius; ++dx) {
                    int xx = x + dx;
                    if (xx < 0 || xx >= width) {
                        continue;
                    }
                    if (mask[MaskIndex(xx, yy, width)] == 0) {
                        keep = false;
                        break;
                    }
                }
            }
            (*out)[MaskIndex(x, y, width)] = keep ? 1 : 0;
        }
    }
}

// 修补道路 mask 的纵向小裂缝。
// 原理：膨胀后腐蚀形成闭运算，并把原始前景强制保留，避免细道路被腐蚀掉。
void CloseVerticalGaps(const std::vector<uint8_t>& mask,
                       int width,
                       int height,
                       int y_start,
                       std::vector<uint8_t>* morph_tmp,
                       std::vector<uint8_t>* closed) {
    DilateMask(mask, width, height, y_start, morph_tmp);
    ErodeMask(*morph_tmp, width, height, y_start, closed);
    for (std::size_t i = 0; i < closed->size(); ++i) {
        if (mask[i] != 0) {
            (*closed)[i] = 1;
        }
    }
}

// 使用 4 邻域 DFS 标记连通域。
// 输入 closed mask，输出 labels/stack/components；小面积区域会被过滤掉。
void LabelComponents(const std::vector<uint8_t>& mask,
                     int width,
                     int height,
                     int y_start,
                     std::vector<int>* labels,
                     std::vector<int>* stack,
                     std::vector<Component>* components) {
    labels->assign(mask.size(), -1);
    components->clear();
    stack->clear();
    int next_label = 0;
    const int dx[4] = {1, -1, 0, 0};
    const int dy[4] = {0, 0, 1, -1};

    for (int y = y_start; y < height; ++y) {
        for (int x = 0; x < width; ++x) {
            int start_idx = MaskIndex(x, y, width);
            if (mask[start_idx] == 0 || (*labels)[start_idx] >= 0) {
                continue;
            }

            Component comp;
            comp.label = next_label++;
            comp.min_x = comp.max_x = x;
            comp.min_y = comp.max_y = y;
            stack->clear();
            stack->push_back(start_idx);
            (*labels)[start_idx] = comp.label;

            while (!stack->empty()) {
                int idx = stack->back();
                stack->pop_back();
                int cx = idx % width;
                int cy = idx / width;
                ++comp.area;
                comp.min_x = std::min(comp.min_x, cx);
                comp.max_x = std::max(comp.max_x, cx);
                comp.min_y = std::min(comp.min_y, cy);
                comp.max_y = std::max(comp.max_y, cy);

                for (int k = 0; k < 4; ++k) {
                    int nx = cx + dx[k];
                    int ny = cy + dy[k];
                    if (nx < 0 || nx >= width || ny < y_start || ny >= height) {
                        continue;
                    }
                    int nidx = MaskIndex(nx, ny, width);
                    if (mask[nidx] != 0 && (*labels)[nidx] < 0) {
                        (*labels)[nidx] = comp.label;
                        stack->push_back(nidx);
                    }
                }
            }

            comp.touches_bottom = comp.max_y >= height - 2;
            comp.touches_roi_top = comp.min_y <= y_start + kBandHeight;
            if (comp.area >= kMinComponentArea) {
                components->push_back(comp);
            }
        }
    }
}

// 根据上一帧导航线预测当前 mask 行的期望 x 位置。
// 没有历史线时回到图像中心，用于 SelectMainComponent 的靠近中心/历史惩罚项。
float ExpectedMaskXFromLastLine(int width, int height, int y_mask) {
    if (!g_has_last_valid_line) {
        return width * 0.5f;
    }
    float original_y = kCropOffsetY +
        y_mask * static_cast<float>(kCropHeight) / static_cast<float>(std::max(1, height - 1));
    float original_x = g_last_valid_line.slope * original_y + g_last_valid_line.intercept;
    return original_x * static_cast<float>(std::max(1, width - 1)) / static_cast<float>(kCropWidth);
}

// 从候选连通域中选择最可能的主道路区域。
// 评分偏好触底、纵向跨度大、面积大、贯通 ROI 且接近上一帧/图像中心的区域。
int SelectMainComponent(const std::vector<Component>& components, int width, int height, int y_start) {
    if (components.empty()) {
        return -1;
    }

    const int roi_height = std::max(1, height - y_start);
    float best_score = -std::numeric_limits<float>::max();
    int best_label = -1;

    for (const auto& comp : components) {
        int span_y = comp.max_y - comp.min_y + 1;
        bool through_domain = comp.touches_bottom && span_y >= std::max(4, roi_height * 35 / 100);
        float center_x = (comp.min_x + comp.max_x) * 0.5f;
        float target_x = ExpectedMaskXFromLastLine(width, height, comp.max_y);
        float center_penalty = std::fabs(center_x - target_x);

        float score = static_cast<float>(comp.area);
        score += static_cast<float>(span_y * width) * 0.25f;
        if (comp.touches_bottom) {
            score += static_cast<float>(width * height);
        }
        if (through_domain || comp.touches_roi_top) {
            score += static_cast<float>(width * height) * 0.5f;
        }
        score -= center_penalty * 2.0f;

        if (score > best_score) {
            best_score = score;
            best_label = comp.label;
        }
    }

    return best_label;
}

// 对 NavLine::points 做 x = slope * y + intercept 的最小二乘拟合。
// 输入输出均为 line；失败时通过 reason 返回原因，成功时填充 bottom_x/deviation/angle/confidence。
bool FitLeastSquares(NavLine* line, const char** reason) {
    if (line->points.size() < kMinValidPoints) {
        *reason = "points_below_min";
        return false;
    }

    float sum_y = 0.0f;
    float sum_x = 0.0f;
    float sum_yy = 0.0f;
    float sum_yx = 0.0f;
    float sum_conf = 0.0f;
    for (const auto& p : line->points) {
        sum_y += p.y;
        sum_x += p.x;
        sum_yy += p.y * p.y;
        sum_yx += p.y * p.x;
        sum_conf += p.confidence;
    }

    float n = static_cast<float>(line->points.size());
    float denom = n * sum_yy - sum_y * sum_y;
    if (std::fabs(denom) < 1e-4f) {
        *reason = "degenerate_fit";
        return false;
    }

    line->slope = (n * sum_yx - sum_y * sum_x) / denom;
    line->intercept = (sum_x - line->slope * sum_y) / n;
    line->bottom_x = line->slope * (kOriginalHeight - 1) + line->intercept;
    line->deviation_px = line->bottom_x - (kOriginalWidth / 2.0f);
    line->angle_deg = std::atan(line->slope) * 180.0f / 3.14159265f;
    line->confidence = sum_conf / n;
    line->valid = true;
    *reason = "ok";
    return true;
}

// 统一处理后处理失败。
// 若最近有效线仍在允许帧数内，则降低置信度后返回兜底线；否则返回 invalid line。
NavLine FailWithFallback(const NavLine& line, const char* reason) {
    g_line_diag.failure_reason = reason;
    if (g_has_last_valid_line && g_consecutive_failures < kMaxFallbackFrames) {
        ++g_consecutive_failures;
        NavLine fallback = g_last_valid_line;
        fallback.confidence *= 0.5f;
        for (auto& p : fallback.points) {
            p.confidence *= 0.5f;
        }
        g_line_diag.fallback_count = g_consecutive_failures;
        g_line_diag.reason = "fallback_last_valid";
        return fallback;
    }

    ++g_consecutive_failures;
    g_line_diag.reason = reason;
    return line;
}

// 统计输出 tensor 的原始值和概率范围。
// 输入为 SSNE 输出 tensor；输出 TensorStats 只用于低频日志，不参与控制决策。
TensorStats ComputeStats(const ssne_tensor_t& tensor) {
    TensorStats stats;
    stats.width = static_cast<int>(get_width(tensor));
    stats.height = static_cast<int>(get_height(tensor));
    stats.dtype = get_data_type(tensor);
    stats.total = stats.width * stats.height;

    if (stats.width <= 0 || stats.height <= 0 || get_data(tensor) == nullptr) {
        return stats;
    }

    float raw_min = std::numeric_limits<float>::max();
    float raw_max = -std::numeric_limits<float>::max();
    float prob_min = std::numeric_limits<float>::max();
    float prob_max = -std::numeric_limits<float>::max();
    double raw_sum = 0.0;
    double prob_sum = 0.0;

    for (int i = 0; i < stats.total; ++i) {
        float raw = TensorRawValue(tensor, i);
        float prob = TensorProbabilityFromRaw(raw, stats.dtype);
        raw_min = std::min(raw_min, raw);
        raw_max = std::max(raw_max, raw);
        prob_min = std::min(prob_min, prob);
        prob_max = std::max(prob_max, prob);
        raw_sum += raw;
        prob_sum += prob;
    }

    stats.raw_min = raw_min;
    stats.raw_max = raw_max;
    stats.raw_mean = static_cast<float>(raw_sum / std::max(1, stats.total));
    stats.prob_min = prob_min;
    stats.prob_max = prob_max;
    stats.prob_mean = static_cast<float>(prob_sum / std::max(1, stats.total));
    return stats;
}

}  // namespace

// 初始化导航线检测器。
// 输入 model_path 为板端 .m1model 路径；成功后创建 640x480 灰度输入 tensor 和 AI 预处理管线。
bool NavLineDetector::Initialize(const std::string& model_path) {
    if (!FileExists(model_path)) {
        std::fprintf(stderr, "[field_nav] model file does not exist: %s\n", model_path.c_str());
        return false;
    }
    // ssne_loadmodel 的接口需要非 const char*，这里仅适配 SDK 签名，不修改字符串内容。
    char* model_path_c = const_cast<char*>(model_path.c_str());
    model_id_ = ssne_loadmodel(model_path_c, SSNE_STATIC_ALLOC);
    // model_id 允许为 0，不能据此判断失败；通过查询输入数量确认模型是否真的可用。
    int input_num = ssne_get_model_input_num(model_id_);
    if (input_num <= 0) {
        std::fprintf(stderr, "[field_nav] ssne_loadmodel or model query failed: %s model_id=%u input_num=%d\n",
                     model_path.c_str(), model_id_, input_num);
        return false;
    }
    int input_dtype = -1;
    int dtype_ret = ssne_get_model_input_dtype(model_id_, &input_dtype);

    // 板端模型约定输入为 1x480x640 灰度图，tensor 放在 AI buffer 便于 NPU 推理。
    input_ = create_tensor(kModelWidth, kModelHeight, SSNE_Y_8, SSNE_BUF_AI);
    if (get_data(input_) == nullptr) {
        std::fprintf(stderr, "[field_nav] create_tensor failed for %dx%d SSNE_Y_8 input\n",
                     kModelWidth, kModelHeight);
        return false;
    }

    preprocess_ = GetAIPreprocessPipe();
    if (preprocess_ == nullptr) {
        std::fprintf(stderr, "[field_nav] GetAIPreprocessPipe failed\n");
        release_tensor(input_);
        input_ = {};
        return false;
    }
    initialized_ = true;
    std::printf("[field_nav] model loaded: %s model_id=%u input_num=%d input_dtype=%d dtype_ret=%d\n",
                model_path.c_str(), model_id_, input_num, input_dtype, dtype_ret);
    return true;
}

// 对单帧图像执行预处理、NPU 推理和导航线后处理。
// 输入 img 为摄像头裁剪后的灰度 tensor，输出 line 为当前帧 NavLine；返回 false 表示推理链路失败。
bool NavLineDetector::Predict(ssne_tensor_t* img, NavLine* line) {
    static int frame = 0;
    const bool diag_frame = (frame++ % kDiagIntervalFrames) == 0;

    // 1. AI 预处理：把摄像头输出 tensor 转成模型输入 tensor。
    auto preprocess_start = std::chrono::steady_clock::now();
    int ret = RunAiPreprocessPipe(preprocess_, *img, input_);
    auto preprocess_end = std::chrono::steady_clock::now();
    if (ret != 0) {
        std::fprintf(stderr, "[field_nav] RunAiPreprocessPipe failed: %d\n", ret);
        return false;
    }
    // 2. NPU 推理：只传入一个灰度输入 tensor，输出稍后通过 ssne_getoutput 取得。
    auto inference_start = std::chrono::steady_clock::now();
    ret = ssne_inference(model_id_, 1, &input_);
    auto inference_end = std::chrono::steady_clock::now();
    if (ret != 0) {
        std::fprintf(stderr, "[field_nav] ssne_inference failed: %d\n", ret);
        return false;
    }
    // 3. 获取输出：输出尺寸和 dtype 由运行时返回，后处理不硬编码 120x160。
    auto getoutput_start = std::chrono::steady_clock::now();
    ret = ssne_getoutput(model_id_, 1, &output_);
    auto getoutput_end = std::chrono::steady_clock::now();
    if (ret != 0) {
        std::fprintf(stderr, "[field_nav] ssne_getoutput failed: %d\n", ret);
        return false;
    }
    if (get_data(output_) == nullptr) {
        std::fprintf(stderr, "[field_nav] ssne_getoutput returned empty output tensor\n");
        return false;
    }

    int output_width = static_cast<int>(get_width(output_));
    int output_height = static_cast<int>(get_height(output_));
    uint8_t output_dtype = get_data_type(output_);
    static int last_width = -1;
    static int last_height = -1;
    static int last_dtype = -1;
    if (output_width != last_width || output_height != last_height || output_dtype != last_dtype) {
        std::printf("[field_nav] output tensor width=%d height=%d dtype=%u(%s)\n",
                    output_width, output_height, output_dtype, DTypeName(output_dtype));
        last_width = output_width;
        last_height = output_height;
        last_dtype = output_dtype;
    }

    // 4. CPU 后处理：概率图 -> mask -> 主连通域 -> 行带中心点 -> 最小二乘导航线。
    auto postprocess_start = std::chrono::steady_clock::now();
    *line = ExtractLine(output_);
    auto postprocess_end = std::chrono::steady_clock::now();

    if (diag_frame) {
        TensorStats stats = ComputeStats(output_);
        std::printf("[field_nav] perf preprocess_ms=%.3f inference_ms=%.3f getoutput_ms=%.3f "
                    "postprocess_ms=%.3f\n",
                    ElapsedMs(preprocess_start, preprocess_end),
                    ElapsedMs(inference_start, inference_end),
                    ElapsedMs(getoutput_start, getoutput_end),
                    ElapsedMs(postprocess_start, postprocess_end));
        std::printf("[field_nav] output stats raw=[%.4f, %.4f, %.4f] prob=[%.4f, %.4f, %.4f] "
                    "threshold=%.2f scanned=%d fg_rows=%d components=%d main_area=%d "
                    "band_points=%d points=%d fallback=%d valid=%d reason=%s failure=%s\n",
                    stats.raw_min, stats.raw_max, stats.raw_mean,
                    stats.prob_min, stats.prob_max, stats.prob_mean,
                    kMaskThreshold, g_line_diag.scanned_rows, g_line_diag.foreground_rows,
                    g_line_diag.component_count, g_line_diag.main_area, g_line_diag.band_points,
                    g_line_diag.points, g_line_diag.fallback_count, line->valid ? 1 : 0,
                    g_line_diag.reason, g_line_diag.failure_reason);
    }
    return true;
}

// 暴露单点概率读取接口；输入 tensor/index，输出 0~1 道路概率，主要用于测试或诊断。
float NavLineDetector::TensorValue(const ssne_tensor_t& tensor, int index) const {
    return TensorProbability(tensor, index);
}

// 从模型输出概率图提取导航线。
// 算法：阈值分割 -> 纵向闭运算 -> 连通域筛选 -> 行带概率加权中心 -> 最小二乘直线拟合。
NavLine NavLineDetector::ExtractLine(const ssne_tensor_t& output) const {
    NavLine line;
    g_line_diag = LineDiag{};

    int width = static_cast<int>(get_width(output));
    int height = static_cast<int>(get_height(output));
    if (width <= 0 || height <= 0) {
        return FailWithFallback(line, "invalid_output_shape");
    }

    const int total = width * height;
    // 只处理输出图下方约 65% 区域；远处道路像素少且噪声大，对近端控制贡献有限。
    const int y_start = static_cast<int>(height * 0.35f);
    ScratchBuffers& scratch = g_scratch;
    scratch.probs.resize(total);
    scratch.mask.resize(total);
    std::fill(scratch.mask.begin(), scratch.mask.end(), 0);
    line.points.reserve(std::max(1, (height - y_start + kBandHeight - 1) / kBandHeight));

    void* output_data = get_data(output);
    uint8_t output_dtype = get_data_type(output);

    // 将输出 tensor 转成概率数组和二值 mask；probs 保留原概率用于后续加权中心。
    for (int y = y_start; y < height; ++y) {
        for (int x = 0; x < width; ++x) {
            int idx = MaskIndex(x, y, width);
            float raw = TensorRawValueFromData(output_data, output_dtype, idx);
            float prob = TensorProbabilityFromRaw(raw, output_dtype);
            scratch.probs[idx] = prob;
            scratch.mask[idx] = prob >= kMaskThreshold ? 1 : 0;
        }
    }

    // TDM-LS 前的轻量形态学：优先在低分辨率 mask 上修补纵向断裂，降低 CPU 开销。
    CloseVerticalGaps(scratch.mask, width, height, y_start, &scratch.morph_tmp, &scratch.closed_mask);
    LabelComponents(scratch.closed_mask, width, height, y_start,
                    &scratch.labels, &scratch.stack, &scratch.components);
    g_line_diag.component_count = static_cast<int>(scratch.components.size());
    if (scratch.components.empty()) {
        return FailWithFallback(line, "no_components");
    }

    // 在多个候选前景块中选择主道路；失败时进入历史线兜底逻辑。
    int main_label = SelectMainComponent(scratch.components, width, height, y_start);
    if (main_label < 0) {
        return FailWithFallback(line, "no_main_component");
    }

    for (const auto& comp : scratch.components) {
        if (comp.label == main_label) {
            g_line_diag.main_area = comp.area;
            break;
        }
    }

    // 从近端向远端扫描水平行带，每个行带输出一个概率加权中心点。
    for (int y1 = height - 1; y1 >= y_start; y1 -= kBandHeight) {
        ++g_line_diag.scanned_rows;

        int y0 = std::max(y_start, y1 - kBandHeight + 1);
        float weighted_x = 0.0f;
        float weighted_y = 0.0f;
        float weight = 0.0f;
        int pixels = 0;

        for (int y = y0; y <= y1; ++y) {
            for (int x = 0; x < width; ++x) {
                int idx = MaskIndex(x, y, width);
                if (scratch.labels[idx] == main_label) {
                    float prob = std::max(scratch.probs[idx], kMaskThreshold);
                    weighted_x += prob * x;
                    weighted_y += prob * y;
                    weight += prob;
                    ++pixels;
                }
            }
        }

        if (pixels > 0 && weight > 1e-5f) {
            ++g_line_diag.foreground_rows;
            ++g_line_diag.band_points;
            float cx = weighted_x / weight;
            float cy = weighted_y / weight;
            // 将低分辨率输出坐标映射回原始 720x1280 坐标系，供 OSD 和 UART 统一使用。
            float original_x = cx * static_cast<float>(kCropWidth) / static_cast<float>(std::max(1, width - 1));
            float original_y = kCropOffsetY +
                cy * static_cast<float>(kCropHeight) / static_cast<float>(std::max(1, height - 1));
            line.points.push_back({original_x, original_y, weight / std::max(1, pixels)});
        }
    }

    g_line_diag.points = static_cast<int>(line.points.size());
    if (g_line_diag.foreground_rows == 0) {
        return FailWithFallback(line, "no_foreground_bands");
    }

    // 用中心点拟合近似导航直线；拟合失败说明点数不足或几何退化。
    const char* fit_reason = "not_run";
    if (!FitLeastSquares(&line, &fit_reason)) {
        return FailWithFallback(line, fit_reason);
    }

    g_last_valid_line = line;
    g_has_last_valid_line = true;
    g_consecutive_failures = 0;
    g_line_diag.reason = "ok_tdm_ls";
    return line;
}

// 释放检测器持有的 tensor 和 AI 预处理管线。
// 注意：底层 SSNE 运行时由 main.cpp 最后统一调用 ssne_release()。
void NavLineDetector::Release() {
    if (initialized_) {
        if (get_data(output_) != nullptr) {
            release_tensor(output_);
            output_ = {};
        }
        if (get_data(input_) != nullptr) {
            release_tensor(input_);
            input_ = {};
        }
        if (preprocess_ != nullptr) {
            ReleaseAIPreprocessPipe(preprocess_);
            preprocess_ = nullptr;
        }
        initialized_ = false;
    }
}

}  // namespace field_nav
