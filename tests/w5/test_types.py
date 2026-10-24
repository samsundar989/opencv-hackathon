from riversight.onboard.types import camera_type


def test_camera_types():
    assert camera_type("CA_Suisun_Slough_nr_Benicia", "CA", 38.1) == "tidal_coastal"
    assert camera_type("GA_Savannah_River_at_USACE_Dock_at_Savannah", "GA", 32.1) == "tidal_coastal"
    assert camera_type("IN_Blue_Creek_near_Pleasant_Mills", "IN", 40.8) == "small_stream"
    assert camera_type("PA_West_Branch_Susquehanna_River_at_Lewisburg", "PA", 40.97) == "large_river"
    assert camera_type("MN_Minnesota_River_at_Morton", "MN", 44.55) == "cold_climate"
    assert camera_type("AK_Alsek_River_at_Dry_Bay_near_Yakutat", "AK", 59.2) == "tidal_coastal"   # "Dry_Bay": name first
    assert camera_type("WI_GLRI_Bioreactor_inlet_near_Duvall_INLET_ARGIDRAIN", "WI", 44.6) == "not_a_river"
    assert camera_type("MO_Missouri_River_at_Hermann", "MO", 38.7) == "large_river"
