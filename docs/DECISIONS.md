# DECISIONS (append-only; D-NNNN)

## D-0001 — 2026-10-13 — Project = RiverSight (Samuel: "go on riversight")
Context: `docs/research/ideas.md`, `docs/research/prior-art.md`, `docs/research/rivals-oct13.md`.
Decision: build RiverSight per `docs/PLAN_2026-10-13_RIVERSIGHT.md`. Alternatives (Porter, SkyFix) are fallbacks only if SLICE_01 fails.
Constraints restated by Samuel: use the latest globally installed Python environment; GPU jobs via workerq (read its docs first); RunPod credits are limited and shared — use only when needed; get to a POC and working demo ASAP.

## D-0002 — (pending) — Kill test verdict
To be written by Claude Code at the end of SLICE_01 with the per-site table (PASS requires registration ≥90% and MAE ≤0.25 ft at ≥10/20 sites on the 10 test days).

## D-0003 — 2026-10-14 — AWS Region us-east-2, profile `riversight`, Agent Toolkit for AWS
Context: Samuel's AWS project uses the new AWS experience with assigned Region us-east-2. Projects can only create Regional resources in their assigned Region (us-east-1 is allowed only for CloudFront, global WAF and their CloudWatch Logs).
Decision: all Regional resources (EC2/Graviton, S3, DynamoDB, Bedrock, Step Functions, Lambda) go in us-east-2. CLI auth is `aws login --profile riversight` (no long-lived access keys). The Agent Toolkit for AWS (AWS MCP server + skills) is configured against that profile; its service endpoint is us-east-1 by design. AWS rules from the toolkit are appended to CLAUDE.md between markers; project rules win on conflict.
Open risks: confirm in us-east-2 that the COOL AMI, c8g/c9g Graviton instances and the Bedrock models in the plan are available, and that cross-Region inference profiles aren't blocked by the project's SCPs.
