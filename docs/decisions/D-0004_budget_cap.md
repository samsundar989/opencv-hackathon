# D-0004 — 2026-10-14 — Hard AWS budget cap: $100 (Samuel)

Samuel: "keep my spend limit to $100, I don't want to spend more than that on this unless we are proven to be working and progressing well."

Rules for Claude Code:
1. Total AWS spend for this competition ≤ **$100** (credits of $120 cover it; the cap is on *charges* so the card is never hit unless Samuel raises it after the kill test + fleet eval pass).
2. Before launching any EC2 instance: create an AWS Budget (`riversight-monthly`, $100, alerts at 25/50/75/90% to samsundar989@gmail.com) and a stop-EC2 action at 90%; CloudWatch billing alarm as backup. Put both in `infra/` (CDK) and verify in `docs/STATUS.md` with the budget ARN.
3. Live stack = minimal variant only: one Graviton instance (c8g.medium or large), CloudFront Free plan, S3/DynamoDB/EventBridge/SQS/Lambda inside free tier, Bedrock Haiku 5.5 with a daily token cap in code. Benchmarks on spot/short-lived instances, terminated by the script.
4. Any action expected to cost > $10 → write `Q-NNNN` in `docs/HUMAN.md` first.
5. Raising the cap requires Samuel's explicit OK (after D-0002 PASS and the fleet table in SLICE_02).

Claude Code: append this ruling to `docs/DECISIONS.md` as D-0004 on your next commit (Cowork could not edit DECISIONS.md without risking a conflict with your working tree).
