# Superseded agent-eval runs (kept for the record)

| file | episode set | what was wrong |
|---|---|---|
| `episodes_v1.jsonl`, `FROZEN_v1.json`, `rules.jsonl`, `REPORT_v1.md` | v1 (sha `336a7cc1…`) | 4 view episodes labelled from the history pipeline's registration flags; at eval time 2 Salt Creek frames match an earlier calibrated reference and 2 Mallard frames register to the main reference. Fixed in the builder (`bank_match`), set re-frozen as v2. |
| `rules_v2set_agebug.jsonl`, `REPORT_v2set_agebug.md` | v2 (sha `e12e0f29…`) | rules bug: `rules.rising` read a gauge 0.0 min old as missing (`age or 1e9`) and fell back to the camera. Found in the Hancock flood replay; fixed with a regression test (`test_rising_uses_gauge_reading_zero_minutes_old`), rules re-frozen. |

No LLM arm had run when either was superseded.
| `rules_v2set_prehysteresis.jsonl` | v2 | valid decisions (92.3%); superseded only because `tools.py` changed afterwards (display-only overlay cleanup), which changes the frozen hash. Re-run expected to be identical. |
| `rules_v2set_final.jsonl`, `REPORT_v2set_final.md` | v2 | final rules run on v2 (92.3%); superseded by set v3 (D-0009 adds out-of-range and muddy-rise behaviour + 20 episodes). |
| `rules_v3_prememfix.jsonl` | v3 | valid rules run (93.9%); re-run after the tools memory fix (shared ALIKED/LightGlue; 74/74 tool outputs identical, `memcheck.json`) so every final arm shares one freeze. |
| `rules_v3_final.jsonl` (+ `FROZEN_v3.json`) | v3 | final rules run on v3 (93.9%); superseded by set v4 (D-0013 W2-1 tidal: +10 episodes, the 98 v3 episodes unchanged). The LLM-only arms (haiku, haiku_noev, sonnet) ran under FROZEN_v3 and are kept as final for the v3 episodes. |
