# River Steward — agent evaluation

Episode set: `results/agent_eval/episodes.jsonl`, sha256 `706de0cfda245e9cd4511fd367d576036eb1a4e6c50b5343c55d59cc97765b9a` (frozen 2026-10-24T21:06:42+00:00, git 3c340eef9); 108 single-camera episodes (73 real) + 12 fleet cycles. Expected actions were written by `scripts/agent_build_episodes.py` before any arm ran. Every number below is computed by `scripts/agent_eval.py report` from `results/agent_eval/runs/*.jsonl`.

Arms: **rules** = deterministic policy (`agent/rules.py`); **haiku** = Bedrock Claude Haiku 4.5 agent with the OpenCV tools; **haiku_noev** = the same agent whose tools return only the reading's flags (no OpenCV evidence); **sonnet** = the agent on Claude Sonnet 4.6; **opus** = the agent on Claude Opus 4.5 (if run). **hybrid** = D-0012 rules-first: the rules act, Sonnet reviews gauge drift and ranks the fleet. Claude 5.5 models are not available to this AWS account (docs/HUMAN.md ANSWER 0010). Each arm ran every episode 3×; cells show mean over repeats (min–max across repeats).

## Headline

| arm | task success | real episodes | synthetic | false-action rate on clean controls | unneeded escalations / episode | fleet top-1 | fleet Kendall τ | LLM fallbacks | p50 / p95 latency (s) | tokens / episode | $ / episode (est.) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| rules | 92.6% (92.6%–92.6%) | 95.9% (95.9%–95.9%) | 85.7% (85.7%–85.7%) | 0.0% (0.0%–0.0%) | 0.01 | 83.3% (83.3%–83.3%) | 0.86 | 0/324 | 0.8 / 6.7 | 0 | 0.0000 |
| haiku | 58.8% (56.1%–61.2%) | 54.5% (49.2%–60.3%) | 66.7% (62.9%–68.6%) | 7.7% (3.8%–11.5%) | 0.08 | 44.4% (33.3%–50.0%) | 0.50 | 3/294 | 42.0 / 65.4 | 9,928 | 0.0147 |
| haiku_noev | 51.4% (49.0%–55.1%) | 47.6% (42.9%–54.0%) | 58.1% (57.1%–60.0%) | 15.4% (11.5%–19.2%) | 0.11 | 52.8% (41.7%–66.7%) | 0.47 | 1/294 | 41.2 / 61.9 | 9,169 | 0.0140 |
| sonnet | 71.4% (71.4%–71.4%) | 79.4% (79.4%–79.4%) | 57.1% (57.1%–57.1%) | 3.8% (3.8%–3.8%) | 0.21 | 100.0% (100.0%–100.0%) | 0.89 | 0/98 | 55.7 / 77.1 | 11,692 | 0.0523 |
| hybrid | 93.2% (92.6%–93.5%) | 95.9% (95.9%–95.9%) | 87.6% (85.7%–88.6%) | 0.0% (0.0%–0.0%) | 0.01 | 86.1% (83.3%–91.7%) | 0.90 | 0/324 | 0.8 / 6.8 | 1,786 | 0.0096 |

## Task success by episode kind

| kind | source | n | rules | haiku | haiku_noev | sonnet | hybrid |
|---|---|---|---|---|---|---|---|
| control_disagree | real | 5 | 100% | 73% | 87% | 80% | 100% |
| control_rise | real | 4 | 100% | 100% | 92% | 100% | 100% |
| control_view | real | 8 | 100% | 100% | 71% | 100% | 100% |
| disagree_camfault | synthetic | 4 | 75% | 33% | 8% | 0% | 75% |
| gauge_drift | synthetic | 3 | 0% | 11% | 22% | 67% | 22% |
| gauge_flatline | synthetic | 2 | 100% | 17% | 100% | 100% | 100% |
| gauge_offset | synthetic | 4 | 75% | 100% | 92% | 100% | 75% |
| muddy_rise | real | 6 | 100% | 17% | 33% | 100% | 100% |
| muddy_stale | synthetic | 3 | 100% | 89% | 0% | 33% | 100% |
| oor_gauge | real | 5 | 100% | 20% | 40% | 0% | 100% |
| oor_live | real | 4 | 100% | 25% | 17% | 0% | 100% |
| oor_stale | synthetic | 2 | 100% | 33% | 50% | 0% | 100% |
| reanchor_banked | real | 10 | 100% | 73% | 0% | 100% | 100% |
| reg_loss_onset | real | 4 | 100% | 25% | 50% | 50% | 100% |
| reg_loss_persist | real | 8 | 100% | 50% | 71% | 88% | 100% |
| rise_alert | real | 8 | 88% | 33% | 46% | 100% | 88% |
| rise_minor | real | 1 | 100% | 67% | 33% | 100% | 100% |
| stale_camera | synthetic | 5 | 100% | 87% | 87% | 20% | 100% |
| stale_night | synthetic | 3 | 100% | 44% | 0% | 33% | 100% |
| tidal_flood | real | 2 | 0% | – | – | – | 0% |
| tidal_live_false_alert | real | 1 | 100% | – | – | – | 100% |
| tidal_tide | real | 7 | 100% | – | – | – | 100% |
| view_shift | synthetic | 3 | 100% | 100% | 89% | 100% | 100% |
| view_transient | synthetic | 6 | 100% | 89% | 94% | 100% | 100% |

## Detection in cycles (real registration loss)

Onset = the first flagged cycle of a real registration-loss segment; persistent = the previous two readings were already flagged. Detection = QUARANTINE in that cycle; escalation = recalibration ticket.

| arm | quarantined at onset | ticket at onset (premature) | quarantined when persistent | ticket when persistent |
|---|---|---|---|---|
| rules | 100% | 0% | 100% | 100% |
| haiku | 25% | 42% | 79% | 62% |
| haiku_noev | 50% | 75% | 92% | 79% |
| sonnet | 50% | 75% | 88% | 100% |
| hybrid | 100% | 0% | 100% | 100% |

## Failure cases

**rules** — 8 episodes failed at least once:

- `disagree_camfault-TX_Buffalo_Bayou_at_Stat-20261009T1700` (3/3 repeats): did `NOOP`, missing `QUARANTINE`. *fresh camera estimate agrees with the gauge (-0.06 ft, σ 0.41); low-quality frame; the quality gate already suppresses it.*
- `gauge_drift-IL_Salt_Creek_at_Wood_Da-20261007T1600` (3/3 repeats): did `QUARANTINE`, missing `OPEN_TICKET`, forbidden `QUARANTINE`, wrong args. *camera differs by -1.28 ft with a normal-looking gauge; trusting the gauge, camera quarantined.*
- `gauge_drift-NJ_Stony_Brook_at_Prince-20261008T1900` (3/3 repeats): did `QUARANTINE`, missing `OPEN_TICKET`, forbidden `QUARANTINE`, wrong args. *camera differs by -1.11 ft with a normal-looking gauge; trusting the gauge, camera quarantined.*
- `gauge_drift-TX_Buffalo_Bayou_at_Stat-20261009T1800` (3/3 repeats): did `QUARANTINE`, missing `OPEN_TICKET`, forbidden `QUARANTINE`, wrong args. *camera differs by -1.10 ft with a normal-looking gauge; trusting the gauge, camera quarantined.*
- `gauge_offset-NJ_Big_Brook_near_Marlbo-20261007T2100` (3/3 repeats): did `QUARANTINE`, missing `OPEN_TICKET`, forbidden `QUARANTINE`, wrong args. *camera fault: frame does not register; readings quarantined.*
- `rise_alert-CA_First_Mallard_Branch_-20261006T1615` (3/3 repeats): did `NOOP`, missing `DENSIFY+DRAFT_ALERT`. *tidal site: 26.43 ft is the ordinary tide (predicted 26.791 ft, residual -0.36 ft < 1.22); no alert.*
- `tidal_flood-GA_Savannah_River_at_USA-20260908T2300` (3/3 repeats): did `NOOP`, missing `DENSIFY+DRAFT_ALERT`. *tidal site: 5.66 ft is the ordinary tide (predicted 6.284 ft, residual -0.62 ft < 2.48); no alert.*
- `tidal_flood-GA_Savannah_River_at_USA-20261010T1400` (3/3 repeats): did `NOOP`, missing `DENSIFY+DRAFT_ALERT`. *tidal site: 5.73 ft is the ordinary tide (predicted 6.331 ft, residual -0.60 ft < 2.48); no alert.*

**haiku** — 60 episodes failed at least once:

- `control_disagree-OH_East_Fork_Little_Miam-20261004T1700` (2/3 repeats): did `OPEN_TICKET`, forbidden `OPEN_TICKET`. *The flagged disagreement is not a transient camera problem: the frame is usable, well-registered, and consistent with recent camera readings. The persistent offset (~0.35–0.56 ft) over multiple cycles, with a stable gaug*
- `control_disagree-TX_Tenmile_Ck_at_Parkins-20261005T2300` (2/3 repeats): did `OPEN_TICKET`, forbidden `OPEN_TICKET`. *The frame is usable, well-registered, and shows the same view as the previous hour, but exhibits a persistent 6-hour pattern of camera readings above a flat gauge. This is not a transient imaging problem but a systematic*
- `disagree_camfault-CO_Sand_Creek_at_Mouth_n-20261007T1835` (3/3 repeats): did `NOOP`, missing `QUARANTINE`. *Frame is not usable due to fog, blurring, and severe texture loss (lap_var 8 vs site p5 1485, fog 0.62), but the camera is still registered to the correct view and prior readings tracked the gauge accurately. The 0.48 ft*
- `disagree_camfault-MN_Root_River_near_Pilot-20261009T1700` (1/3 repeats): did `NOOP`, missing `QUARANTINE`. *Frame view is unchanged vs last good frame (0.3 px shift, same geometry), but image quality is NOT usable due to severe texture loss (46%), fog score 0.27, and elevated lap_var (1006 vs site p5 932). The stage reading of*
- `disagree_camfault-OH_East_Fork_Little_Miam-20261005T2000` (1/3 repeats): did `NOOP`, missing `QUARANTINE`. *Frame registers to current reference but image quality is not usable due to significant texture loss (0.46 fraction, likely transient lens occlusion or fog). Structural similarity to last good frame is 0.28, same view ge*
- `disagree_camfault-TX_Buffalo_Bayou_at_Stat-20261009T1700` (3/3 repeats): did `NOOP`, missing `QUARANTINE`. *Frame is usable, well-registered to reference (same view, 0.8 px shift), and gauge is fresh and stable. The 1.24 ft camera overestimate is an anomaly near the camera's calibrated maximum; likely saturation, not a camera *
- `gauge_drift-IL_Salt_Creek_at_Wood_Da-20261007T1600` (3/3 repeats): did `OPEN_TICKET`, wrong args. *The camera is well-registered, usable, and stable; the gauge is fresh and normal. The persistent ~1.4 ft negative bias suggests a camera calibration drift, not a transient fault or gauge issue. Escalate for human recalib*
- `gauge_drift-NJ_Stony_Brook_at_Prince-20261008T1900` (3/3 repeats): did `OPEN_TICKET`, wrong args. *The camera registers well and frames are usable, but systematically reads ~1.1 ft lower than the fresh gauge across all recent readings. This persistent offset—well outside ±0.4 ft error band—suggests camera calibration *
- `gauge_drift-TX_Buffalo_Bayou_at_Stat-20261009T1800` (2/3 repeats): did `MARK_PROVISIONAL`, missing `OPEN_TICKET`, wrong args. *The frame is usable and well-registered; the camera-gauge disagreement reflects saturation as the stage approaches the camera's calibrated ceiling (60.83 ft). The gauge is fresh, stable, and trustworthy; use it as provis*
- `gauge_flatline-CA_First_Mallard_Branch_-20261012T1645` (2/3 repeats): did `NOOP`, missing `OPEN_TICKET`, wrong args. *Frame is usable, well-registered to current reference, and the same view as prior frames. The metadata gauge value (28.99 ft) is stale; the actual latest gauge is 26.02 ft, which matches the camera's 26.23 ft estimate wi*
- `gauge_flatline-CA_First_Mallard_Branch_-20261012T1845` (3/3 repeats): did `NOOP`, missing `OPEN_TICKET`, wrong args. *Gauge was stuck at 28.38 ft for 3 hours while camera tracked actual water correctly (27.8 → 26.6 ft); gauge just corrected to 26.61 ft matching camera. Current frame is usable, well-registered, and the DISAGREE flag reso*
- `muddy_rise-CO_Animas_River_at_Duran-20260914T2115` (1/3 repeats): did `NOOP`, missing `DENSIFY`. *The frame fails to register and shows texture loss, but this is transient muddy water during an active rise (gauge up 0.18 ft/h, now 2.33 ft), not a camera fault. Recent frames show lap_var improving over time, consisten*
- `muddy_rise-MN_Root_River_near_Pilot-20260919T1700` (3/3 repeats): did `DENSIFY+MARK_PROVISIONAL`, missing `DRAFT_ALERT`. *Camera registers well but reports 16.05 ft vs. gauge 15.39 ft; texture loss (0.63) from muddy floodwater is a transient quality issue, not a fault. Fresh gauge reading is more reliable during poor visibility. Sampling ev*
- `muddy_rise-NJ_Stony_Brook_at_Prince-20260706T2100` (3/3 repeats): did `DENSIFY`, missing `DRAFT_ALERT`. *Frame registers well (220 inliers, 0.883 score) and camera stage 3.59 ft matches fresh gauge 3.6 ft within error band. Texture loss is transient, consistent with muddy water and flooded banks during a persistent rise; th*

**haiku_noev** — 69 episodes failed at least once:

- `control_disagree-OH_East_Fork_Little_Miam-20261004T1700` (1/3 repeats): did `OPEN_TICKET`, forbidden `OPEN_TICKET`. *Frame is well-registered, high quality, and daylight; the persistent ~0.34 ft camera-high bias across 5+ recent readings exceeds normal noise despite being within 1 sigma. Fresh gauge is stable. No view change or lens fa*
- `control_disagree-TX_Tenmile_Ck_at_Parkins-20261005T2300` (1/3 repeats): did `OPEN_TICKET`, forbidden `OPEN_TICKET`. *The frame is usable and registers acceptably, but the camera has run 0.4–1.0 ft high vs. the fresh gauge consistently. This pattern suggests either gauge drift or reference aging rather than a transient camera fault. Ope*
- `control_rise-NY_Neversink_River_at_Go-20261011T2100` (1/3 repeats): did `DENSIFY+DRAFT_ALERT`, forbidden `DRAFT_ALERT`. *Camera is well-registered and image quality is good; measurement agrees with gauge within error band. River is actively rising (3.4→3.573 ft in 6h). Densify sampling to 15-minute intervals for 6 hours to track the rise p*
- `control_view-MN_Root_River_near_Pilot-20261008T1500` (1/3 repeats): did `MARK_PROVISIONAL`, forbidden `MARK_PROVISIONAL`. *Frame registered marginally to current reference with borderline inlier ratio; image quality is acceptable. Camera stage 8.948 ft agrees with gauge 8.56 ft within error band (±1.743 ft). The VIEW_CHANGE flag alternates w*
- `control_view-OH_Bean_Creek_at_Powers-20261013T1600` (2/3 repeats): did `MARK_PROVISIONAL`, forbidden `MARK_PROVISIONAL`. *This frame fails all registration checks but image quality is good (fog 0.16, glare 0.09) and the camera estimate (8.082 ft) is within the calibrated range and error band of the fresh gauge (8.39 ft). All 6 prior reading*
- `control_view-PA_Brandywine_Creek_at_C-20261004T2100` (1/3 repeats): did `QUARANTINE`, forbidden `QUARANTINE`. *Frame fails ALIKED+LightGlue+MAGSAC fullres registration despite earlier ORB success, indicating a genuine view change from the calibrated reference. This is a new condition (prior 6 readings registered cleanly). Camera *
- `control_view-TX_White_Rk_Ck_at_Greenv-20261013T1400` (1/3 repeats): did `MARK_PROVISIONAL`, forbidden `MARK_PROVISIONAL`. *Frame registers with borderline confidence and full re-registration flags VIEW_CHANGE, but image quality is acceptable and the camera estimate (69.37 ft) is consistent with the historical camera-gauge offset (~0.8 ft). T*
- `control_view-WI_East_Branch_Pecatonic-20261007T1500` (2/3 repeats): did `OPEN_TICKET+QUARANTINE`, forbidden `OPEN_TICKET+QUARANTINE`. *The frame initially registered but full reregistration against all banked references (ORB + ALIKED + MAGSAC) confirms it no longer matches any calibrated view. This represents a persistent camera shift from 6 prior stabl*
- `disagree_camfault-CO_Sand_Creek_at_Mouth_n-20261007T1835` (3/3 repeats): did `NOOP`, missing `QUARANTINE`. *Frame registered successfully but poor image quality (fog, night IR artifacts) caused a 0.484 ft measurement spike above the fresh gauge reading and recent camera trend. This is a transient optical degradation, not a vie*
- `disagree_camfault-MN_Root_River_near_Pilot-20261009T1700` (3/3 repeats): did `NOOP`, missing `QUARANTINE`. *Frame registers successfully but reports 13.73 ft vs. gauge 8.5 ft—a 5.23 ft jump that contradicts 6 hours of stable agreement. Elevated fog (0.27) and glare (0.10) suggest transient lens occlusion/fogging, not a true me*
- `disagree_camfault-OH_East_Fork_Little_Miam-20261005T2000` (2/3 repeats): did `NOOP`, missing `QUARANTINE`. *Frame is occluded (noted in frame_key) with low sharpness and fog. Despite registration success, the marginal inlier ratio (0.313) and sudden 2.2 ft jump above a stable 6-hour trend strongly suggest the registration is u*
- `disagree_camfault-TX_Buffalo_Bayou_at_Stat-20261009T1700` (3/3 repeats): did `NOOP`, missing `QUARANTINE`. *Frame registered successfully but image quality is degraded by fog (fog_score 0.3451, lap_var 220.74), causing the camera reading (60.29 ft) to be artificially elevated versus the fresh gauge (59.05 ft). The previous fra*
- `gauge_drift-IL_Salt_Creek_at_Wood_Da-20261007T1600` (1/3 repeats): did `OPEN_TICKET`, wrong args. *The camera registers well and image quality is good, but shows a persistent systematic ~1.3 ft underestimate relative to the gauge across six consecutive readings over 18 hours. This is not a transient registration or qu*
- `gauge_drift-NJ_Stony_Brook_at_Prince-20261008T1900` (3/3 repeats): did `OPEN_TICKET`, wrong args. *Camera frame registers cleanly with good image quality, but shows persistent systematic disagreement (~1.1 ft low) versus the gauge across 6+ consecutive hourly readings. This is not a transient view or quality issue but*

**sonnet** — 28 episodes failed at least once:

- `control_disagree-CO_Animas_River_at_Duran-20261005T1830` (1/1 repeats): did `MARK_PROVISIONAL+OPEN_TICKET`, forbidden `OPEN_TICKET`. *The frame is well-registered, fully usable, and the gauge is fresh and well-behaved — the 0.19 ft disagreement is within the camera's 1-sigma band of 0.63 ft, so no quarantine or gauge suspicion is justified. However, th*
- `disagree_camfault-CO_Sand_Creek_at_Mouth_n-20261007T1835` (1/1 repeats): did `NOOP`, missing `QUARANTINE`. *The frame is severely degraded by a transient quality event (lap_var 7.6 vs site p5 of 1485, texture_loss 0.97, fog 0.62) that appeared abruptly in this single frame — all four preceding frames were clean (lap_var ~3900–*
- `disagree_camfault-MN_Root_River_near_Pilot-20261009T1700` (1/1 repeats): did `MARK_PROVISIONAL+OPEN_TICKET+QUARANTINE`, forbidden `OPEN_TICKET`. *The LOW_QUALITY and DISAGREE flags are caused by a confirmed and worsening lens occlusion (texture_loss_frac = 0.46, lap_var declining from 5120 → 1006 over 2 hours), which has inflated the camera stage estimate to a spu*
- `disagree_camfault-OH_East_Fork_Little_Miam-20261005T2000` (1/1 repeats): did `OPEN_TICKET+QUARANTINE`, forbidden `OPEN_TICKET`. *Full-res re-registration confirms the camera is correctly anchored to its reference (149 ALIKED+LightGlue inliers, 6.7 px corner shift), so the VIEW_CHANGE/ORB weak result was a false alarm and no SET_REFERENCE is needed*
- `disagree_camfault-TX_Buffalo_Bayou_at_Stat-20261009T1700` (1/1 repeats): did `DENSIFY+MARK_PROVISIONAL`, missing `QUARANTINE`. *The frame has rain droplets on the lens (transient LOW_QUALITY) that corrupt the waterline estimate, pushing the camera reading 1.24 ft above the gauge (3× sigma); however the frame registers solidly to the current refer*
- `gauge_drift-TX_Buffalo_Bayou_at_Stat-20261009T1800` (1/1 repeats): did `DENSIFY+MARK_PROVISIONAL+OPEN_TICKET`, wrong args. *The frame is usable and registers cleanly to the current reference, but the camera has under-read the gauge by ~1–1.5 ft across 6 consecutive well-registered frames while the gauge is fresh, smooth, and only 0.74 ft belo*
- `muddy_stale-OH_Bean_Creek_at_Powers-20260418T1700` (1/1 repeats): did `DENSIFY+MARK_PROVISIONAL+OPEN_TICKET`, forbidden `OPEN_TICKET`. *The gauge has been silent for 6 hours but was well-behaved before dropout; the camera registers cleanly (142 inliers) and independently estimates 13.42 ± 1.10 ft — identical to the last gauge reading — so it is published*
- `muddy_stale-TX_Buffalo_Bayou_at_Stat-20260616T1700` (1/1 repeats): did `DENSIFY+MARK_PROVISIONAL+OPEN_TICKET`, forbidden `OPEN_TICKET`. *The USGS gauge has been stale for 6 hours (last reading 57.56 ft at 11:00Z); the camera frame registers cleanly to the reference (255 inliers, score 0.832) and estimate_stage returns 57.89 ± 0.41 ft — within calibrated r*
- `oor_gauge-NY_East_Branch_Delaware_-20260729T1200` (1/1 repeats): did `DENSIFY+DRAFT_ALERT+MARK_PROVISIONAL`, forbidden `MARK_PROVISIONAL`. *The camera's 10.08 ft reading is pure saturation — the gauge is a fresh, well-behaved 17.43 ft, which is 6.25 ft above the camera's calibrated ceiling of 11.18 ft; DISAGREE and OUT_OF_RANGE are expected artefacts, not ca*
- `oor_gauge-NY_East_Branch_Delaware_-20260729T1800` (1/1 repeats): did `DENSIFY+DRAFT_ALERT+MARK_PROVISIONAL`, forbidden `MARK_PROVISIONAL`. *The camera is well-registered (0.924 inlier ratio) and the frame is fully usable; the DISAGREE flag is entirely explained by OUT_OF_RANGE saturation — the gauge reads 18.01 ft while the camera's calibrated ceiling is onl*
- `oor_gauge-NY_East_Branch_Delaware_-20260730T1200` (1/1 repeats): did `DENSIFY+DRAFT_ALERT+MARK_PROVISIONAL`, forbidden `MARK_PROVISIONAL`. *The camera is healthy — firmly registered (616 inliers, 3.6 px corner shift), usable image quality, no view change — and the DISAGREE flag is explained entirely by saturation: the gauge reads 12.65 ft while the camera's *
- `oor_gauge-WI_East_Branch_Pecatonic-20260415T1300` (1/1 repeats): did `DENSIFY+DRAFT_ALERT+MARK_PROVISIONAL`, forbidden `MARK_PROVISIONAL`. *The gauge reads 9.17 ft — 3.6 ft above this camera's calibrated ceiling of 5.58 ft — and is fresh, steadily rising (+1.15 ft in 6 h), with no anomalous steps; the camera's reported 4.62 ft is saturation at its calibrated*
- `oor_gauge-WI_East_Branch_Pecatonic-20260415T1900` (1/1 repeats): did `DENSIFY+DRAFT_ALERT+MARK_PROVISIONAL+OPEN_TICKET+QUARANTINE`, forbidden `MARK_PROVISIONAL+OPEN_TICKET+QUARANTINE`. *The camera has persistently registered to an uncalibrated banked view (reference_20260207.jpg) for ≥3 consecutive cycles, confirming a real physical shift — likely flood-driven — not a transient fault; the camera cannot *
- `oor_live-CO_Animas_River_at_Duran-20261023T1845` (1/1 repeats): did `DENSIFY+DRAFT_ALERT+MARK_PROVISIONAL`, forbidden `MARK_PROVISIONAL`. *The camera frame re-registers cleanly to its current calibrated reference (50 ALIKED+LightGlue inliers); the live ORB pass was a false alarm. The gauge is fresh at 8.34 ft — well above the camera's calibrated ceiling of *

**hybrid** — 8 episodes failed at least once:

- `disagree_camfault-TX_Buffalo_Bayou_at_Stat-20261009T1700` (3/3 repeats): did `NOOP`, missing `QUARANTINE`. *fresh camera estimate agrees with the gauge (-0.06 ft, σ 0.41); low-quality frame; the quality gate already suppresses it.*
- `gauge_drift-IL_Salt_Creek_at_Wood_Da-20261007T1600` (1/3 repeats): did `QUARANTINE`, missing `OPEN_TICKET`, forbidden `QUARANTINE`, wrong args. *camera differs by -1.28 ft with a normal-looking gauge; trusting the gauge, camera quarantined.*
- `gauge_drift-NJ_Stony_Brook_at_Prince-20261008T1900` (3/3 repeats): did `QUARANTINE`, missing `OPEN_TICKET`, forbidden `QUARANTINE`, wrong args. *camera differs by -1.11 ft with a normal-looking gauge; trusting the gauge, camera quarantined.*
- `gauge_drift-TX_Buffalo_Bayou_at_Stat-20261009T1800` (3/3 repeats): did `QUARANTINE`, missing `OPEN_TICKET`, forbidden `QUARANTINE`, wrong args. *camera differs by -1.10 ft with a normal-looking gauge; trusting the gauge, camera quarantined.*
- `gauge_offset-NJ_Big_Brook_near_Marlbo-20261007T2100` (3/3 repeats): did `QUARANTINE`, missing `OPEN_TICKET`, forbidden `QUARANTINE`, wrong args. *camera fault: frame does not register; readings quarantined.*
- `rise_alert-CA_First_Mallard_Branch_-20261006T1615` (3/3 repeats): did `NOOP`, missing `DENSIFY+DRAFT_ALERT`. *tidal site: 26.43 ft is the ordinary tide (predicted 26.791 ft, residual -0.36 ft < 1.22); no alert.*
- `tidal_flood-GA_Savannah_River_at_USA-20260908T2300` (3/3 repeats): did `NOOP`, missing `DENSIFY+DRAFT_ALERT`. *tidal site: 5.66 ft is the ordinary tide (predicted 6.284 ft, residual -0.62 ft < 2.48); no alert.*
- `tidal_flood-GA_Savannah_River_at_USA-20261010T1400` (3/3 repeats): did `NOOP`, missing `DENSIFY+DRAFT_ALERT`. *tidal site: 5.73 ft is the ordinary tide (predicted 6.331 ft, residual -0.60 ft < 2.48); no alert.*

## Notes

- Costs are estimates at Anthropic first-party list prices per MTok in/out (Haiku 4.5 $1/$5, Sonnet 4.6 $3/$15, Opus 4.5 $5/$25); Bedrock bills its own rates. Latency = model time + original (uncached) tool compute time.
- Temperature is not set (model default), so repeats show the spread.
- Real episodes use cached USGS HIVIS frames and gauge records; synthetic faults are labelled `synthetic` (`agent/faults.py`, `tools.apply_gauge_fault`). No real gauge outage > 3 h exists in the 20 sites' history, so all gauge-stale episodes are synthetic dropouts on real frames.
- Tools use protocol-cut site bundles (training < 2026-10-03), so test-window frames are out-of-sample for the scene model. Test-day frames serve here only as agent inputs; nothing in the stage model was refit or tuned on them.
- `rise_*` labels are hindsight: an alert is expected iff the gauge reached the site's calibration p90 within 6 h.
