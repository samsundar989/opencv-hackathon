# HUMAN — questions for Samuel (Q-NNNN) and answers (## ANSWER NNNN)

Claude Code appends questions here when blocked on something only Samuel can decide or do, then continues with other work. Samuel answers inline; Cowork may also answer on his behalf for non-cost, non-irreversible items.

## Q-0001 — workerq docs location and submit command
Cowork could not read `C:\Users\samsu\Documents\gpu-queue` (folder not connected). Claude Code: read the docs there yourself and record the current submit command in `docs/DECISIONS.md` (D-0003). If that folder is not workerq, Samuel: where do the workerq docs live?

## Q-0002 — Global Python version and CUDA PyTorch
Samuel said to use the latest global environment. Claude Code: run `python --version`, `python -c "import torch;print(torch.__version__, torch.cuda.is_available(), torch.version.cuda)"` and record both in `docs/STATUS.md`. If torch is missing or has no CUDA for the RTX 5090 (sm_120 needs CUDA ≥12.8 builds), ask Samuel before installing a new torch globally.

## Q-0003 — USGS API key
Needed for comfortable rate limits: https://api.waterdata.usgs.gov/signup/ (free, instant). Samuel: paste it into `.env` as `USGS_API_KEY=...` (never into chat). Claude Code proceeds at a low request rate until then.

### Claude Code notes (2026-10-14)
- Q-0001: answered by D-0005 (worker-q docs found at `C:\Users\samsu\Documents\gpu-queue`).
- Q-0002: global Python is **3.14.4**; **torch is not installed** there. SLICE_01 doesn't need it. Before SLICE_03, Samuel: OK to `python -m pip install torch --index-url https://download.pytorch.org/whl/cu128` (or newer) into the global 3.14? If no cp314 CUDA wheel exists I will create `.venv` (uv, Python 3.12/3.13) for training only and say so in STATUS.
- Q-0003: answered — key is in `.env`.

## Q-0004 — Commit `docs/AWS_ACCOUNT_NOTES.md`?
It contains AWS account IDs, the console URL slug and the card's last 4 digits. The repo will be shared with judges, so I left it untracked. Options: (a) keep it local-only (add to `.gitignore`), (b) commit a redacted copy. My recommendation: (b). Until answered, it stays untracked.
