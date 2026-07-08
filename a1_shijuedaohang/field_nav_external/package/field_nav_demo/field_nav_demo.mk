# Buildroot local package：从 field_nav_external/src/field_nav_demo 复制源码并用 cmake-package 构建。
FIELD_NAV_DEMO_VERSION =
FIELD_NAV_DEMO_SITE = $(BR2_EXTERNAL_FIELD_NAV_PATH)/src/field_nav_demo
FIELD_NAV_DEMO_SITE_METHOD = local
FIELD_NAV_DEMO_DEPENDENCIES = m1_sdk_lib

# 向 CMake 和 run.sh 传递 M1 SDK 根路径、模型相对路径以及人脸 demo 源码路径。
export EXPORT_LIB_M1_SDK_ROOT_PATH = $(call qstrip,$(BR2_M1_SDK_ROOT_PATH))
export FIELD_NAV_MODEL_PATH = $(call qstrip,$(BR2_FIELD_NAV_MODEL_PATH))
export FIELD_NAV_FACE_DEMO_ROOT = $(BR2_EXTERNAL_SMART_SOFTWARE_PATH)/src/app_demo/face_detection/ssne_ai_demo

# 安装目标根文件系统资源：demo 可执行文件、启动脚本、模型 assets 和 OSD LUT。
define FIELD_NAV_DEMO_INSTALL_TARGET_CMDS
	rm -rf $(TARGET_DIR)/field_nav
	mkdir -p $(TARGET_DIR)/field_nav/app_assets/models
	mkdir -p $(TARGET_DIR)/field_nav/scripts
	$(INSTALL) -D -m 0755 $(@D)/field_nav_demo $(TARGET_DIR)/field_nav/field_nav_demo
	$(INSTALL) -D -m 0755 $(@D)/scripts/run.sh $(TARGET_DIR)/field_nav/scripts/run.sh
	# 将 Buildroot 配置中的模型路径写入 run.sh，占位符未替换时脚本会使用默认模型。
	$(SED) 's|@FIELD_NAV_MODEL_PATH@|$(FIELD_NAV_MODEL_PATH)|g' \
		$(TARGET_DIR)/field_nav/scripts/run.sh
	cp -r $(@D)/app_assets/. $(TARGET_DIR)/field_nav/app_assets/
	# LUT 来自人脸 demo 已验证资源；field_nav_demo 启动时优先使用 shared_colorLUT.sscl。
	if [ -f "$(BR2_EXTERNAL_SMART_SOFTWARE_PATH)/src/app_demo/face_detection/ssne_ai_demo/app_assets/shared_colorLUT.sscl" ]; then \
		cp "$(BR2_EXTERNAL_SMART_SOFTWARE_PATH)/src/app_demo/face_detection/ssne_ai_demo/app_assets/shared_colorLUT.sscl" \
			$(TARGET_DIR)/field_nav/app_assets/shared_colorLUT.sscl; \
	fi
	if [ -f "$(BR2_EXTERNAL_SMART_SOFTWARE_PATH)/src/app_demo/face_detection/ssne_ai_demo/app_assets/colorLUT.sscl" ]; then \
		cp "$(BR2_EXTERNAL_SMART_SOFTWARE_PATH)/src/app_demo/face_detection/ssne_ai_demo/app_assets/colorLUT.sscl" \
			$(TARGET_DIR)/field_nav/app_assets/colorLUT.sscl; \
	fi
endef

$(eval $(cmake-package))
