"""Camera type for the fleet-scale report (D-0013 W5-1: '% qualifying by camera type').

Assigned from the NIMS camera id, state and latitude only (no image or result is looked at), first match wins:
  tidal_coastal   name says slough / bay / harbor / estuary / sound / dock / marsh / lagoon / tidal (tidal water or a
                  Great Lakes bay: coastal water levels either way)
  not_a_river     edge-of-field research installations (bioreactor / tile-drain inlets); never onboarded
  small_stream    creek / ck / branch / brook / run / kill / fork / bayou
  cold_climate    Alaska, or latitude ≥ 44.5° N
  large_river     everything else
"""
from __future__ import annotations

import re

TIDAL = re.compile(r"(Slough|_Bay(_|$)|_Harbou?r(_|$)|Estuary|_Sound(_|$)|_Dock(_|$)|_Marsh(_|$)|Lagoon|Intracoastal|Tidal)", re.I)
SMALL = re.compile(r"(Creek|_Ck(_|$)|Branch|_Br_|Brook|_Run(_|$)|_Kill(_|$)|_Fk_|Fork|Bayou)", re.I)
RIVER = re.compile(r"(River|_Rv(r)?(_|$)|_R_)", re.I)               # "West Branch Susquehanna River" is not a creek
NOT_A_RIVER = re.compile(r"(Bioreactor|DRAIN|_Tile_|GLRI)", re.I)   # edge-of-field research installations
TYPES = ("tidal_coastal", "small_stream", "cold_climate", "large_river")


def camera_type(cam_id: str, state: str | None, lat: float | None) -> str:
    if NOT_A_RIVER.search(cam_id):
        return "not_a_river"
    if TIDAL.search(cam_id):
        return "tidal_coastal"
    if SMALL.search(cam_id) and not RIVER.search(cam_id):
        return "small_stream"
    if (state or "").upper() == "AK" or (lat is not None and lat >= 44.5):
        return "cold_climate"
    return "large_river"
