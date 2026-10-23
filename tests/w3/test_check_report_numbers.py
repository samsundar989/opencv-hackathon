import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("crn", ROOT / "scripts" / "check_report_numbers.py")
crn = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(crn)


def test_doc_numbers_skips_dates_ids_code_and_splits_fractions():
    text = "On 2026-10-04 (D-0007) we got 14/20 sites, `0.999` in code, MAE 0.182 ft on m9g, 4,892 frames."
    nums = [n for _, n in crn.doc_numbers(text)]
    assert nums == ["14", "20", "0.182", "4892"]


def test_check_flags_untraced_and_accepts_roundings(tmp_path):
    res = tmp_path / "r.csv"
    res.write_text("mae\n0.18217\n0.9567\n")
    known = crn.corpus([res])
    assert {"0.182", "95.7", "96"} <= known
    doc = tmp_path / "d.md"
    doc.write_text("median 0.182 ft, registration 95.7 %, made-up 0.444 ft, 15/20 sites\n")
    crn.ROOT = tmp_path
    bad = crn.check([doc], known, set())
    assert [n for _, _, n in bad] == ["0.444"]
