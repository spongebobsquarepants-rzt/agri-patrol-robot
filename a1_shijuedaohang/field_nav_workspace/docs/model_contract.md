# NavRoad Model Contract

## Input

- Name: `image`
- Shape: `1x1x480x640`
- Type: uint8 or float, depending on the ONNX-to-`.m1model` conversion settings.
- Semantics: grayscale road image matching the board preprocessing path.

## Output

- Name: `road_logits`
- Shape: `1x1x120x160` for the provided tiny model.
- Semantics: road foreground logits or probabilities.

The board app does not require a fixed output width/height. It reads the output
tensor size at runtime, thresholds the road map, extracts row centers, and maps
the result back to the original `720x1280` OSD coordinate system.

