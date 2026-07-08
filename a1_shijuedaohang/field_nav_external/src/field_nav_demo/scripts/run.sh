#!/bin/sh

# 板端启动脚本：在目标根文件系统 /field_nav 下运行 field_nav_demo。
# 输入来自环境变量 FIELD_NAV_*；输出为 exec 后的 field_nav_demo 进程。
cd /field_nav || exit 1

# Buildroot 打包时会把 @FIELD_NAV_MODEL_PATH@ 替换为配置项；未替换时使用默认模型。
MODEL_PATH="@FIELD_NAV_MODEL_PATH@"
if [ -z "$MODEL_PATH" ] || [ "${MODEL_PATH#@}" != "$MODEL_PATH" ]; then
    MODEL_PATH="app_assets/models/navroad_640x480.m1model"
fi
MODEL="/field_nav/$MODEL_PATH"
if [ ! -f "$MODEL" ]; then
    # 模型缺失时直接退出，避免程序启动后 ssne_loadmodel 失败难以定位。
    echo "[field_nav] missing model: $MODEL"
    echo "[field_nav] convert navroad_640x480.onnx to .m1model and rebuild the SDK"
    exit 1
fi
# 优先使用人脸 demo 共享 LUT；若不存在则回退到旧 colorLUT.sscl。
LUT="/field_nav/app_assets/shared_colorLUT.sscl"
if [ ! -f "$LUT" ]; then
    LUT="/field_nav/app_assets/colorLUT.sscl"
fi
if [ ! -f "$LUT" ]; then
    echo "[field_nav] missing OSD LUT: /field_nav/app_assets/shared_colorLUT.sscl"
    exit 1
fi

# 运行参数可由板端环境变量覆盖；默认值要与 main.cpp 的命令行默认值保持一致。
NAV_RATE="${FIELD_NAV_RATE:-10}"
SENSOR_FPS="${FIELD_NAV_SENSOR_FPS:-0}"
OSD_RATE="${FIELD_NAV_OSD_RATE:-15}"
TEST_SECONDS="${FIELD_NAV_TEST_SECONDS:-0}"

echo "[field_nav] run config: model=$MODEL lut=$LUT nav_uart=${FIELD_NAV_UART:-1} nav_baud=${FIELD_NAV_BAUD:-115200} nav_rate=${NAV_RATE} sensor_fps=${SENSOR_FPS} osd_rate=${OSD_RATE} test_seconds=${TEST_SECONDS}"

chmod +x ./field_nav_demo
# 用 exec 让 demo 成为当前脚本进程，退出码直接传给系统启动链路。
exec ./field_nav_demo \
    --model "$MODEL" \
    --lut "$LUT" \
    --nav-uart "${FIELD_NAV_UART:-1}" \
    --nav-baud "${FIELD_NAV_BAUD:-115200}" \
    --nav-rate "$NAV_RATE" \
    --sensor-fps "$SENSOR_FPS" \
    --osd-rate "$OSD_RATE" \
    --test-seconds "$TEST_SECONDS"
