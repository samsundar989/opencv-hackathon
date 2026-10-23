# Interfaces — the contract between the three sprint workers (Cowork, 2026-10-22)

These schemas let W1 (cloud), W2 (agent) and W3 (eval/docs/COOL) build in parallel. Changing one needs a `D-` entry and a note in all three status files.

## 1. Per-site model bundle — produced by W1 `scripts/export_site_models.py`

Location: `models/sites/<cam_id>/`. Gitignored locally; uploaded to `s3://<bucket>/models/sites/<cam_id>/`.

| file | content |
|---|---|
| `reference.jpg` | Registration reference frame (720 px). If a view change was re-anchored, more references sit next to it as `reference_<yyyymmdd>.jpg`. |
| `scene_model.npz` | Arrays for the D-0007 setting: flood-height map (`thr`, `acc`, `w`, `mid`), ROI mask, kernel-ridge training features + alpha (or a low-rank equivalent), feature mean/std, Kalman q and r. |
| `meta.json` | `{cam_id, nwis_id, lat, lon, tier, sigma_ft, calib_start, calib_end, n_calib_frames, stage_p05, stage_p50, stage_p90, stage_p95, frozen_config_sha, model_sha, trained_at}` |

Live models are refit on **all** data up to export time, test days included. That's fine for live serving. The kill-test numbers stay the frozen-protocol ones.

## 2. Reading — one per site per cycle, produced by W1 `riversight.live.cycle.run_site()`

```json
{
  "cam_id": "...", "t_frame": "2026-10-23T15:00:03Z", "t_cycle": "...",
  "daylight": true,
  "frame_key": "live/frames/<cam>/<ts>.jpg",
  "overlay_key": "live/overlays/<cam>/<ts>.jpg",
  "registration": {"ok": true, "inliers": 412, "inlier_ratio": 0.61, "reproj_px": 1.3, "ref": "reference.jpg", "method": "aliked_lightglue"},
  "quality": {"lap_var": 812.0, "mean_v": 121.0, "glare_frac": 0.01, "fog_score": 0.12},
  "camera_stage_ft": 5.42, "camera_sigma_ft": 0.31,
  "gauge_stage_ft": 5.38, "gauge_time": "2026-10-23T14:45:00Z", "gauge_age_min": 15,
  "flood_state": "normal|elevated|flood",
  "flags": ["VIEW_CHANGE","LOW_QUALITY","GAUGE_STALE","DISAGREE","RISING","NIGHT"],
  "model_sha": "...", "code_sha": "...", "opencv": {"version": "5.0.0", "file": "/opt/cool/...", "cool": true}
}
```

Each cycle writes three things to S3:
- `live/sites/<cam>/latest.json`
- one line appended to `live/sites/<cam>/YYYY-MM-DD.jsonl`
- `live/index.json`: every site's latest reading, plus `{cycle_started, cycle_ms, n_ok, n_flagged}`

Overlays are face-blurred (YuNet) before upload.

## 3. Agent event and decision (W1 calls W2)

W1 calls `riversight.agent.handle(event) -> Decision` once per flagged reading. It is never called for unflagged readings, so the LLM costs nothing on quiet days. If import or Bedrock fails, W1 falls back to `riversight.agent.rules.handle()`, a deterministic policy.

```json
// event
{"event_id": "...", "cam_id": "...", "reading": {...Reading...}, "recent": [ ...last 24 readings... ], "site_meta": {...meta.json...}, "mode": "live|replay|eval"}
// decision
{"event_id": "...", "decided_by": "llm|rules", "model": "anthropic.claude-haiku-5-5...", "tokens_in": 0, "tokens_out": 0, "usd": 0.0,
 "steps": [{"tool": "reregister_fullres", "args": {...}, "result_summary": "...", "ms": 0}],
 "actions": [{"type": "SET_REFERENCE|QUARANTINE|DENSIFY|MARK_PROVISIONAL|OPEN_TICKET|DRAFT_ALERT|NOOP", "args": {...}, "needs_approval": false}],
 "rationale": "≤ 3 sentences", "approval_id": null}
```

- **Approval rule:** `DRAFT_ALERT` and `OPEN_TICKET` always need approval. They become a pending item at `live/approvals/<approval_id>.json`, and a human approves or rejects it on the dashboard's approval page (token-protected) or through the SNS email link.
- **Autonomous actions:** `SET_REFERENCE`, `QUARANTINE`, `DENSIFY` and `MARK_PROVISIONAL` happen without approval. They are reversible and logged.
- **Log:** every decision is appended to `live/agent/YYYY-MM-DD.jsonl`.

## 4. OpenCV tools the agent may call (W2 owns `riversight.agent.tools`)
Pure functions over the model bundle and frames. Every one returns JSON-serialisable output plus a short `summary` string.

| tool | what it does |
|---|---|
| `reregister_fullres(cam, frame_key)` | ALIKED+LightGlue+MAGSAC on 2688×1520 against every reference in the bank |
| `compare_to_last_good(cam, frame_key)` | `phaseCorrelate` shift, plus SSIM-style similarity of the static-structure mask |
| `image_quality(frame_key)` | Laplacian variance, glare and fog scores, IR/night detection |
| `estimate_stage(cam, frame_key, ref=None)` | Scene model → stage ± σ |
| `render_wet_overlay(cam, frame_key, stage_ft)` | Draws every block with h* ≤ stage, i.e. what would be under water at that stage |
| `get_gauge(nwis_id, hours)` | Recent gauge readings (USGS IV) |
| `get_nws_forecast(nwis_id)` | NWPS forecast and flood categories, if the gauge has them |
| `fetch_recent_frames(cam, n)` | The n most recent frames for this camera, from NIMS |

## 5. Fault-injection episode format (W2 builds, W3 reports)
`results/agent_eval/episodes.jsonl`: one line per episode `{episode_id, kind, cam_id, source:"real|synthetic", injected:{...}, expected_actions:[...], t0}`. Results go to `results/agent_eval/results.csv`, which is scored by `scripts/agent_eval.py`.
