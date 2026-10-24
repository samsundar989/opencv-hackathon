# Fri Oct 23 follow-up: paste into each running session (or a new one) once `aws login --profile riversight` has succeeded

## W1
Samuel has run `aws login --profile riversight` (Q-0008 answered).
1. `git pull` and read `docs/decisions/D-0009_review_oct23.md`.
2. Deploy now: `cdk bootstrap` → `python scripts/deploy.py --guard-only` (record the ARNs) → `python scripts/deploy.py` on the stock arm64 worker. Send the CloudFront URL to Samuel in this chat as soon as it serves.
3. Then fix D-0009's W1 must-fix items 1–7, in order. Redeploy after items 1–3.
4. When Samuel answers Q-0009 (COOL subscribed), redeploy the worker on the COOL G5 AMI (m9g) and confirm in `/proof.json`.
5. Record the actual spend in `docs/status/W1.md`.

## W2
Samuel has run `aws login --profile riversight`.
1. `git pull` and read `docs/decisions/D-0009_review_oct23.md`.
2. Add the OUT_OF_RANGE and LOW_QUALITY-during-RISING behavior with its episodes, re-freeze, and only then run the pilot.
3. Run the arms per D1 (Haiku 3×, Haiku-no-OpenCV 3×, Sonnet 1×; Sonnet 2× more only if ≤ $10 measured).
4. Once W1's site is live: one approval round-trip with a screenshot, plus the kill-switch and token-cap demo.
5. Write `results/agent_eval/summary.json` so `/judge` picks it up.

## W3
1. `git pull` and read `docs/decisions/D-0009_review_oct23.md`.
2. Apply the corrected numbers (8/20, 9/19) in the README, report and docs, and extend `check_report_numbers.py` to `web/judge.html`.
3. Run the COOL A/B as soon as W1's bucket exists and Samuel has subscribed (Q-0009). The Sat 12:00 fallback is in D-0009.
4. Report v2 Sat; final PDF Sun noon.
