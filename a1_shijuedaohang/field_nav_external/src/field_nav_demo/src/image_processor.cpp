#include "field_nav.hpp"

#include <cstdio>

namespace field_nav {

// 初始化在线图像管线。
// 输出：成功返回 true；失败打印 SDK 错误码。使用注意：这里固定裁剪 720x540 并输出 SSNE_Y_8 灰度图。
bool ImageProcessor::Initialize() {
    // 板端坐标约定：从原始 720x1280 中裁剪 y=370 起的近端道路区域，再交给模型 resize。
    OnlineSetCrop(kPipeline0, 0, kCropWidth, kCropOffsetY, kCropOffsetY + kCropHeight);
    OnlineSetOutputImage(kPipeline0, SSNE_Y_8, kCropWidth, kCropHeight);
    int ret = OpenOnlinePipeline(kPipeline0);
    if (ret != 0) {
        std::fprintf(stderr, "[field_nav] OpenOnlinePipeline failed: %d\n", ret);
        return false;
    }
    initialized_ = true;
    std::printf("[field_nav] online pipe0 opened, crop=%dx%d offset_y=%d\n",
                kCropWidth, kCropHeight, kCropOffsetY);
    return true;
}

// 获取一帧摄像头图像。
// 输入 img_sensor 为输出 tensor 指针；成功时 SDK 填充 pipeline0/sensor0 的灰度图像。
bool ImageProcessor::GetImage(ssne_tensor_t* img_sensor) {
    int ret = GetImageData(img_sensor, kPipeline0, kSensor0, 0);
    if (ret != 0) {
        std::fprintf(stderr, "[field_nav] GetImageData failed: %d\n", ret);
        return false;
    }
    return true;
}

// 关闭在线图像管线。
// 使用注意：只在 initialized_ 为 true 时关闭，避免重复 CloseOnlinePipeline。
void ImageProcessor::Release() {
    if (initialized_) {
        CloseOnlinePipeline(kPipeline0);
        initialized_ = false;
    }
}

}  // namespace field_nav
