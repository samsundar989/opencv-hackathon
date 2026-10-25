"""Silent rough cut of the submission video (D-0014 W3-1), following docs/VIDEO_SCRIPT_DRAFT.md v3 shot by shot.

Built entirely with OpenCV: B-roll clips from results/video_assets/ (capture_broll.py) are streamed through
`VideoCapture` and retimed to each shot's slot (frames resampled monotonically, so memory stays at a few
frames); title cards, Samuel's intro/outro slots and the end card are drawn with `cv2.FontFace`; stills
(architecture diagram, failure gallery) are letterboxed. Output: one 1920×1080, 25 fps MP4 plus an edit
decision list with every shot's in/out times so the narration and on-camera clips can be dropped in.

    python report/video/rough_cut.py   → results/video_assets/rough_cut.mp4 (+ rough_cut_edl.json, committed)
"""
from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
VA = ROOT / "results" / "video_assets"
W, H, FPS = 1920, 1080, 25
BG, INK, INK2, ACCENT = (251, 252, 252), (11, 11, 11), (78, 81, 82), (214, 120, 42)
URL = "https://d2aes2r6og8aap.cloudfront.net"
REPO = "github.com/samsundar989/opencv-hackathon"


def card(lines: list[tuple[str, int, tuple]], bg=BG) -> np.ndarray:
    img = np.full((H, W, 3), bg, np.uint8)
    face = cv2.FontFace("sans")
    total = sum(int(sz * 1.6) for _, sz, _ in lines)
    y = (H - total) // 2
    for text, sz, color in lines:
        y += int(sz * 1.3)
        cv2.putText(img, text, (160, y), color, face, sz)
        y += int(sz * 0.3)
    return img


def letterbox(img: np.ndarray) -> np.ndarray:
    s = min(W / img.shape[1], H / img.shape[0])
    r = cv2.resize(img, (int(img.shape[1] * s), int(img.shape[0] * s)), interpolation=cv2.INTER_AREA)
    out = np.full((H, W, 3), BG, np.uint8)
    y0, x0 = (H - r.shape[0]) // 2, (W - r.shape[1]) // 2
    out[y0:y0 + r.shape[0], x0:x0 + r.shape[1]] = r
    return out


class Cut:
    def __init__(self, path: Path):
        self.vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (W, H))
        self.n = 0
        self.edl: list[dict] = []

    def _w(self, f: np.ndarray) -> None:
        if f.shape[:2] != (H, W):
            f = cv2.resize(f, (W, H), interpolation=cv2.INTER_AREA)
        self.vw.write(f)
        self.n += 1

    def still(self, img: np.ndarray, seconds: float, shot: str, what: str) -> None:
        t0 = self.n / FPS
        for _ in range(int(round(seconds * FPS))):
            self._w(img)
        self.edl.append({"shot": shot, "in_s": round(t0, 2), "out_s": round(self.n / FPS, 2), "what": what})

    def clip(self, name: str, seconds: float, shot: str, what: str, start_s: float = 0.0, end_s: float | None = None) -> None:
        """Play [start_s, end_s) of a B-roll clip, resampled to fill `seconds` exactly (slow-down or speed-up)."""
        cap = cv2.VideoCapture(str(VA / f"{name}.mp4"))
        if not cap.isOpened():
            self.still(card([(f"[missing B-roll: {name}]", 48, INK2)]), seconds, shot, f"MISSING {name}")
            return
        fps = cap.get(cv2.CAP_PROP_FPS) or FPS
        n_src = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        a = int(start_s * fps)
        b = min(int(end_s * fps), n_src) if end_s else n_src
        n_out = int(round(seconds * FPS))
        want = np.linspace(a, b - 1, n_out).round().astype(int)    # monotonic source index per output frame
        cap.set(cv2.CAP_PROP_POS_FRAMES, a)
        cur_i, cur = a - 1, None
        t0 = self.n / FPS
        for j in want:
            while cur_i < j:
                ok, f = cap.read()
                if not ok:
                    break
                cur_i, cur = cur_i + 1, f
            self._w(cur if cur is not None else card([("", 10, INK)]))
        cap.release()
        self.edl.append({"shot": shot, "in_s": round(t0, 2), "out_s": round(self.n / FPS, 2), "what": what,
                         "source": f"{name}.mp4", "source_range_s": [round(a / fps, 1), round(b / fps, 1)]})

    def close(self) -> None:
        self.vw.release()


def failure_montage() -> list[np.ndarray]:
    names = ["night_ir_hancock.jpg", "fog_lens_bigbrook.jpg", "view_change_pecatonica.jpg", "above_range_hancock.png"]
    caps = ["Night / IR: not scored", "Fog, rain, wet lens", "Cameras get re-aimed", "Floods beyond its history saturate it"]
    out = []
    for n, c in zip(names, caps):
        img = cv2.imread(str(ROOT / "results" / "failures" / n))
        if img is None:
            continue
        f = letterbox(img)
        cv2.rectangle(f, (0, H - 110), (W, H), (30, 30, 30), -1)
        cv2.putText(f, c, (80, H - 40), (255, 255, 255), cv2.FontFace("sans"), 52)
        out.append(f)
    return out


def main() -> None:
    cut = Cut(VA / "rough_cut.mp4")
    slot = (40, 40, 40)
    # 1 (0:00–0:15)
    cut.still(card([("INTRO SLOT: Samuel on camera", 64, (255, 255, 255)), ("replace this card with the on-camera take (about 5 s)", 34, (200, 200, 200))], bg=slot),
              5, "1a", "Samuel on camera (drop in)")
    cut.clip("home", 10, "1b", "Live home page: fleet map, 'Needs a person now', camera cards", 1.0, 16.0)
    # 2 (0:15–0:45)
    cut.clip("salt_creek_slider", 30, "2", "Salt Creek site page: stage slider sweep, connected wet overlay", 2.5)
    # 3 (0:45–1:20)
    cut.clip("replay_salt_creek", 35, "3", "Replay a flood, Salt Creek 3 Jul 2026 (out of sample): overlay rising, chart cursor, agent log, 'above range: gauge trusted'", 1.5)
    # 4 (1:20–1:45)
    cut.still(card([("OpenCV 5 registration", 72, INK), ("ALIKED + LightGlue + USAC_MAGSAC", 48, ACCENT),
                    ("95.7 % of daylight frames registered  vs  39.6 % for ORB alone", 40, INK2)]), 5, "4a", "Registration card")
    cut.clip("judge", 20, "4b", "/judge: frozen-test tiles (14/20, 0.18 ft, gap-fill 15/20 and 18/20)", 2.0, 16.0)
    # 5 (1:45–2:10)
    cut.clip("judge", 25, "5", "/judge: v2 and prospective tiles, gauge-wins-while-online", 16.0, 33.0)
    # 6 (2:10–2:40)
    cut.clip("approvals", 15, "6a", "/approvals: approval cards with Claude's second opinion", 1.0)
    cut.clip("health", 15, "6b", "/health: offline, moved, stuck in IR; ticket drafts need approval", 1.0)
    # 7 (2:40–3:00)
    arch = cv2.imread(str(ROOT / "docs" / "img" / "architecture.png"))
    cut.still(letterbox(arch) if arch is not None else card([("architecture", 60, INK)]), 8, "7a", "Architecture diagram")
    cut.clip("proof", 12, "7b", "/proof: COOL build provenance, Graviton5 instance identity", 1.0)
    # 8 (3:00–3:10)
    mont = failure_montage()
    for k, f in enumerate(mont):
        cut.still(f, 10 / max(len(mont), 1), f"8{chr(97 + k)}", "Failure gallery")
    # 9 (3:10–3:25)
    cut.still(card([("OUTRO SLOT: Samuel on camera", 64, (255, 255, 255)), ("replace this card with the on-camera take (about 10 s)", 34, (200, 200, 200))], bg=slot),
              10, "9a", "Samuel on camera (drop in)")
    cut.still(card([("RiverSight", 96, INK), ("public river webcams as water-level instruments", 44, INK2), ("", 30, INK),
                    (URL, 40, ACCENT), (REPO, 40, ACCENT), ("OpenCV AI Competition 2026 · powered by AWS", 32, INK2)]), 5, "9b", "End card")
    cut.close()
    edl = {"output": "results/video_assets/rough_cut.mp4", "fps": FPS, "size": f"{W}x{H}",
           "duration_s": round(cut.n / FPS, 2), "script": "docs/VIDEO_SCRIPT_DRAFT.md v3", "shots": cut.edl}
    (VA / "rough_cut_edl.json").write_text(json.dumps(edl, indent=1) + "\n", encoding="utf-8")
    print(f"rough cut {edl['duration_s']} s -> {VA / 'rough_cut.mp4'}")


if __name__ == "__main__":
    main()
