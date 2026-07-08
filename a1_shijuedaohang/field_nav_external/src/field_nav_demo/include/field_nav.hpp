#pragma once

#include <array>
#include <csignal>
#include <cstdint>
#include <string>
#include <vector>

#include "smartsoc/osd_lib_api.h"
#include "smartsoc/ssne_api.h"

namespace field_nav {

constexpr int kOriginalWidth = 720;
constexpr int kOriginalHeight = 1280;
constexpr int kCropWidth = 720;
constexpr int kCropHeight = 540;
constexpr int kCropOffsetY = 370;
constexpr int kModelWidth = 640;
constexpr int kModelHeight = 480;

struct Box {
    int x_min;
    int y_min;
    int x_max;
    int y_max;
};

struct NavPoint {
    float x;
    float y;
    float confidence;
};

struct NavLine {
    bool valid = false;
    float slope = 0.0f;
    float intercept = 0.0f;
    float bottom_x = 0.0f;
    float deviation_px = 0.0f;
    float angle_deg = 0.0f;
    float confidence = 0.0f;
    std::vector<NavPoint> points;
};

class ImageProcessor {
  public:
    bool Initialize();
    bool GetImage(ssne_tensor_t* img_sensor);
    void Release();

  private:
    bool initialized_ = false;
};

class NavLineDetector {
  public:
    bool Initialize(const std::string& model_path);
    bool Predict(ssne_tensor_t* img, NavLine* line);
    void Release();

  private:
    float TensorValue(const ssne_tensor_t& tensor, int index) const;
    NavLine ExtractLine(const ssne_tensor_t& output) const;

    uint16_t model_id_ = 0;
    ssne_tensor_t input_{};
    ssne_tensor_t output_{};
    AiPreprocessPipe preprocess_ = nullptr;
    bool initialized_ = false;
};

class OsdOverlay {
  public:
    bool Initialize(const std::string& lut_path);
    void DrawLine(const NavLine& line);
    void Clear();
    void Release();

  private:
    void BuildBox(const Box& box, int border, fdevice::VERTEXS_S* out, fdevice::VERTEXS_S* in) const;
    void DrawBoxes(const std::vector<Box>& boxes, int color, fdevice::QUADRANGLETYPE type);

    handle_t handle_ = INVALID_HANDLE;
    fdevice::DMA_BUFFER_ATTR_S dma_{};
    std::vector<uint8_t> lut_data_;
    bool initialized_ = false;
};

bool FileExists(const std::string& path);

}  // namespace field_nav
