# STATUS (newest first)

## 2026-10-13 23:xx UTC — bootstrap (Cowork)
- Repo bootstrapped by Cowork: rules (`CLAUDE.md`), plan, slice contracts, verified data clients, geometry core, classical vision core, 15 passing tests (run in a Linux container against `opencv-python-headless==5.0.0.93`; not yet run on Samuel's Windows box).
- GitHub private repo created: `samsundar989/opencv-hackathon` (empty; first push pending).
- Samuel's to-dos: `docs/AWS_SETUP.md` (AWS account tonight), USGS API key, Slack, Devpost project.
- Open questions: see `docs/HUMAN.md` Q-0001..Q-0003.
- Next: Claude Code runs `BOOTSTRAP_PROMPT.md` → SLICE_01 kill test by Oct 14 night.

### Checklist (Samuel)
- [ ] AWS account created on the **Paid plan** (or upgraded) — `docs/AWS_SETUP.md` A
- [ ] Root MFA; IAM user `riversight-admin`; `aws configure` done; `aws sts get-caller-identity` works — B
- [ ] Budget $150 with alerts — C
- [ ] Bedrock access requested (Claude Haiku 5.5 / Sonnet 5.5, Nova 2 Lite) — D
- [ ] EC2 vCPU quota request (32) — E
- [ ] USGS API key in `.env` — G16
- [ ] Slack #opencvcomp26 joined — G17
- [ ] Devpost project created — G18
- [ ] (Oct 17–18) COOL Graviton4 AMI subscribed — F
