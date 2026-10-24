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


def test_check_flags_untraced_and_accepts_roundings(tmp_path, monkeypatch):
    res = tmp_path / "r.csv"
    res.write_text("mae\n0.18217\n0.9567\n")
    known = crn.corpus([res])
    assert {"0.182", "95.7", "96"} <= known
    doc = tmp_path / "d.md"
    doc.write_text("median 0.182 ft, registration 95.7 %, made-up 0.444 ft, 15/20 sites\n")
    monkeypatch.setattr(crn, "ROOT", tmp_path)
    bad = crn.check([doc], known, set())
    assert [n for _, _, n in bad] == ["0.444"]


def test_html_visible_text_only_and_stale_claims(tmp_path, monkeypatch):
    page = tmp_path / "judge.html"
    page.write_text("<p>Shown: 0.444 ft</p><script>const x = 0.777;</script><pre>pip install 0.888</pre>\n"
                    "<li>7 of 20 cameras were re-aimed</li>\n<li>9/17 sites</li>\n<li>14 of 20 sites accurate</li>\n")
    rules = crn.stale_claims()                      # the committed report/stale_claims.txt
    monkeypatch.setattr(crn, "ROOT", tmp_path)
    assert [n for _, _, n in crn.check([page], set(), set())] == ["0.444"]
    hits = crn.check_stale([page], rules)
    assert [line for _, line, _ in hits] == [2, 3]


def test_corpus_accepts_four_decimals_and_small_value_sig_figs(tmp_path):
    res = tmp_path / "r.csv"
    res.write_text("0.0561653\n0.00044201\n")
    known = crn.corpus([res])
    assert {"0.0562", "0.056", "0.00044", "0.000442"} <= known
    assert "0.0563" not in known
