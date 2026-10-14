# D — AWS architecture brief for a solo entrant (researched 2026-10-10)

## 0. Findings that change the plan
1. **Only three COOL SKUs are OpenCV 5:** the Graviton4 AMI (COOL 3.1 = OpenCV 5.0), the Graviton5 AMI (5.1.0 + KleidiCV 0.7.0) and the Graviton4 Docker image (5.1.0). The Graviton2/3 AMIs (v1.3/v2.0) don't state an OpenCV 5 base, so avoid them.
2. **Stock OpenCV already has KleidiCV.** It has been on by default for Linux aarch64 since 4.13 (5.x CMake: `WITH_KLEIDICV` ON for AArch64 UNIX). COOL's claims (~20% average, up to 70%, 1.2–1.8x) were measured against pip **4.12**, so gains over `opencv-python==5.0.0.93` should be far smaller. That fits competitor results (0.94x on c8g.medium, 1.26x on 2xlarge). A three-arm A/B is our edge. *[wheel contents inferred — check `getBuildInformation()` on day 1]*
3. **COOL's fee sets a break-even speedup.** The c8g.large fee is $0.01/h against $0.0798/h EC2, so COOL must be ≥1.125x faster end to end to lower $/frame (≥1.063x on xlarge). Docker costs $0.03 per container-hour, needing ≥1.38x on c8g.large.
4. **Account blockers:**
   - The Free plan allows only free-tier EC2 types (t3/t4g micro/small, c7i/m7i-flex.large) and no fee-bearing Marketplace offers. Upgrade to Paid now; credits carry over.
   - Credits exclude Marketplace, so COOL fees and Claude on Bedrock are paid by card. Nova, EC2 and AgentCore are credit-eligible *[inferred]*.
   - New accounts often get Bedrock quotas of 0 ("Too many tokens per day"), EC2 vCPU limits as low as 1, and a GPU quota of 0.
5. **App Runner is closed to new customers** (since Apr 30, 2026). AWS points to ECS Express Mode, which runs on Fargate, so no COOL there.
6. **AgentCore is fully GA**, including Policy (Cedar rules on tool calls; Mar 3) and Evaluations (Goal Success, Tool Selection/Parameter Accuracy, trajectory match, Lambda evaluators; Mar 31). Runtime is **arm64-only**; Harness is still preview.
7. **The CloudFront flat-rate Free plan costs $0.** It includes 1M requests and 100 GB a month, WAF with IP rate limiting, OAC and signed URLs, with no overage charges. That makes it the judge front door.

## 1. COOL facts
| SKU | Version / OpenCV | Runs on | Fee/h | Notes |
|---|---|---|---|---|
| G4 AMI `prodview-fdvbfiewzuehs` | 3.1 / 5.0 | c8g/m8g/r8g | large/xl $0.01, 2xl $0.02 | Py3.10–3.12; C++ `cmake/opencv4` (sic) |
| G5 AMI `prodview-igdweaoo6prb6` | 5-1.0 / 5.1.0 | c9g/m9g (us-east-1/2, us-west-2, eu-central-1+) | m9g.medium $0.002, large $0.005 | Py3.12–3.14; FFmpeg; IMDS license check — snapshot-derived images fail |
| G4 Docker `prodview-fsbcuniykfunw` | 1.0-py312-cpp_sdk / 5.1.0 | ECS/EKS on Graviton4 EC2 | $0.03/container-h | task role `RegisterUsage` (EKS: IRSA); metering egress or exit 133; no Fargate |
| G3 `prodview-5b2boxpyztidw` / G2 `prodview-jz6w32bsfv6sg` | 2.0 / 1.3, version unstated | c7g / c6g | $0.01+ | 4.12 baseline |

- **Common to all:** Ubuntu 24.04; `source /opt/cool/venvs/python_3.12/bin/activate`; C++ SDK at `/opt/cool/cpp_sdk`; 7-day trial per product that converts automatically, with no refunds.
- **5.1.0 isn't a public release** (GitHub's latest is 5.0.0, Jun 6), so it's likely a 5.x-branch build *[inferred]*.
- **Where COOL runs:** EC2 and ECS/EKS on EC2 only. Not Lambda, Fargate or AgentCore. Batch is possible *[unverified]*.
- **Vendor claims** (vs pip 4.12, method undisclosed, 78 functions):
  - Named winners: resize, Gaussian adaptiveThreshold, findContours, cvtColor, CLAHE.
  - The "Mars" workflow ran at 1.2→1.6 fps on Graviton4 (AWS blog, Apr 9).
  - KleidiCV also covers remap, warpPerspective, rotate, blurs, YUV and LK flow.
  - No DNN claim.
  - The promised benchmark tool (opencv.org/COOL) doesn't exist yet.
- **Gotcha:** dependencies that pull `opencv-python` shadow COOL's cv2. Install with `--no-deps` and assert at startup that `cv2.__file__` starts with `/opt/cool`.
- **Use the G4 AMI as the primary arm,** since its OpenCV 5.0 matches the pip baseline with no version confound. Use G5 as a generational data point.

## 2. Unimpeachable A/B ("COOL-AB-v1")
- **Same c8g instance, separate Python 3.12 venvs, same NumPy:**
  - A = COOL
  - B1 = `opencv-python-headless==5.0.0.93`
  - B2 = `4.12.0.88` (the vendor's baseline)
  - Optional B3 = OpenCV 5.0 built from source with `-mcpu=neoverse-v2` (separates compiler effects)
  - Optional C = c7i.large on the stock wheel
  - Clear `PYTHONPATH`/`LD_LIBRARY_PATH` for the B arms.
- **Proof per arm:** version, `cv2.__file__`, full `getBuildInformation()` (Custom HAL, SVE baseline), `ldd`, `lscpu`, and the signed IMDS identity document.
- **Thread regimes:** one thread pinned with `taskset`; `setNumThreads(nproc)`; and nproc processes × 1 thread.
- **Inputs:** a licensed fixed frame set at VGA, 720p, 1080p and 4K, with preallocated `dst`. Prove output equivalence (max diff or PSNR).
- **Timing:**
  - 50 warmup iterations, discarded.
  - ≥300 iterations or ≥5 s per function and size.
  - Randomized, interleaved arms over ≥5 rounds on ≥3 fresh instances.
  - Report p50/p95/p99, fps, a bootstrap 95% CI on speedup, CPU utilization and RSS.
- **Scope:** the COOL-named functions plus our end-to-end pipeline, with an Amdahl breakdown.
- **Cost:** $/1k frames = 1000 × (EC2 + COOL $/h) / (3600 × aggregate fps), on-demand and spot, against the break-even line. Publish CSVs, scripts, lockfiles and slowdowns.

## 3. Agent stack (us-east-1)
Image tokens = ⌈w/28⌉×⌈h/28⌉ (720p = 1,196). One decision = one 720p frame + 1.5k prompt + 300 output tokens. Bedrock prices are assumed equal to Anthropic's list (geo endpoints may add ~10%).

| Model | $/1M in/out | Per decision |
|---|---|---|
| Claude Haiku 5.5 (on Bedrock since Oct 7) | 0.10/0.50 (≤100K prompt) | ~$0.0004 |
| Claude Sonnet 5.5 / Opus 5.5 | 2/10 · 4/20 | ~$0.008 / $0.017 |
| Nova 2 Lite (image and video; credit-eligible) | ~0.30/2.50 *[3rd-party price]* | ~$0.002 |

- **Model access:** a one-time Anthropic first-use form (can sit pending); the first call auto-subscribes through Marketplace (needs a payment method); quotas depend on account age.
- **AgentCore pricing:**
  - Runtime: $0.0895/vCPU-h + $0.00945/GB-h; I/O wait is free; ~2 s cold starts on the new runtime (Sep 18).
  - Gateway: $0.005 per 1k calls.
  - Policy: $0.000025 per request.
  - Evaluations: $0.0024/$0.012 per 1k tokens.
  - Observability is billed at CloudWatch rates.
- **Strands 1.59.0:** MCP client, graph/swarm, OTEL, and **interrupts** (pause before a tool call for human approval, then resume).
- **Step Functions** ($0.025 per 1k transitions): `.waitForTaskToken` with Heartbeat and Catch(Rejected/Timeout) gives auditable approvals.
- **Recommended combination:**
  - Step Functions as the durable outer loop.
  - A Strands agent on AgentCore Runtime using Haiku 5.5, falling back to Nova 2 Lite on 429s.
  - Gateway MCP tools: a COOL OpenCV MCP server (novel — no official one exists), Lambda tools and action tools.
  - Cedar policies as the "autonomy dial".
  - Observability traces and Evaluations scores as evidence.

## 4. Live camera → cloud (1 camera)
| Path | Cost |
|---|---|
| Script or browser → S3 presigned keyframes → EventBridge (cheapest) | ≈$0 |
| Greengrass v2 on a Pi 5: OpenCV 5 edge gating, MQTT + S3 ("Arm edge + Arm cloud") | $0.16 per core-month (3 free); IoT $1/M messages |
| Kinesis Video Streams → COOL consumer via HLS `cv2.VideoCapture` or GetImages | $0.0085/GB ingest; 2 Mbps 24/7 ≈ $13/mo |
| API Gateway WebSocket for pushing results | $1/M messages |

## 5. Judge endpoint options (30 days)
| Option | COOL | $/mo | Note |
|---|---|---|---|
| EC2 c8g.large on the G4 AMI behind CloudFront | ✔ | ≈71 | core worker; no cold start |
| m9g.medium on the G5 AMI | ✔ | ≈43 | cheapest; 1 vCPU |
| ECS on EC2 c8g.large + COOL Docker | ✔ | ≈85 (+ALB 18) | use bridge networking; awsvpc needs NAT ($32+) |
| Lambda arm64 + headless 5.0.0.93 | ✘ | 0–5 | 1–3 s cold start *[est.]*; provisioned concurrency ≈ $8.6 or a warm-up ping |
| ECS Express Mode (Fargate) | ✘ | ≈30 | fallback |
| App Runner | – | – | closed to new customers |
| S3 SPA + CloudFront Free plan | – | 0 | front end |

**Abuse and cost protection:**
- WAF rate rule of 300 requests per 5 min per IP.
- Public "replay mode"; "live mode" behind Cognito (free tier) or signed cookies, with judge credentials in Devpost's testing notes.
- Origin security group limited to CloudFront's prefix list.
- Daily token budget in DynamoDB, falling back to replay.
- Reserved concurrency, upload size caps, and 7-day expiry on uploads.
- Budgets alerts at $25/$50/$100 plus an action that denies `bedrock:Invoke*` and stops EC2.
- Public voting (Oct 26–Nov 9) may bring traffic spikes.

## 6. Hybrid GPU + Graviton
- **Pipeline:** train on the RTX 5090 → ONNX → validate OpenCV 5 DNN `ENGINE_NEW` on aarch64 (with a CLASSIC fallback) → serve on Graviton, with COOL doing pre- and post-processing.
- **Use g6.xlarge ($0.805/h) only if quota is granted.**
- **Cost reporting:** camera-month = (P_ec2 + P_cool) × 720 × f_cam/F + f_cam × 2.592M × r_esc × c_VLM.
- **Illustration (F = 60 fps is hypothetical):** $1.08 per camera-month at 1 fps, while 0.5% Haiku escalations add ~$5. OpenCV gating is the cost lever, so measure it.

## 7. IaC, observability, security
- **CDK (Python):** the aws-cdk-lib `aws_bedrockagentcore` L2 constructs (Runtime, Gateway with `addMcpServerTarget`, Memory, PolicyEngine, OnlineEvaluation). Launch EC2 from the Marketplace AMI alias `resolve:ssm:/aws/service/marketplace/prod-…/<version>`, pinned to a version. Pin image digests, use a uv lock, a Makefile and GitHub OIDC, and commit a `cdk-nag` report.
- **Observability:** use ADOT/OpenTelemetry; the X-Ray SDKs have been in maintenance since Feb 25, 2026. Turn on Transaction Search. Add a metric dimension `backend=cool|stock`. Share the CloudWatch dashboard with up to 5 judge emails or a public link (free).
- **Security:** least-privilege roles, IMDSv2, S3 Block Public Access + OAC, Secrets Manager, OpenCV face blur before any VLM call, CloudTrail.
- **What a judge can check in 5 minutes:**
  - The live URL.
  - A `/proof` endpoint showing the signed identity document (`marketplaceProductCodes`, imageId, instanceType) and a hash of the build info.
  - The trace viewer.
  - The dashboard.
  - The eval and benchmark CSVs and the IAM policy JSON.

## 8. Day-1 actions
1. Upgrade to the Paid plan and choose us-east-1.
2. Submit the Anthropic form and test Haiku 5.5 and Nova 2 Lite.
3. Request quota increases: EC2 vCPU (≥32), Bedrock TPM/TPD and Lambda concurrency.
4. Set up budgets.
5. Subscribe to the G4 AMI once the benchmark harness is ready (7-day trial).
6. If you have an older AWS account, use it instead.

## 9. Reference architecture
```
MINIMAL (~$80/mo)
Judge ─► CloudFront Free(+WAF,OAC) ─┬─► S3 SPA (replay mode)
                                    └─► EC2 c8g.large, COOL G4 AMI, ASG=1
Camera script/webcam ─► S3 keyframes ─► EventBridge ─► COOL worker:
   FastAPI + Strands agent (in-proc MCP tools = COOL OpenCV fns)
   ─► Haiku 5.5 ─► risky? ─► Step Functions taskToken ─► SNS/UI approve ─► act
ADOT ─► CloudWatch + shared dashboard; Budgets/WAF/token caps

SHOWCASE (~$180–220/mo)
Camera ─(Greengrass edge gating)─► KVS + S3 + MQTT ─► EventBridge
 ─► Step Functions: Perceive [ECS c8g, COOL Docker] ─► Agent [AgentCore Runtime, Strands, Haiku↘Nova]
      ⇄ Gateway (MCP + Cedar) ─► {COOL OpenCV MCP | Lambda stock-OpenCV | action tools}
    ─► Choice(risk) ─► waitForTaskToken ─► Act ─► Re-perceive ─► Evaluations
 Judge: CloudFront ─► S3 SPA + Cognito ─► Lambda URL; WebSocket push
 Bench: CDK-launched COOL spot runs ─► S3 CSV
```

## 10. Cost table (30 days, estimates)
| Item | Minimal | Showcase |
|---|---|---|
| CloudFront/WAF/S3 | 0 | 15 |
| COOL compute | 71 | 100 |
| Lambda/API | 0–2 | 5–10 |
| AgentCore | – | 20–30 |
| Bedrock (paid by card) | 2–5 | 15–30 |
| Step Functions/EventBridge/SNS | 1–2 | 3 |
| Ingestion | 0 | 14 |
| CloudWatch | 3 | 8–10 |
| **Total** | **≈80** | **≈180–220** |

## 11. COOL evidence checklist
- ☐ Listing, version and OpenCV version; subscription screenshot; region; AMI alias.
- ☐ Instance type, `lscpu`, and the signed identity document with `marketplaceProductCodes`.
- ☐ Both arms' `cv2.__file__` and build-info committed; live `/proof` endpoint.
- ☐ A per-request `cv_backend` header and metric, proving the core workload runs on COOL.
- ☐ Docker variant: task role with the `RegisterUsage` policy, image digest, exit code 0, CloudTrail `RegisterUsage` event.
- ☐ Three-arm benchmark: CIs, thread regimes, CPU utilization, $/1k frames, break-even; one-command repro; slowdowns reported.
- ☐ Bill line item for COOL hours.

## 12. Agentic evidence checklist
- ☐ Workflow diagram showing human gates and autonomy levels.
- ☐ MCP tool catalog split into read-only and side-effecting tools, the Cedar policies, and a trace of a denied call.
- ☐ ≥3 traces where an OpenCV metric changed the next tool call, each with its counterfactual.
- ☐ Eval:
  - ≥50 labeled episodes.
  - Metrics: success, steps, false-action rate, escalation rate, p50/p95 latency, $/episode.
  - Baselines: fixed pipeline and VLM-only agent vs agent + OpenCV tools.
  - AgentCore Evaluations results plus a code-based evaluator.
- ☐ Fault injection (timeout, corrupt frame, 429 → fallback, low confidence → human), with retries and a dead-letter queue.
- ☐ Observability: shared dashboard, episode IDs, alarms.
- ☐ Security: least-privilege IAM, Cognito/JWT, no long-lived keys, and text found inside images treated as data rather than instructions.
- ☐ Human control: approval inbox, a default action on timeout, override, kill switch and audit log, all shown in the video.

**Sources:**
- AWS Marketplace listings above
- aws.amazon.com/blogs/spatial/accelerating-opencv-on-graviton-the-cool-framework
- Arm's KleidiCV 26.03 blog
- opencv/opencv 5.x CMakeLists.txt
- pypi.org/project/opencv-python
- platform.claude.com pricing/vision docs
- Bedrock docs: model-access, Haiku 5.5 and Nova 2 Lite model cards, quotas
- AgentCore pricing page and Policy/Evaluations GA notes
- strandsagents.com interrupts
- AWS docs and pricing pages: Step Functions, Kinesis Video Streams, Greengrass, IoT, API Gateway, Lambda, WAF, CloudFront flat-rate, App Runner availability, Free plan
- re:Post threads on Bedrock quotas
- X-Ray end-of-support notice
- CloudWatch dashboard sharing
- EC2 instance identity documents
- Marketplace AMI aliases
- RegisterUsage docs
- instances.vantage.sh prices
