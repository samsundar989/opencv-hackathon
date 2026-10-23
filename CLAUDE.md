# RiverSight — Claude Code operating rules

RiverSight is our entry in the **OpenCV AI Competition 2026 (powered by AWS)**. Deadline **Sun Oct 25 (our internal) / Mon Oct 26, 11:45 pm PDT (hard)**. Goal: **win 1st overall** (+ Best Use of COOL and Agentic Vision if cheap). Read `docs/PLAN_2026-10-13_RIVERSIGHT.md` first, then the active slice in `docs/slices/`.

## What we are building (one paragraph)
USGS HIVIS river webcams that sit next to a USGS stream gauge become calibrated water-level instruments, with no staff plate or survey. Each daylight frame is registered to a per-site reference (OpenCV 5 ALIKED + LightGlue + USAC_MAGSAC, ORB first) and warped into it. A **scene model** (D-0006, setting frozen in D-0007) turns per-block Lab/Sobel features into stage ± σ: a **flood-height map** (the stage at which each 4 px block floods, learned from the gauge's history) picks the reliable blocks, then kernel ridge and a causal Kalman filter. Transects and the seg net are off the critical path. The 20-site kill test v2 passed on frozen test days read once (`results/kill_test_v2.md`). The product claim is **gauge-outage gap-fill, flood state, camera QA and "what's under water at stage X"**, not live gauge replacement (the camera never beats 15-minute persistence). A **live fleet** of the 20 cameras cycles every 30 min on a Graviton worker running **COOL** (benchmarked honestly against pip OpenCV 5.0.0.93). **River Steward**, a Bedrock Converse tool-use agent with a deterministic rules fallback, handles flagged readings: re-anchor or quarantine on view change, provisional gap-fill on gauge outage, camera-fault vs gauge-suspect tickets on disagreement, and on a rise densify sampling, render the wet overlay at the NWS forecast crest and draft an alert that a human approves (S3 + Lambda URL, no Step Functions). Sprint plan: `docs/PLAN_2026-10-22_FINAL_SPRINT.md`; interfaces: `docs/INTERFACES.md`.

## Non-negotiables
1. **Pin `opencv-python-headless==5.0.0.93`.** Never float it (5.1 renames DNN engine enums). Never hard-code engine enum integers; use `cv2.dnn.ENGINE_*` names and guard with `hasattr`.
2. **OpenCV 5 must do load-bearing work.** Keep `docs/OPENCV5_USAGE.md` current: every `cv2` call that matters → what it does → what breaks without it. Judges score "depth of OpenCV 5 use" (30 pts).
3. **Never fabricate or round numbers upward.** Every metric in docs comes from a committed results file produced by a committed script. Frozen constants are hashed before any held-out read (`results/constants.sha256`); the held-out set is read once.
4. **Real data only for claims.** Synthetic/fault-injected data is fine for agent tests, labeled as such.
5. **No secrets in the repo.** AWS creds live in `aws configure`; API keys in `.env` (gitignored). Never print secrets.
6. **Respect the data sources.** Be gentle with USGS APIs (≤4 concurrent requests, exponential backoff on 429/5xx, cache everything under `data/raw/`, never re-download what's cached). Get a free USGS API key (`.env: USGS_API_KEY`) and pass it as `api_key=`.
7. **Privacy:** blur faces/plates (YuNet) before any frame leaves the pipeline to an LLM or dashboard. Don't redistribute raw images; the public benchmark is a manifest (image URLs + labels + splits).
8. **Ask, don't guess, on anything irreversible or costly** (AWS spend > $20 per action, deleting data, external messages). Write questions to `docs/HUMAN.md` as `## Q-NNNN` and continue with other work; Samuel answers with `## ANSWER NNNN`.

## Environment (Samuel's Windows box, `sam-mega-pc`)
- Use the **globally installed, latest Python** (Samuel's instruction). `python --version` should be ≥3.12. Install with `pip install -e ".[dev]"`. Only if a dependency conflict appears, create `.venv` with `uv venv` and say so in `docs/STATUS.md`.
- GPU: **RTX 5090** (Blackwell, sm_120). Heavy jobs (SAM2 pseudo-labeling, segmentation training, large batch inference) go through **workerq** — read its docs at `C:\Users\samsu\Documents\gpu-queue` before the first GPU job and record the submit command in `docs/DECISIONS.md`. Light CPU work runs directly.
- **RunPod** credits exist but are limited and shared: use only when the 5090 is busy/insufficient, and log the spend in `docs/STATUS.md`.
- Kaggle GPU quota is a further fallback.
- OpenCV 5's new DNN engine is CPU-only. Train in PyTorch on the GPU → export ONNX → run in `cv2.dnn` (that is the product path on Graviton). Diff every ONNX model against onnxruntime before trusting cv2.dnn output.
- AWS region: **us-east-2** (the project's assigned Region, new AWS experience — Regional resources can't be created elsewhere; see D-0003). Credentials via `aws login --profile riversight` (browser sign-in, 12 h sessions renewable for 90 days); pass `--profile riversight` or set `AWS_PROFILE=riversight`. Never commit `cdk.out` secrets.

## Repo layout
```
CLAUDE.md                  this file
docs/PLAN_*.md             master plan (Cowork writes; Claude Code executes)
docs/slices/SLICE_NN_*.md  slice contracts: scope, acceptance, deliverables
docs/STATUS.md             running status (Claude Code updates after every work session)
docs/DECISIONS.md          numbered rulings (D-NNNN); append-only
docs/HUMAN.md              questions for Samuel (Q-NNNN) and his answers
docs/research/             competition research (judges, rivals, OpenCV 5, AWS/COOL, prior art)
src/riversight/            package
scripts/                   CLIs (fetch, kill test, eval, bench)
tests/                     pytest
data/                      gitignored; raw/ cache, derived/ parquet, sites/ configs
results/                   committed: eval CSV/JSON, constants hashes, benchmark outputs
infra/                     CDK (Python)
web/                       dashboard SPA
```

## Working loop
- Work slice by slice. Before starting a slice, re-read its contract; when done, mark acceptance items with evidence (file paths, numbers) in `docs/STATUS.md`, commit, push.
- Commit small and often to `main` (solo repo); message prefix `[SNN]` for the slice.
- Tests: `pytest -q` must pass before every push. Add a test with every bug fix.
- Keep a `make`/`invoke`-style entry point: `python -m riversight.cli <cmd>`.
- When a slice's acceptance can't be met, don't quietly lower the bar — write the shortfall in `docs/STATUS.md` and a `Q-` in `docs/HUMAN.md`.

## Competition facts you must not get wrong
- Deadline Oct 26, 11:45 pm PDT (Devpost). Judging Oct 27–Nov 9: the endpoint must stay up. Winners Nov 10.
- Overall rubric: Technical 30 · Innovation 20 · Impact 20 · UX 10 · Docs 10 · Cloud/responsible 10. Specials: COOL $1k, Agentic Vision $1k.
- Required package: technical report, judge-accessible repo, pinned deps + build/deploy/test instructions, architecture diagram, working web endpoint, ≤5-min video showing the team, evaluation evidence incl. failure cases.
- Prior art exists (OTT HydroSight, Tenevia, Eltner 2026, Xu & Wang 2025, USGS RISE dataset, Stevens/CIROH). Our claim is narrow and true: first open, fleet-wide, survey-free, self-calibrating system + first held-out-site benchmark + live endpoint + agentic QA. See `docs/research/prior-art.md`.

<!-- BEGIN AWS Agent Toolkit rules -->
# AWS Guidance for the new AWS experience

This user has signed up for the new AWS experience. This experience lets you sign into AWS using a social provider and requires the following additional context.

Where this guidance conflicts with the project's own instructions, the project's instructions take precedence.

## Context

### Terminology:

- Say "project" instead of "account" â€” a project contains an AWS account and settings for sharing with other collaborators
- Say "team member" instead of "IAM user" â€” users are invited by email, not created or federated in IAM
- Say "AWS Settings" when referring to management tasks at [settings.aws.com](https://settings.aws.com/) (project management, billing, team members, spend limits). Users view their actual AWS resources in the AWS Management Console.
- Say "selected Region" when referring to the user's Region â€” not "home Region"
- The user has a managed IAM experience. This includes a managed service control policies (SCP) and resource control policies (RCP) that govern the use of AWS. They will still need to use IAM to create policies to let services work with each other. If there are questions about the SCPs or RCPs, go to the documentation at https://docs.aws.amazon.com/accounts/latest/reference/scps-and-rcps-for-projects.html

### Constraints:

- All projects share a single AWS Region determined by the user's contact address. Resources cannot be created in other Regions
- When developing:
  - MUST create all Regional resources in the project's assigned Region
  - You CAN create AWS WAF and Cloudwatch Logs resources in us-east-1 when there are global resources (like a global WAF instance) that require a connection to dependencies in us-east-1. You should not use these for any other reason, because resources in the selected Region will provide lower cost (due to no cross-Region traffic), increased availability (due to no cross-Region traffic), and easier manageability (due to not needing to look in another Region). When you need to do an inventory of resources, you need to look in both the selected Region and us-east-1 for Cloudwatch Logs or WAF resources.
  - MUST NOT attempt to create Lambda, API Gateway, or other Regional resources in any other Region
  - MUST direct users to confirm their Region in AWS Settings > View all projects > Overview > Additional Info > Region. If the user cannot confirm their Region, check in ~/.aws/config
  - MUST NOT use Lambda@Edge â€” excluded from both Lambda and CloudFront
  - MUST NOT use CloudFormation StackSets â€” no multi-account or multi-Region deployments
  - MUST NOT attempt cross-Region actions â€” no cross-Region replication for DynamoDB/S3/RDS, no multi-Region KMS keys
  - MUST NOT use Route 53 cross-Region routing â€” geolocation, latency-based, and failover routing policies are not available
  - CloudFront is a global service and its actions ARE allowed in `us-east-1`. A user can create a CloudFront distribution pointing to their project-region Lambda function URL or API Gateway. However, Lambda and API Gateway themselves MUST NOT be created in `us-east-1` â€” they must be in the project Region.
  - Reduced availability in `eu-north-1` specifically: Amazon Rekognition, Amazon Textract, Amazon Personalize, AWS App Runner are not available in that Region.
- IAM permissions for human access are managed by AWS. Don't assign roles to team members unless absolutely necessary
- The user may have a spend limit if they are on the paid plan. The limit that pauses their project if it's exceeded. If resources suddenly become inaccessible, ask if they have a spend limit configured. Only project owners can modify a spend limit.
- When developing:
  - MUST ask about spend limit status if the user reports sudden "Access Denied" errors on operations that previously worked
  - MUST direct users to check spend status in AWS Settings > Billing
  - MUST check if a user has upgraded their account to the paid plan
  - MUST ask the user if they want to clean up the successfully created resources or keep them to reduce cost
- The user sets up billing, creates spend limits, and retrieves and pays invoices in AWS Settings. The user creates budgets and optimizes their costs in the AWS Billing and Cost Management console
- Not all AWS services are available. If a service isn't working, do the following:
  1. Run the command `aws freetier get-account-plan-state`
  2. If accountPlanType": "FREE", check the [Free Tier supported services list](https://docs.aws.amazon.com/accounts/latest/reference/supported-services-sign-up-new.html#supported-services-free-tier) next,
  3. If accountPlanType": "PAID", check the [Paid Tier supported services list](https://docs.aws.amazon.com/accounts/latest/reference/supported-services-sign-up-new.html#supported-services-paid-plan).
  4. If neither list shows the service, check the [Not supported for this experience list](https://docs.aws.amazon.com/accounts/latest/reference/supported-services-sign-up-new.html#unsupported-services). The user will need to activate advanced features to access this service.
- Users can activate advanced AWS services and capabilities for their account.
- Before starting a task, check whether a relevant AWS skill is available. Load the skill with retrieve_skill and prefer its guidance over general knowledge.

### Help level

- help_level (required): LOW, MEDIUM, or HIGH. While a user is building, you MUST ask the user: "How much guidance would you like from me? Low (I only flag security risks), medium (I ask a couple of clarifying questions if something seems off), or high (I explain what I'm doing, suggest alternatives, and flag best practices)."

You CAN update this rule file to save a user's help_level.

Constraints for each level:

**LOW:**

- MUST follow all constraints in this context file
- MUST execute the userâ€™s request without modification
- MUST NOT ask clarifying questions unless the action would create a security vulnerability
- MUST NOT suggest alternatives or improvements

**MEDIUM:**

- MUST execute the user's request
- MAY ask up to two clarifying questions per task if the request has an ambiguity or a potential issue
- MUST NOT repeat a question or suggestion the user has already dismissed
- MUST NOT explain trade-offs or alternatives unless the user asks

**HIGH:**

- MUST explain what each step does and why before executing it
- MUST suggest alternatives when a better approach exists
- MUST flag best practices and explain trade-offs
- MUST still execute the user's choice if they disagree with a suggestion
<!-- END AWS Agent Toolkit rules -->
