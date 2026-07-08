#!/bin/sh

# 板端 rootfs overlay 自启动脚本：先加载 field_nav_demo 需要的内核模块，再启动 /field_nav/scripts/run.sh。
kernel_ver="`uname -r`"
ko_dir="/lib/modules/${kernel_ver}/extra"

# 下面模块顺序沿用 SDK 启动链路；摄像头、NPU、OSD、GPIO 和 UART 都依赖这些驱动。
insmod ${ko_dir}/ddr_mmap.ko
insmod ${ko_dir}/ocm.ko
insmod ${ko_dir}/emb.ko
insmod ${ko_dir}/preoffline.ko
insmod ${ko_dir}/preonpipe.ko
insmod ${ko_dir}/lnpu.ko
insmod ${ko_dir}/osd_kmod.ko
insmod ${ko_dir}/isp_debug.ko
insmod ${ko_dir}/axi_dma.ko
insmod ${ko_dir}/aec.ko
insmod ${ko_dir}/gpio_kmod.ko
insmod ${ko_dir}/uart_kmod.ko

# 进入导航 demo 启动脚本，由 run.sh 再检查模型、LUT 和运行参数。
/bin/sh /field_nav/scripts/run.sh
