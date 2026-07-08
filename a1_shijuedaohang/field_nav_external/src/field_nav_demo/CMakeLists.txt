cmake_minimum_required(VERSION 3.0.0)

project(field_nav_demo)

# 载入 M1 SDK 头文件和库路径；这些路径由 Buildroot 环境变量传入。
include(cmake_config/Paths.cmake)

# 板端目标是 C++11，开启 O3/NDEBUG，避免使用 C++17 语法。
set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -std=c++11 -O3 -DNDEBUG")
add_compile_options(-Wno-psabi)

# OSD 复用人脸 demo 的 osd-device.cpp；Buildroot package 通过 FIELD_NAV_FACE_DEMO_ROOT 指定源码路径。
set(FACE_DEMO_DIR "$ENV{FIELD_NAV_FACE_DEMO_ROOT}" CACHE PATH "Face demo source directory")
if(NOT EXISTS "${FACE_DEMO_DIR}/src/osd-device.cpp")
    message(FATAL_ERROR "FIELD_NAV_FACE_DEMO_ROOT is invalid: ${FACE_DEMO_DIR}")
endif()

# field_nav_demo 主程序由取图、推理后处理、OSD 和主循环四个自研源文件组成。
add_executable(field_nav_demo
    src/main.cpp
    src/image_processor.cpp
    src/navline_detector.cpp
    src/osd_overlay.cpp
    ${FACE_DEMO_DIR}/src/osd-device.cpp
)

# 头文件包含顺序：本 demo、复用的人脸 OSD 封装、M1 SDK 公共头和 smartsoc 子目录。
target_include_directories(field_nav_demo PRIVATE
    ${CMAKE_SOURCE_DIR}/include
    ${FACE_DEMO_DIR}/include
    ${M1_SDK_INC_DIR}
    ${M1_SDK_INC_DIR}/smartsoc
)

# 链接 SSNE/NPU、CMA buffer、OSD、GPIO、UART 以及 SDK 日志和 EMB 支撑库。
target_link_libraries(field_nav_demo
    ${M1_SSNE_LIB}
    ${M1_CMABUFFER_LIB}
    ${M1_OSD_LIB}
    ${M1_GPIO_LIB}
    ${M1_UART_LIB}
    ${M1_SSZLOG_LIB}
    ${M1_ZLOG_LIB}
    ${M1_EMB_LIB}
)

install(TARGETS field_nav_demo DESTINATION bin)
