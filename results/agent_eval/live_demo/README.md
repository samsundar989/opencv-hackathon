# Live-stack demos (2026-10-23, us-east-2, https://d2aes2r6og8aap.cloudfront.net)

| demo | what was done | evidence |
|---|---|---|
| Kill switch | 21:07:42Z wrote `live/agent/ENABLED=false`; restored to `true` at 21:09:30Z | `kill_switch_decisions.jsonl`: Big Brook and Swan Creek decided `kill_switch` → NOOP within the running cycle |
| Daily token cap | 21:09:34Z set today's ledger (`live/agent/usage/2026-10-23.json`) to 1e9 tokens; restored to the original token count at 21:16:57Z (decision count kept) | `token_cap_decisions.jsonl`: two decisions at 21:15Z routed to the rules policy with "[daily token cap … reached: rules policy]" |
| Approval queue | a real flood: Animas gauge 8.38 ft vs the camera's calibrated max 4.57 ft; the agent drafted an alert with the live NWS forecast crest and two wet overlays | `approvals_pending_animas_2026-10-23.jpg` (pending item on /approvals). The approve/reject step needs the operator token, which only Samuel has; the round-trip screenshot follows his approval |

Note: Bedrock denied Claude 5.5 at the time (Q-0010), so live decisions were made by the rules fallback; the decision log records `fallback_reason` for each.
