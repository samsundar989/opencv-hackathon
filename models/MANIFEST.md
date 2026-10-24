# Model manifest (downloaded at build time; *.onnx is gitignored)

| file | source | sha256 | license |
|---|---|---|---|
| onnx/aliked-n16rot-top1k-640.onnx | https://raw.githubusercontent.com/YangGuanyuhan/lightglue_opencv_project/HEAD/model/aliked-n16rot-top1k-640.onnx | `b46868de0794ea0f2d878985d99dc17d3639dfab85d852994254a4cdf0cdc0ea` | BSD-3 (ALIKED) |
| onnx/aliked_lightglue.onnx | https://raw.githubusercontent.com/YangGuanyuhan/lightglue_opencv_project/HEAD/model/aliked_lightglue.onnx | `a1bd99d294c4c6c08ca978af3128c85f8c0e603b04a03e4391428455d9624439` | Apache-2.0 (LightGlue) |
| onnx/dinov2_small_224x392.onnx | exported by `scripts/v2_export_dino.py` from https://huggingface.co/facebook/dinov2-small (fixed 224×392 input, position embeddings baked to 16×28, opset 17) | `84c75599e4c99a3a81831e122a5670ebe8179a35aeee7d10b09bcf0fa88bdec7` | Apache-2.0 (DINOv2, Meta) |
