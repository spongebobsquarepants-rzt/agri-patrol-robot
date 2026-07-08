# Field Navigation Training Workspace

This workspace is for the A1 field navigation project. It only reads the
original LabelMe dataset and writes derived files under this directory.

## Dataset Contract

- Source annotations: LabelMe JSON polygons.
- Accepted labels: `sand_road`, `grassy_road`.
- Training target: both labels are merged into one foreground class named
  `road`.
- Model input: grayscale `1x480x640`.
- Recommended model output: one road probability map. The board app accepts any
  2-D output size and maps it back to the camera crop.

## Typical Flow

From `D:\1.1.1.1.1`:

```powershell
$DATASET_ROOT = "D:\1.1.1.1.1\智慧农业田垄采摘机器人道路识别农作物过道区域识别分割数据集labelme格式211张2类别"

python .\field_nav_workspace\tools\prepare_labelme_dataset.py `
  --dataset-root $DATASET_ROOT `
  --out-dir ".\field_nav_workspace\data\processed_640x480"

python .\field_nav_workspace\tools\train_navroad.py `
  --data-dir ".\field_nav_workspace\data\processed_640x480" `
  --run-dir ".\field_nav_workspace\runs\navroad_tiny"
```

## V2 Quality Flow

The v2 flow keeps the original dataset read-only and creates review copies,
derived images, masks, checkpoints, and reports under `field_nav_workspace`.

Set the dataset root once in PowerShell:

```powershell
$DATASET_ROOT = "D:\1.1.1.1.1\智慧农业田垄采摘机器人道路识别农作物过道区域识别分割数据集labelme格式211张2类别"
```

1. Audit the LabelMe files and copy suspicious samples for manual review:

```powershell
python .\field_nav_workspace\tools\audit_labelme_dataset_v2.py `
  --dataset-root $DATASET_ROOT `
  --audit-dir ".\field_nav_workspace\data\audit_v2" `
  --curated-dir ".\field_nav_workspace\data\labelme_curated_v2"
```

Review:

```text
field_nav_workspace\data\audit_v2\audit.csv
field_nav_workspace\data\audit_v2\overlays
field_nav_workspace\data\labelme_curated_v2
```

Only edit the copied JSON/JPG files in `labelme_curated_v2` if labels need
manual correction. The original dataset should remain untouched.

2. Build board-like 640x480 grayscale training data with stratified splits:

```powershell
python .\field_nav_workspace\tools\prepare_labelme_dataset_v2.py `
  --dataset-root $DATASET_ROOT `
  --curated-dir ".\field_nav_workspace\data\labelme_curated_v2" `
  --out-dir ".\field_nav_workspace\data\processed_v2_640x480"
```

3. Train the v2 skip-fusion model:

```powershell
python .\field_nav_workspace\tools\train_navroad_v2.py `
  --data-dir ".\field_nav_workspace\data\processed_v2_640x480" `
  --run-dir ".\field_nav_workspace\runs\navroad_v2" `
  --epochs 120 `
  --patience 15
```

4. Evaluate on val/test and generate failure previews:

```powershell
python .\field_nav_workspace\tools\evaluate_navroad_v2.py `
  --data-dir ".\field_nav_workspace\data\processed_v2_640x480" `
  --checkpoint ".\field_nav_workspace\runs\navroad_v2\best.pt" `
  --split test `
  --failure-dir ".\field_nav_workspace\runs\navroad_v2\failures"
```

5. If `onnxruntime` is installed, compare PyTorch and ONNX logits:

```powershell
python .\field_nav_workspace\tools\compare_onnx_navroad_v2.py `
  --data-dir ".\field_nav_workspace\data\processed_v2_640x480" `
  --checkpoint ".\field_nav_workspace\runs\navroad_v2\best.pt" `
  --onnx ".\field_nav_workspace\runs\navroad_v2\navroad_640x480.onnx"
```

After training, convert the exported ONNX with your ONNX-to-`.m1model` tool and
place the result here before building the SDK:

```text
D:\1.1.1.1.1\data\A1_SDK_SC132GS\smartsens_sdk\field_nav_external\src\field_nav_demo\app_assets\models\navroad_640x480.m1model
```
