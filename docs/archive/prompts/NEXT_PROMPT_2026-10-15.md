# Paste into Claude Code (opencv-hackathon)

Cowork reviewed SLICE_01 and answered Q-0004/5/6 (see the bottom of `docs/HUMAN.md`). We are NOT pivoting.
1. Read `docs/decisions/D-0006_scene_model_and_protocol.md`, `docs/research/2026-10-14_waterlevel_investigation.md` and `experiments/cowork_2026-10-14/README.md`.
2. Append D-0004 and D-0006 to `docs/DECISIONS.md`. Gitignore `docs/AWS_ACCOUNT_NOTES.md` and `_xfer/` (Cowork transfer tarballs; you may delete `_xfer/`). Commit with `[S01B] cowork review: D-0006, SLICE_01B, reference experiment`.
3. Execute `docs/slices/SLICE_01B_SCENE_MODEL_RERUN.md` end to end. The step 1 reproduction gate comes first. History fetch and registration go through worker-q at low priority. The frozen test days are scored exactly once, by Oct 17 09:00 CT.
4. Keep `docs/STATUS.md` current at every stopping point. Put questions in `docs/HUMAN.md` and keep working on something else meanwhile.
