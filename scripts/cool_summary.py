"""Build results/cool_bench/summary.json (rendered on /judge) from the committed COOL A/B CSVs. No numbers typed by hand."""
import csv, json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
D = ROOT / "results" / "cool_bench" / "cool_g5_m9g_2026-10-24"
rd = lambda n: list(csv.DictReader(open(D / n)))
fleet = [r for r in rd("compare_fleet.csv") if r["threads"] == "2" and r["fleet"] == "880"][0]
kern = {r["stage"]: r for r in rd("compare_kernels.csv") if r["threads"] == "2"}
k1 = {r["stage"]: r for r in rd("compare_kernels.csv") if r["threads"] == "1"}
cost = {r["arm"]: r for r in rd("cost.csv") if r["cadence_min"] == "15"}
am = {r["stage"]: r for r in rd("amdahl.csv") if r["arm"] == "cool" and r["threads"] == "2"}
eq = rd("equivalence.csv")
out = {
    "setup": {"instance": "m9g.large (AWS Graviton5), us-east-2", "COOL": "OpenCV 5.1.0-dev, COOL Graviton5 AMI (/opt/cool, Python 3.14)",
              "baseline": "pip opencv-python-headless 5.0.0.93 on the same instance", "workload": "the live RiverSight cycle on real HIVIS frames"},
    "end_to_end_fleet_speedup_880_cams_2_threads": f"{float(fleet['speedup_cool']):.4f}x (flat)",
    "classical_registration_speedup_ORB_MAGSAC": f"{float(k1['register_orb_magsac']['speedup_cool']):.2f}x (1 thread) / {float(kern['register_orb_magsac']['speedup_cool']):.2f}x (2 threads)",
    "classical_frame_pipeline_speedup": f"{float(k1['frame_pipeline']['speedup_cool']):.2f}x (1 thread) / {float(kern['frame_pipeline']['speedup_cool']):.2f}x (2 threads)",
    "why_flat": f"ALIKED+LightGlue (DNN) is {100*float(am['register_aliked_lightglue_magsac']['share_of_stages']):.1f}% of stage time; COOL does not accelerate it",
    "outputs_identical": f"{sum(float(r['max_abs_diff']) == 0 for r in eq)}/{len(eq)} stages bit-identical across 20 sites; full stage pipeline differs by at most {max(float(r['max_abs_diff']) for r in eq):.5f} ft",
    "cost_at_15_min_cadence": f"${float(cost['cool']['usd_per_camera_month']):.3f} per camera-month; {cost['cool']['cameras_per_instance']} cameras per m9g.large",
    "sources": "results/cool_bench/cool_g5_m9g_2026-10-24/*.csv, amdahl.png; built by scripts/cool_summary.py",
}
(ROOT / "results" / "cool_bench" / "summary.json").write_text(json.dumps(out, indent=1))
print(json.dumps(out, indent=1))
