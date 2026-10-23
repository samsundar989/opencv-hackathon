"""Write the result tables of docs/COOL_BENCHMARK.md from results/cool_bench/<run>/ (no hand-copied numbers).

A run's tables go between `<!-- BEGIN:cool:<run> -->` and `<!-- END:cool:<run> -->`. One-arm runs get the
latency and fleet tables; runs that compare_arms.py has processed also get speedups, equivalence, cost and
scaling.

    python bench/build_cool_doc.py devbox_x86_2026-10-23 [aws_2026-10-24 ...]
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "results" / "cool_bench"
DOC = ROOT / "docs" / "COOL_BENCHMARK.md"


def _t(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    out += ["| " + " | ".join(str(v) for v in r) + " |" for r in df.itertuples(index=False)]
    return "\n".join(out)


def _ms(x: float) -> str:
    return f"{x:.3f}" if x < 10 else f"{x:.1f}"


def provenance_line(run: Path, arm: str) -> str:
    p = json.loads((run / arm / "provenance.json").read_text(encoding="utf-8"))
    ec2 = p.get("ec2_identity") or {}
    where = f"{ec2.get('instanceType')} {ec2.get('region')}, AMI `{p.get('ami_id')}`" if ec2 else f"{p['machine']}, not EC2"
    return (f"- **{arm}:** OpenCV {p['cv2_version']} from `{p['cv2_file']}`, build-info sha256 `{p['build_info_sha256'][:12]}…`, "
            f"KleidiCV {'yes' if p['kleidicv'] else 'no'}, Python {p['python']}, {p['cpu']}, {p['nproc']} cores; {where}.")


def run_block(run: Path) -> str:
    arms = sorted(p.name for p in run.iterdir() if (p / "kernels.csv").exists())
    parts = ["**Provenance**", ""] + [provenance_line(run, a) for a in arms] + [""]
    K = pd.concat([pd.read_csv(run / a / "kernels.csv").assign(arm=a) for a in arms])
    F = pd.concat([pd.read_csv(run / a / "fleet.csv").assign(arm=a) for a in arms])
    for a in arms:
        k = K[K.arm == a]
        lat = k.assign(**{"p50 ms": k.p50_ms.map(_ms), "p95 ms": k.p95_ms.map(_ms), "p99 ms": k.p99_ms.map(_ms),
                          "CPU util": k.cpu_util.map(lambda v: f"{v:.2f}")})[
            ["threads", "stage", "n", "p50 ms", "p95 ms", "p99 ms", "CPU util"]]
        parts += [f"**Per-stage latency, {a}**", "", _t(lat), ""]
    fl = (F.groupby(["arm", "threads", "fleet"])
            .agg(repeats=("repeat", "count"), wall_s=("wall_s", "mean"), frames_per_s=("frames_per_s", "mean"),
                 registered=("n_registered", "min"), cpu_util=("cpu_util", "mean")).reset_index())
    fl["wall_s"] = fl.wall_s.map(lambda v: f"{v:.1f}")
    fl["frames_per_s"] = fl.frames_per_s.map(lambda v: f"{v:.2f}")
    fl["cpu_util"] = fl.cpu_util.map(lambda v: f"{v:.2f}")
    parts += ["**Fleet cycles** (mean over repeats; `registered` = frames the cascade registered)", "", _t(fl), ""]

    if (run / "compare_kernels.csv").exists():
        ck = pd.read_csv(run / "compare_kernels.csv")
        sp = [c for c in ck.columns if c.startswith("speedup_")]
        show = ck[["threads", "stage"] + arms + sp].copy()
        for c in arms:
            show[c] = show[c].map(_ms)
        for c in sp:
            show[c] = show[c].map(lambda v: f"{v:.2f}×")
        parts += ["**Per-stage p50 (ms) and speedup vs the baseline** (> 1 = faster)", "", _t(show), ""]
        cf = pd.read_csv(run / "compare_fleet.csv")
        for c in cf.columns:
            if c.startswith("speedup_"):
                cf[c] = cf[c].map(lambda v: f"{v:.2f}×")
            elif c not in ("threads", "fleet"):
                cf[c] = cf[c].map(lambda v: f"{v:.2f}")
        parts += ["**Fleet frames/s and speedup**", "", _t(cf), ""]
        am = pd.read_csv(run / "amdahl.csv")
        am["share"] = am.share_of_stages.map(lambda v: f"{100 * v:.1f} %")
        parts += ["**Amdahl: share of the summed stage time** (if every stage ran on every frame; ALIKED runs only when ORB fails)",
                  "", _t(am[["arm", "threads", "stage", "share"]]), ""]
    if (run / "equivalence.csv").exists():
        eq = pd.read_csv(run / "equivalence.csv")
        parts += ["**Output equivalence vs the baseline** (worst over the 20 frames)", "", _t(eq), ""]
    for name, title in (("cost.csv", "Cost"), ("scaling.csv", "Fleet scaling at a 30-minute cadence")):
        if (run / name).exists():
            parts += [f"**{title}**", "", _t(pd.read_csv(run / name)), ""]
    return "\n".join(parts).rstrip()


def main() -> None:
    txt = DOC.read_text(encoding="utf-8")
    for name in sys.argv[1:]:
        pat = re.compile(rf"(<!-- BEGIN:cool:{re.escape(name)} -->\n)(?:.*?\n)?(<!-- END:cool:{re.escape(name)} -->)", re.S)
        if not pat.search(txt):
            raise SystemExit(f"no marker for {name} in {DOC}")
        block = run_block(RUNS / name)
        txt = pat.sub(lambda m: m.group(1) + block + "\n" + m.group(2), txt)
    DOC.write_text(txt, encoding="utf-8")
    print(f"updated {DOC}")


if __name__ == "__main__":
    main()
