"""W4 step 1: export DINOv2-S/14 to a fixed-shape ONNX graph that OpenCV 5's DNN engine can run.

Run with the export-only venv (torch is not a runtime dependency; the product path is cv2.dnn):
    .venv/Scripts/python.exe scripts/v2_export_dino.py

Source weights: facebook/dinov2-small on Hugging Face (Apache-2.0, Oquab et al. 2023).
Input  : (1, 3, 224, 392) float32, ImageNet-normalised RGB (normalisation is done by
         cv2.dnn.blobFromImageWithParams at run time, not inside the graph).
Output : (1, 449, 384) = CLS token + 16×28 patch tokens after the final LayerNorm.

The model's position embeddings are bicubically resized to the 16×28 grid **once, here**, and baked
into the graph as a constant, so the graph has no Resize/bicubic op and a fully static shape.
Writes models/onnx/dinov2_small_224x392.onnx and prints its sha256 (record it in models/MANIFEST.md).
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import torch
from transformers import Dinov2Model

ROOT = Path(__file__).resolve().parents[1]
H, W = 224, 392
OUT = ROOT / "models" / "onnx" / "dinov2_small_224x392.onnx"
HF_ID = "facebook/dinov2-small"


class FixedDino(torch.nn.Module):
    def __init__(self, m: Dinov2Model):
        super().__init__()
        self.patch = m.embeddings.patch_embeddings.projection        # Conv2d 3→384, k=14, s=14
        self.cls = torch.nn.Parameter(m.embeddings.cls_token.detach().clone())
        with torch.no_grad():
            pos = m.embeddings.interpolate_pos_encoding(torch.zeros(1, 1 + (H // 14) * (W // 14), 384), H, W)
        self.pos = torch.nn.Parameter(pos.detach().clone())
        self.encoder = m.encoder
        self.norm = m.layernorm

    def forward(self, x):
        t = self.patch(x).flatten(2).transpose(1, 2)                 # (1, 448, 384)
        t = torch.cat([self.cls.expand(x.shape[0], -1, -1), t], 1) + self.pos
        t = self.encoder(t)[0]
        return self.norm(t)


def main():
    m = Dinov2Model.from_pretrained(HF_ID, attn_implementation="eager").eval()
    f = FixedDino(m).eval()
    x = torch.randn(1, 3, H, W)
    with torch.no_grad():
        ref = m(pixel_values=x).last_hidden_state
        got = f(x)
    d = float((ref - got).abs().max())
    print(f"wrapper vs HF model max abs diff: {d:.2e}")
    if d > 1e-4:
        sys.exit("wrapper does not reproduce the HF model")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    torch.onnx.export(f, x, str(OUT), input_names=["pixel_values"], output_names=["tokens"],
                      opset_version=17, do_constant_folding=True, dynamo=False)
    print(OUT, OUT.stat().st_size, "bytes")
    print("sha256", hashlib.sha256(OUT.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
