#!/bin/bash

# Linux SDK 容器中的一键构建脚本；Windows PowerShell 不能直接完整执行 Buildroot 构建。
set -e

# 解析脚本、BR2_EXTERNAL 和 SDK 根目录；后续命令都基于这些绝对路径执行。
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]-$0}")" && pwd)
EXTERNAL_DIR=$(cd "${SCRIPT_DIR}/.." && pwd)
ROOT_DIR=$(cd "${EXTERNAL_DIR}/.." && pwd)
CACHE_DIR=${ROOT_DIR}/cache

# 先让 SDK 原始脚本准备 dl/cache 依赖，避免 Buildroot 后续缺包。
bash "${ROOT_DIR}/scripts/build_dl.sh"

echo ">> checking toolchain"
# 工具链只在缺失时从 cache 解压；已存在时不重复覆盖。
if [[ -d "${ROOT_DIR}/smart_software/toolchain/glibc-ssp-cpp" ]]; then
    echo "toolchain exist"
else
    mkdir -p "${ROOT_DIR}/smart_software/toolchain"
    cd "${ROOT_DIR}/smart_software/toolchain/"
    tar -xvf "${CACHE_DIR}/glibc-ssp-cpp.tar.gz"
    cd "${ROOT_DIR}"
fi
echo ">> checking toolchain done!"

echo ">> checking package"
# Buildroot package 目录缺失时从 SDK cache 恢复。
if [[ -d "${ROOT_DIR}/package" ]]; then
    echo "package exist"
else
    cd "${ROOT_DIR}"
    tar -xvf "${CACHE_DIR}/package.tar.gz"
    cd "${ROOT_DIR}"
fi
echo ">> checking package done!"

echo ">> checking kernel src"
# 内核源码缺失时解压并打 A1 SDK 补丁；已有源码时不重复 patch。
if [[ -d "${ROOT_DIR}/smart_software/src/linux-5.15.24" ]]; then
    echo "linux-5.15.24 exist"
else
    cd "${ROOT_DIR}/smart_software/src"
    tar -xvf "${CACHE_DIR}/linux-5.15.24.tar.gz"
    cd linux-5.15.24
    patch -p1 < "${ROOT_DIR}/patch/0001-Add-support-of-A1.patch"
    cd "${ROOT_DIR}"
fi
echo ">> checking kernel src done!"

# 检查板端模型是否放入 field_nav_demo assets；缺失只警告，便于先验证源码构建链路。
MODEL="${EXTERNAL_DIR}/src/field_nav_demo/app_assets/models/navroad_640x480.m1model"
if [[ ! -f "${MODEL}" ]]; then
    echo "WARNING: ${MODEL} is missing."
    echo "The image can still build, but /field_nav/scripts/run.sh will exit until the model is provided."
fi

export LD_LIBRARY_PATH=
cd "${ROOT_DIR}"
# 使用 smart_software 和 field_nav_external 两个 BR2_EXTERNAL 共同生成导航镜像配置。
make BR2_EXTERNAL=./smart_software:./field_nav_external field_nav_m1pro_defconfig
echo ">> cleaning field_nav_demo build cache"
# dirclean 强制 Buildroot 丢弃旧 field_nav_demo 缓存，确保重新复制最新源码。
make BR2_EXTERNAL=./smart_software:./field_nav_external field_nav_demo-dirclean
# 并行完整构建最终 zImage.smartsens-m1-evb。
make -j"$(nproc)"

echo "field navigation image: ${ROOT_DIR}/output/images/zImage.smartsens-m1-evb"
