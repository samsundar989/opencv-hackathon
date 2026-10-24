"""SPRINT W5: one-command onboarding of new HIVIS cameras (frozen D-0007 setting, no per-site tuning) and the
real gauge-outage catalogue. See docs/slices/SPRINT_W5_FLEET_ONBOARDING.md and D-0010 §3."""
from datetime import datetime, timezone

# Onboarding / outage-scan window: the 12 months before the day the W5 sprint started (Oct 23 00Z).
W_END = datetime(2026, 10, 23, tzinfo=timezone.utc)
W_START = datetime(2025, 10, 23, tzinfo=timezone.utc)
