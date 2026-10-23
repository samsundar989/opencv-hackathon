"""COOL vs stock OpenCV benchmark: one arm, whatever `cv2` this interpreter imports.

Run it once per arm on the same machine, from each arm's venv, then compare with bench/compare_arms.py.
It times exactly the live per-frame path (src/riversight/live/bundle.py, vision/register.py), stage by
stage, plus the fleet cycle end to end. Only numpy + cv2 are needed; `src/` is put on sys.path, so the
package does not have to be installed into the arm's venv.

Outputs in <out>/<arm>/:
  provenance.json   cv2 file/version, getBuildInformation sha256 (+ full text), CPU, platform, EC2 identity
  build_info.txt    cv2.getBuildInformation()
  kernels.csv       per (thread regime, stage): n, mean/p50/p95/p99 ms, throughput, CPU utilisation
  fleet.csv         per (thread regime, fleet size): wall s, frames/s, CPU utilisation, registered frames
  outputs.npz       per-site outputs of every stage (single-thread run), for the equivalence check.
                    Holds decoded USGS frames: never commit it (gitignored, non-negotiable 7).

    python bench/cool_bench.py --pack data/bench_pack --out results/cool_bench/<run> --arm pip-5.0.0.93
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import platform
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from riversight.live.bundle import PAD, SiteModel  # noqa: E402
from riversight.vision.register import Registrar  # noqa: E402
from riversight.vision.scene_features import OUT_H, OUT_W, block_features  # noqa: E402

SMALL = (OUT_W, OUT_H)
DNN_STAGES = {"register_aliked_lightglue_magsac", "frame_pipeline"}


# ---- provenance -------------------------------------------------------------------------------------

def _imds(path: str, timeout: float = 0.5) -> str | None:
    """EC2 instance metadata (IMDSv2). None off EC2."""
    try:
        tok = urllib.request.urlopen(urllib.request.Request(
            "http://169.254.169.254/latest/api/token", method="PUT",
            headers={"X-aws-ec2-metadata-token-ttl-seconds": "60"}), timeout=timeout).read().decode()
        return urllib.request.urlopen(urllib.request.Request(
            f"http://169.254.169.254/latest/{path}", headers={"X-aws-ec2-metadata-token": tok}),
            timeout=timeout).read().decode()
    except Exception:
        return None


def _cpu_model() -> str:
    try:
        txt = Path("/proc/cpuinfo").read_text()
        for key in ("model name", "CPU part"):
            for line in txt.splitlines():
                if line.startswith(key):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or platform.machine()


def provenance(arm: str) -> tuple[dict, str]:
    bi = cv2.getBuildInformation()
    ident = _imds("dynamic/instance-identity/document")
    return {
        "arm": arm,
        "cv2_file": cv2.__file__,
        "cv2_version": cv2.__version__,
        "build_info_sha256": hashlib.sha256(bi.encode()).hexdigest(),
        "kleidicv": "KleidiCV" in bi or "kleidicv" in bi,
        "python": sys.version.split()[0],
        "numpy": np.__version__,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu": _cpu_model(),
        "nproc": os.cpu_count(),
        "cv2_default_threads": cv2.getNumThreads(),
        "ec2_identity": json.loads(ident) if ident else None,
        "ami_id": _imds("meta-data/ami-id"),
        "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }, bi


# ---- timing -----------------------------------------------------------------------------------------

def set_threads(n: int) -> None:
    cv2.setNumThreads(n)
    if hasattr(os, "sched_setaffinity"):      # Linux: pin the 1-thread regime to one core
        os.sched_setaffinity(0, {0} if n == 1 else set(range(os.cpu_count())))


def time_stage(fn, inputs: list, warmup: int, iters: int) -> dict:
    """Call fn(inputs[i % len]) warmup + iters times; per-call wall ms and overall CPU utilisation."""
    for i in range(warmup):
        fn(inputs[i % len(inputs)])
    ts = np.empty(iters)
    c0, w0 = time.process_time(), time.perf_counter()
    for i in range(iters):
        t = time.perf_counter()
        fn(inputs[i % len(inputs)])
        ts[i] = time.perf_counter() - t
    wall, cpu = time.perf_counter() - w0, time.process_time() - c0
    ms = ts * 1e3
    return {"n": iters, "mean_ms": ms.mean(), "p50_ms": np.percentile(ms, 50), "p95_ms": np.percentile(ms, 95),
            "p99_ms": np.percentile(ms, 99), "throughput_hz": iters / wall, "cpu_util": cpu / wall}


# ---- the per-frame pipeline, stage by stage ---------------------------------------------------------

class Fleet:
    """Site models and registrars with per-site reference features cached (one ALIKED net for all sites)."""

    def __init__(self, pack: Path):
        self.pack = pack
        self.man = json.loads((pack / "manifest.json").read_text(encoding="utf-8"))
        onnx = pack / "models" / "onnx"
        self.orb = Registrar(use_aliked=False)
        self.ali = Registrar(onnx / "aliked-n16rot-top1k-640.onnx", onnx / "aliked_lightglue.onnx")
        if self.ali.method != "aliked+lightglue":
            raise SystemExit("ALIKED/LightGlue unavailable in this cv2 build or models missing")
        cams = sorted({s["cam_id"] for s in self.man["sites"]} | {f["cam_id"] for f in self.man["fleet"]})
        self.models = {c: SiteModel(pack / "models" / "sites" / c) for c in cams}
        self.refs: dict[str, dict] = {}
        for c, m in self.models.items():
            ref = m.reference()
            self.refs[c] = {}
            for name, reg in (("orb", self.orb), ("ali", self.ali)):
                reg.set_reference(ref)
                self.refs[c][name] = (reg._ref_kp, reg._ref_desc, reg._ref_shape)

    def use_ref(self, reg: Registrar, cam: str, name: str) -> None:
        reg._ref_kp, reg._ref_desc, reg._ref_shape = self.refs[cam][name]

    def bytes_of(self, rel: str) -> bytes:
        return (self.pack / rel).read_bytes()

    def frame_pipeline(self, cam: str, buf: bytes) -> tuple[float, bool]:
        """Live path for one frame: decode → ORB → (ALIKED+LightGlue if ORB fails) → warp → features → stage."""
        m = self.models[cam]
        img = cv2.imdecode(np.frombuffer(buf, np.uint8), cv2.IMREAD_COLOR)
        self.use_ref(self.orb, cam, "orb")
        r = self.orb.register(img)
        if not r.ok:
            self.use_ref(self.ali, cam, "ali")
            r = self.ali.register(img)
        if not r.ok:
            return float("nan"), False
        small = warp_small(img, r.H, tuple(m.meta["ref_shape"]))
        F = block_features(small).astype(np.float16).astype(np.float32)
        stage = float(m.predict_raw(F)[0])
        m.wet_mask(stage)
        return stage, True


def warp_padded(img: np.ndarray, H: np.ndarray, ref_shape) -> np.ndarray:
    """The warp of live/bundle.warp_small_safe (pad + BORDER_CONSTANT), at reference resolution."""
    h, w = ref_shape
    src = cv2.copyMakeBorder(img, PAD, PAD, PAD, PAD, cv2.BORDER_REPLICATE)
    shift = np.array([[1, 0, -PAD], [0, 1, -PAD], [0, 0, 1]], float)
    return cv2.warpPerspective(src, H @ shift, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)


def warp_small(img: np.ndarray, H: np.ndarray, ref_shape) -> np.ndarray:
    return cv2.resize(warp_padded(img, H, ref_shape), SMALL, interpolation=cv2.INTER_AREA)


def sobel_mag(small: np.ndarray) -> np.ndarray:
    L = cv2.cvtColor(small, cv2.COLOR_BGR2LAB)[..., 0].astype(np.float32)
    return cv2.magnitude(cv2.Sobel(L, cv2.CV_32F, 1, 0), cv2.Sobel(L, cv2.CV_32F, 0, 1))


def build_inputs(fl: Fleet) -> list[dict]:
    out = []
    for s in fl.man["sites"]:
        buf = fl.bytes_of(s["frame"])
        img = cv2.imdecode(np.frombuffer(buf, np.uint8), cv2.IMREAD_COLOR)
        H = np.asarray(s["H"], float).reshape(3, 3)
        rs = tuple(s["ref_shape"])
        warped = warp_padded(img, H, rs)
        small = cv2.resize(warped, SMALL, interpolation=cv2.INTER_AREA)
        L = cv2.cvtColor(small, cv2.COLOR_BGR2LAB)[..., 0].astype(np.float32)
        F = block_features(small).astype(np.float16).astype(np.float32)
        out.append({"cam": s["cam_id"], "buf": buf, "img": img, "H": H, "rs": rs, "warped": warped,
                    "small": small, "L": L, "F": F})
    return out


def stages(fl: Fleet) -> dict:
    """name → fn(input dict). Each stage takes the previous stage's cached output as input."""
    def orb(x):
        fl.use_ref(fl.orb, x["cam"], "orb")
        return fl.orb.register(x["img"])

    def ali(x):
        fl.use_ref(fl.ali, x["cam"], "ali")
        return fl.ali.register(x["img"])

    return {
        "imdecode": lambda x: cv2.imdecode(np.frombuffer(x["buf"], np.uint8), cv2.IMREAD_COLOR),
        "register_orb_magsac": orb,
        "register_aliked_lightglue_magsac": ali,
        "warpPerspective": lambda x: warp_padded(x["img"], x["H"], x["rs"]),
        "resize_area": lambda x: cv2.resize(x["warped"], SMALL, interpolation=cv2.INTER_AREA),
        "cvtColor_lab": lambda x: cv2.cvtColor(x["small"], cv2.COLOR_BGR2LAB),
        "sobel_magnitude": lambda x: cv2.magnitude(cv2.Sobel(x["L"], cv2.CV_32F, 1, 0),
                                                   cv2.Sobel(x["L"], cv2.CV_32F, 0, 1)),
        "block_features": lambda x: block_features(x["small"]),
        "ridge_predict": lambda x: fl.models[x["cam"]].predict_raw(x["F"]),
        "frame_pipeline": lambda x: fl.frame_pipeline(x["cam"], x["buf"]),
    }


def stage_outputs(fl: Fleet, inputs: list[dict]) -> dict:
    """Deterministic per-site outputs of every pixel stage, for the cross-arm equivalence check."""
    out = {}
    for x in inputs:
        c = x["cam"]
        img = cv2.imdecode(np.frombuffer(x["buf"], np.uint8), cv2.IMREAD_COLOR)
        warped = warp_padded(img, x["H"], x["rs"])
        small = cv2.resize(warped, SMALL, interpolation=cv2.INTER_AREA)
        F = block_features(small)
        out[f"{c}|imdecode"] = img
        out[f"{c}|warpPerspective"] = warped
        out[f"{c}|resize_area"] = small
        out[f"{c}|cvtColor_lab"] = cv2.cvtColor(small, cv2.COLOR_BGR2LAB)
        out[f"{c}|sobel_magnitude"] = sobel_mag(small)
        out[f"{c}|block_features"] = F
        out[f"{c}|stage_fixedH"] = np.array([fl.models[c].predict_raw(F.astype(np.float16).astype(np.float32))[0]])
        s, ok = fl.frame_pipeline(c, x["buf"])
        out[f"{c}|stage_pipeline"] = np.array([s if ok else np.nan])
    return out


def fleet_run(fl: Fleet, frames: list[tuple[str, bytes]]) -> dict:
    c0, w0 = time.process_time(), time.perf_counter()
    n_ok = sum(fl.frame_pipeline(c, b)[1] for c, b in frames)
    wall, cpu = time.perf_counter() - w0, time.process_time() - c0
    return {"n_frames": len(frames), "wall_s": wall, "frames_per_s": len(frames) / wall,
            "cpu_util": cpu / wall, "n_registered": n_ok}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", type=Path, default=ROOT / "data" / "bench_pack")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--arm", required=True, help="label, e.g. cool-g5-py3.14 or pip-5.0.0.93")
    ap.add_argument("--warmup", type=int, default=50)
    ap.add_argument("--iters", type=int, default=300)
    ap.add_argument("--dnn-warmup", type=int, default=10)
    ap.add_argument("--dnn-iters", type=int, default=100,
                    help="iterations for the stages that run ALIKED+LightGlue (about 1-3 s each on CPU)")
    ap.add_argument("--threads", default="1,all", help="comma list of thread counts; 'all' = nproc")
    ap.add_argument("--fleet", default="20,880", help="fleet sizes; 20 = one frame per calibrated site")
    ap.add_argument("--fleet-repeats", type=int, default=5, help="repeats of the 20-site cycle")
    ap.add_argument("--only", nargs="*", help="subset of stage names")
    args = ap.parse_args()

    out = args.out / args.arm
    out.mkdir(parents=True, exist_ok=True)
    prov, bi = provenance(args.arm)
    (out / "build_info.txt").write_text(bi, encoding="utf-8")
    print(json.dumps({k: v for k, v in prov.items() if k != "ec2_identity"}, indent=1), flush=True)

    fl = Fleet(args.pack)
    inputs = build_inputs(fl)
    set_threads(1)
    np.savez_compressed(out / "outputs.npz", **stage_outputs(fl, inputs))

    progress = os.environ.get("WORKERQ_PROGRESS")
    regimes = [os.cpu_count() if t == "all" else int(t) for t in args.threads.split(",")]
    fns = stages(fl)
    names = [n for n in fns if not args.only or n in args.only]
    krows, frows = [], []
    sites20 = [(x["cam"], x["buf"]) for x in inputs]
    fleet_frames = [(f["cam_id"], fl.bytes_of(f["frame"])) for f in fl.man["fleet"]]
    total = len(regimes) * (len(names) + 1)
    done = 0
    for nt in regimes:
        set_threads(nt)
        for name in names:
            dnn = name in DNN_STAGES
            r = time_stage(fns[name], inputs, args.dnn_warmup if dnn else args.warmup,
                           args.dnn_iters if dnn else args.iters)
            krows.append({"arm": args.arm, "threads": nt, "stage": name, **{k: round(v, 4) for k, v in r.items()}})
            print(f"[{nt} thr] {name:34s} p50 {r['p50_ms']:9.3f} ms  p95 {r['p95_ms']:9.3f}  cpu {r['cpu_util']:.2f}",
                  flush=True)
            done += 1
            if progress:
                Path(progress).write_text(str(done / total))
        for size in (int(s) for s in args.fleet.split(",")):
            frames = sites20 if size == len(sites20) else fleet_frames[:size]
            reps = args.fleet_repeats if size == len(sites20) else 1
            fl.frame_pipeline(*frames[0])   # warm
            for rep in range(reps):
                r = fleet_run(fl, frames)
                frows.append({"arm": args.arm, "threads": nt, "fleet": size, "repeat": rep,
                              **{k: round(v, 4) if isinstance(v, float) else v for k, v in r.items()}})
                print(f"[{nt} thr] fleet {size:4d} rep {rep}: {r['wall_s']:.2f} s, {r['frames_per_s']:.2f} fr/s, "
                      f"registered {r['n_registered']}", flush=True)
        done += 1
        if progress:
            Path(progress).write_text(str(done / total))

    for fname, rows in (("kernels.csv", krows), ("fleet.csv", frows)):
        with open(out / fname, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    prov["finished_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    prov["args"] = {k: str(v) for k, v in vars(args).items()}
    (out / "provenance.json").write_text(json.dumps(prov, indent=1), encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
