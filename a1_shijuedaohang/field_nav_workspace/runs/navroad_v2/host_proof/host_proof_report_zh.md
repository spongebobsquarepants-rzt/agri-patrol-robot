# 主机侧模型与导航线证明报告

## 目的

开发板暂时跑不起来时，先在 Windows 主机上证明两件事：

1. `navroad_v2` 模型能从 640x480 灰度图输出可通行区域 mask。
2. 与板端 `field_nav_demo` 接近的行扫描后处理，能从模型输出中提取导航线。

## 本次运行

- 数据目录：`D:\1.1.1.1.1\field_nav_workspace\data\processed_v2_640x480`
- 模型权重：`D:\1.1.1.1.1\field_nav_workspace\runs\navroad_v2\best.pt`
- 测试集：`test`
- 样本数：`32`
- mask 阈值：`0.45`
- 证明脚本：`D:\1.1.1.1.1\field_nav_workspace\tools\prove_navroad_host.py`

## 输出文件

- 汇总指标：`D:\1.1.1.1.1\field_nav_workspace\runs\navroad_v2\host_proof\proof_metrics.json`
- 每张图的结果表：`D:\1.1.1.1.1\field_nav_workspace\runs\navroad_v2\host_proof\proof_samples.csv`
- 可视化拼图：`D:\1.1.1.1.1\field_nav_workspace\runs\navroad_v2\host_proof\contact_sheet.jpg`
- 单张 overlay：`D:\1.1.1.1.1\field_nav_workspace\runs\navroad_v2\host_proof\overlays`
- 预测 mask：`D:\1.1.1.1.1\field_nav_workspace\runs\navroad_v2\host_proof\pred_masks`

## 结果

```json
{
  "split": "test",
  "samples": 32,
  "threshold": 0.45,
  "mean_iou": 0.49924806545337924,
  "median_iou": 0.4751195966880043,
  "valid_navline_samples": 32,
  "invalid_navline_samples": 0,
  "target_valid_navline_samples": 31,
  "mean_line_error_px_original720": 86.92143173487428,
  "mean_crop_bottom_error_px_original720": 100.02548426407729
}
```

## 解释

- `valid_navline_samples = 32/32`：模型输出经过行扫描后处理后，32 张测试图都能得到有效导航线。
- `invalid_navline_samples = 0`：没有出现完全提取不出导航线的测试样本。
- `mean_iou ≈ 0.499`：模型能分割出道路区域，但分割质量还没有达到高质量标准。
- `mean_line_error_px_original720 ≈ 86.9`：预测线与标注参考线仍有明显偏差，说明当前模型可用于冒烟验证，但不应作为最终稳定田间导航模型。
- 可视化中黄色线是预测导航线，绿色线是从标注 mask 推出的参考线。

## 未完成项

ONNX 一致性检查未完成，因为当前主机 Python 环境缺少 `onnxruntime`。本次证明覆盖的是 PyTorch checkpoint 和主机侧后处理，不等价于 `.m1model` 已经能在板端运行。
