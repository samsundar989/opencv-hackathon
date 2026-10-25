# D-0015 — 2026-10-25 (Sun 12:20 CT) — W1/W2 idle: reassign their D-0014 items (Cowork)

**Context.** W1 and W2 have made no commits since Sat about 17:00 CT, and Samuel has not been able to restart them yet. W3, W4 and W5 are active. The v2 serving decision was made in D-0014 (all D-0010 §2 criteria met: 249 paired readings, 0.084 vs 0.183 ft; cycle 42–61 s), but v2 is not deployed: `latest.json` still carries the v1 `model_sha`.

**Ruling.** The full item list is in the `docs/HUMAN.md` note of 2026-10-25 12:20 CT.
- **W4 takes W1's deploy list:**
  - v2 serving and the fused filter with `F.b = 0`
  - the recal patch, in shadow mode
  - G2 fixes: the title, the approval TTL, superseded tide alerts
  - the guard stop at 100%
  - the Bedrock token cap
  - batch-2 bundles
- **W5 takes W2's list:** the king-tide advisory and `RECALIBRATE` as a rules action, with no Bedrock spend.
- **W3** recaptures B-roll and flips the "approved, not deployed" wording only after the v2 sha appears live.

If W1 or W2 restart, they read this file and coordinate through status files; the reassigned owner finishes whatever item it has started.

**Cutoffs:** nothing risky after Mon 10:00 CT, and code freezes Mon 12:00 CT.
