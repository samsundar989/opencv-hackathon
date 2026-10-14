# HUMAN — questions for Samuel (Q-NNNN) and answers (## ANSWER NNNN)

Claude Code appends questions here when blocked on something only Samuel can decide or do, then continues with other work. Samuel answers inline; Cowork may also answer on his behalf for non-cost, non-irreversible items.

## Q-0001 — workerq docs location and submit command
Cowork could not read `C:\Users\samsu\Documents\gpu-queue` (folder not connected). Claude Code: read the docs there yourself and record the current submit command in `docs/DECISIONS.md` (D-0003). If that folder is not workerq, Samuel: where do the workerq docs live?

## Q-0002 — Global Python version and CUDA PyTorch
Samuel said to use the latest global environment. Claude Code: run `python --version`, `python -c "import torch;print(torch.__version__, torch.cuda.is_available(), torch.version.cuda)"` and record both in `docs/STATUS.md`. If torch is missing or has no CUDA for the RTX 5090 (sm_120 needs CUDA ≥12.8 builds), ask Samuel before installing a new torch globally.

## Q-0003 — USGS API key
Needed for comfortable rate limits: https://api.waterdata.usgs.gov/signup/ (free, instant). Samuel: paste it into `.env` as `USGS_API_KEY=...` (never into chat). Claude Code proceeds at a low request rate until then.
