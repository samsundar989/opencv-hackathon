# AWS setup — Samuel's checklist (do tonight; ~45 min)

Everything below is clickable by you only. Tick items in `docs/STATUS.md` or tell Cowork. Region for everything: **us-east-1 (N. Virginia)** — COOL AMIs, Graviton c8g and the Bedrock models we need are all there.

## A. Create the account (10 min)
1. Go to **https://aws.amazon.com/free/** → **Create a free account** (it goes to `https://signin.aws.amazon.com/signup?request_type=…`). Use `samsundar989@gmail.com` (or a `+aws` alias) as the root email. Account name suggestion: `riversight`.
2. When the sign-up asks **Free plan vs Paid plan: choose Paid plan.** You still get the $100 credit immediately and up to $100 more for "exploring key services" (6-month expiry). The Free plan cannot subscribe to fee-bearing Marketplace products (COOL) and only allows a few free-tier instance types — we need c8g Graviton.
   If you already created a Free-plan account: Billing and Cost Management console → the Free plan banner → **Upgrade to paid plan**. Credits carry over.
3. Enter a card (required for the Paid plan; Marketplace fees for COOL and some Bedrock usage are billed to it — credits generally do not cover Marketplace charges).
4. After sign-in as root: **turn on MFA for the root user** (IAM → My security credentials → MFA). Then stop using root.

## B. Admin user for the CLI/CDK (10 min)
5. IAM → Users → **Create user** `riversight-admin` → attach policy **AdministratorAccess** (hackathon scope; we tighten later in `infra/`).
6. Open the user → Security credentials → **Create access key** → "Command Line Interface" → download the CSV. Do **not** paste the keys into chat or any file in the repo.
7. On your Windows box: install **AWS CLI v2** (https://awscli.amazonaws.com/AWSCLIV2.msi), then in a terminal run `aws configure` → paste key + secret, region `us-east-1`, output `json`. Check: `aws sts get-caller-identity`.
8. Install CDK: `npm install -g aws-cdk` (Node is already there). Claude Code runs `cdk bootstrap` later.

## C. Guardrails (5 min)
9. Billing → **Budgets** → Create → Cost budget, monthly, amount **$150**, alerts at **$25, $50, $100** (actual) to your email.
10. Billing → Billing preferences → turn on **"Receive Free Tier usage alerts"** and PDF invoices by email.

## D. Bedrock model access (5 min, approval can take hours)
11. Console → **Amazon Bedrock** (us-east-1) → Model catalog / Model access → request access to **Anthropic Claude Haiku 5.5 and Claude Sonnet 5.5** (one-time Anthropic use-case form: company = personal/hackathon, use case = "agentic monitoring of public river cameras for flood safety; OpenCV AI Competition 2026 entry") and **Amazon Nova 2 Lite**.
12. Tell Cowork when it shows "Access granted". Claude Code then runs a 1-token test call.

## E. Quota increases (5 min; approvals take 1–3 days — do it tonight)
13. **Service Quotas** → Amazon EC2 → "Running On-Demand Standard (A, C, D, H, I, M, R, T, Z) instances" → request **32 vCPUs** (new accounts often start at ≤5).
14. Service Quotas → Amazon Bedrock → if "Tokens per minute / Requests per minute" for Claude Haiku 5.5 shows 0 or tiny, request the default values.

## F. COOL subscription (do on Oct 17–18, not tonight — the 7-day free trial starts when you subscribe)
15. AWS Marketplace → **Cloud-Optimized OpenCV Library (COOL) — Graviton4 AMI** (`https://aws.amazon.com/marketplace/pp/prodview-fdvbfiewzuehs`) → View purchase options → **Subscribe / Accept terms** (7-day trial, then ~$0.01/h software fee + EC2). Without accepting terms, launches fail with `OptInRequired`.
    Later, if we benchmark Graviton5 too: `prodview-igdweaoo6prb6`.

## G. Other accounts (5 min)
16. **USGS API key** (free, instant): https://api.waterdata.usgs.gov/signup/ → put it in the repo's `.env` as `USGS_API_KEY=…` (gitignored).
17. **OpenCV Slack**: https://join.slack.com/t/open-cv/shared_invite/zt-4bjbl3ub8-PwKoqVRJZnkvzRx4Y_9Axw → join **#opencvcomp26**.
18. **Devpost**: https://opencv26.devpost.com/ → "Start project" → title `RiverSight` (editable later), "Working solo". Opt into both special-award considerations when the form asks.

## What Claude Code will do once A–E are done
- `cdk bootstrap aws://<account>/us-east-1`; deploy `infra/` (VPC-less single c8g.large with the COOL AMI resolved from the Marketplace SSM alias, S3 buckets, DynamoDB table, EventBridge rule, SQS, CloudFront distribution with WAF rate rule, IAM roles with least privilege, CloudWatch dashboard, Budgets action to stop EC2 at $120).
- Expected monthly run-rate while live: **~$80** (EC2 c8g.large ~$58 + COOL ~$7 + CloudFront/S3/DynamoDB/Lambda ~$5 + Bedrock ~$5 + CloudWatch ~$3). Spot is not used for the judge endpoint.

## Known blockers to expect
- New-account Bedrock quotas can be 0 → the quota request in E14 fixes it; until then the agent uses a stub model and real OpenCV outputs.
- App Runner is closed to new customers; ECS Express Mode runs on Fargate where COOL isn't allowed → we use plain EC2 + ASG(1).
- If the console says "Your account is being verified" for hours, the pipeline still runs locally; nothing in slices 01–04 needs AWS.
