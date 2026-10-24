# Changes to frozen agent files after the final freeze (FROZEN.json)

`FROZEN.json` records exactly the code the final arms ran (`git_head`). These later edits to hashed files do not
change any decision and were made while (or after) the arms ran; they are listed so the hash mismatch is explained.

| when (UTC) | file | change | decision impact |
|---|---|---|---|
| 2026-10-24 02:40 | `src/riversight/agent/tools.py` (`render_wet_overlay`) | draw the wet overlay with W1's connected inundation (`SiteModel.wet_connected`, D-0011), same function as the dashboard slider | none: overlays are images attached to alerts; no tool result the agent reads changed except the overlay key / wet fraction text |
| 2026-10-24 03:05 | (resolved) | the overlay change above and the memory fix are included in the re-freeze of 2026-10-24; all final arms re-run under it | — |
