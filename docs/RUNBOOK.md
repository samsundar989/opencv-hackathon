# RiverSight runbook

For whoever keeps the live site up through judging (Oct 27 – Nov 9). Everything is in **us-east-2**, profile `riversight`. Deployment itself: `docs/DEPLOY.md`.

```bash
export AWS_PROFILE=riversight AWS_REGION=us-east-2
aws sts get-caller-identity          # expired? → aws login --profile riversight
```
In Git Bash on Windows, prefix AWS CLI calls that take an `/aws/...` or `/...` name with `MSYS_NO_PATHCONV=1`.

## Is it healthy?

1. Open `/judge`: the status line says how long ago the last cycle ran.
2. `live/index.json` (behind CloudFront at `/live/index.json`): `cycle_started`, `n_ok`, `n_flagged`.
3. CloudWatch dashboard `riversight`; alarms `riversight-no-cycle-75min` and `riversight-cycle-errors` e-mail the operator through SNS `riversight-alerts`.
4. `/proof`: which instance, AMI and OpenCV build produced the readings.

At night most sites show "night (gauge only)" with the last daylight frame. That is normal, not an outage.

## The worker stopped producing cycles

Alarm `riversight-no-cycle-75min`, or `/judge` says the last cycle is old.

1. **Is the instance running?**
   ```bash
   aws ec2 describe-instances --filters Name=tag:Project,Values=riversight Name=instance-state-name,Values=running,stopped \
     --query "Reservations[].Instances[].[InstanceId,State.Name,InstanceType,Tags[?Key=='Name'].Value|[0]]" --output table
   ```
   - **Stopped:** first check whether the **budget guard** stopped it (spend reached 90 % of the $100 cap; there will be a budget e-mail). If so, **do not restart it**. Spending more needs Samuel's explicit OK (D-0004). Otherwise, start it: `aws ec2 start-instances --instance-ids <id>`.
   - **Running:** go on.
2. **Shell in (no SSH; SSM only):** `aws ssm start-session --target <WorkerInstanceId>`
3. **Look at the last cycle:** `journalctl -u riversight-cycle -n 200 --no-pager`; `systemctl list-timers riversight-cycle.timer`.
   - **Killed for memory:** the unit has `MemoryMax=80%`. ALIKED + LightGlue need about 1.5 GB on arm64 (W1 status). The agent's tools run in a short-lived subprocess with a rules fallback, so a crash there should not kill the cycle. Keep m9g.large; don't go below 8 GB.
   - **Code error after a deploy:** redeploy the last good commit's code: `git checkout <good-sha> && python scripts/deploy.py --code-only`.
4. **Run one cycle by hand:** `sudo systemctl start riversight-cycle.service`, then watch `journalctl -fu riversight-cycle`.
5. **Instance broken beyond repair:** `python scripts/deploy.py` (full deploy) replaces it from the bootstrap. The COOL root volume must be ≥ 80 GB.

## USGS is down or slow

- **Frames (NIMS) missing:** sites keep their last daylight frame with a "stale" banner, and the gauge-only reading continues. Nothing to do. Do not raise request rates; the fetchers already back off on 429/5xx.
- **Gauge (NWIS/OGC) missing:** readings get `GAUGE_STALE`. The agent marks camera readings **provisional** (gap-fill), which is the product working as intended. If the whole USGS API is down for hours, note it on `/judge` so judges don't read it as our outage.
- **OGC API key quota exhausted (1,000 requests/h):** the code falls back to legacy NWIS IV (D-0005a: identical values).

## Bedrock is throttling or denying

- **Automatic:** any Bedrock error, timeout or the daily token cap → the deterministic rules policy decides (`decided_by: "rules"` in `live/agent/YYYY-MM-DD.jsonl`). Nothing breaks.
- **AccessDenied** on a model that worked before: check the model agreements in the Bedrock console (Q-0010), then whether the project hit a spend limit (AWS Settings → Billing).
- **To stop LLM spend immediately** (kill switch; every decision becomes a logged NOOP):
  ```bash
  echo false | aws s3 cp - s3://<bucket>/live/agent/ENABLED
  echo true  | aws s3 cp - s3://<bucket>/live/agent/ENABLED      # re-enable
  ```

## A camera misbehaves

- **Moved, fogged or re-aimed:** the cycle flags `VIEW_CHANGE` or `LOW_QUALITY`; the agent re-anchors to a banked reference or quarantines and opens a ticket. A quarantine lifts itself after 3 consecutive good cycles (D-0009 W1-6).
- **Permanent new view:** it needs recalibration from new history. Re-export that site's bundle (`python scripts/export_site_models.py --only <cam>`, local data cache required) and `python scripts/deploy.py --code-only`. Until then it stays quarantined. That is the honest state.
- **Above the calibrated range:** shown as "≥ X ft (above calibrated range)", with the gauge trusted. Not a bug (report §6.6).

## Approvals and alerts

- Pending items: `/approvals` (token required). The token reached the operator once by e-mail and is kept only in the operator's gitignored `.env` as `APPROVAL_TOKEN`. Never paste it into chat, issues or commits.
- SNS e-mails arrive only after the subscriptions to `riversight-alerts` and `riversight-stop` are confirmed (D-0011).

## Cost check

- AWS Settings → Billing, or the budget `riversight-cap` in the Billing console. Actual spend is also on `/proof`.
- The COOL benchmark instance (`bench/run_cool_bench.py`) terminates itself. If one is left over: `python bench/run_cool_bench.py --bucket <bucket> --collect --run <run> --ami <ami> --cool-price <fee>` terminates it and fetches its results.

## Tear-down (after Nov 9 only; the stack stays up through judging)

```bash
cd infra
cdk destroy RiverSightLive --profile riversight     # the S3 bucket is retained: empty and delete it by hand
cdk destroy RiverSightGuard --profile riversight    # last, so the budget guard outlives everything that costs money
aws iam remove-role-from-instance-profile --instance-profile-name riversight-cool-bench --role-name riversight-cool-bench
aws iam delete-instance-profile --instance-profile-name riversight-cool-bench
aws iam delete-role-policy --role-name riversight-cool-bench --policy-name bench-s3
aws iam delete-role --role-name riversight-cool-bench
```
Then check us-east-2 (and us-east-1 for CloudWatch Logs and WAF) for anything left, and cancel the COOL Marketplace subscription.
