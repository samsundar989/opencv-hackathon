# Superseded agent-eval runs (kept for the record)

| file | episode set | what was wrong |
|---|---|---|
| `episodes_v1.jsonl`, `FROZEN_v1.json`, `rules.jsonl`, `REPORT_v1.md` | v1 (sha `336a7cc1…`) | 4 view episodes labelled from the history pipeline's registration flags; at eval time 2 Salt Creek frames match an earlier calibrated reference and 2 Mallard frames register to the main reference. Fixed in the builder (`bank_match`), set re-frozen as v2. |
| `rules_v2set_agebug.jsonl`, `REPORT_v2set_agebug.md` | v2 (sha `e12e0f29…`) | rules bug: `rules.rising` read a gauge 0.0 min old as missing (`age or 1e9`) and fell back to the camera. Found in the Hancock flood replay; fixed with a regression test (`test_rising_uses_gauge_reading_zero_minutes_old`), rules re-frozen. |

No LLM arm had run when either was superseded.
