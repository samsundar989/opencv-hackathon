"""Every number in the judge-facing docs must appear in a committed results file (CLAUDE.md rule 3).

Scans README.md, report/REPORT.md and the W3 docs, pulls out each numeric token, and checks it against
the numbers in git-tracked files under results/ (CSV, JSON, Markdown, TXT). A float in a results file also
matches its roundings to 1–3 decimals and, for values in [0, 1], its percentage to 0–1 decimals. Fractions
like 14/20 are checked part by part.

Not checked (stated so nobody over-reads a pass):
  * dates, times, versions, IDs (D-0007, Q-0008, #29794), file paths, URLs, code spans and fenced code;
  * integers ≤ 20 (site counts and small counts match almost anything), and years 1900–2099;
  * protocol constants and other non-results numbers listed with a reason in report/number_allowlist.txt.
HTML pages are scanned as visible text: script, style and pre blocks and tags are removed first (numbers the
page renders from results JSON at runtime are therefore not checked here; they come straight from results/).
Known-wrong claims in report/stale_claims.txt (regex, reason) fail the check wherever they appear.

    python scripts/check_report_numbers.py            exit 1 and list offenders if any number is untraced
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ["README.md", "report/REPORT.md", "docs/COOL_BENCHMARK.md", "docs/OPENCV5_USAGE.md",
        "docs/RESPONSIBLE_USE.md", "docs/REPRODUCE.md", "docs/ARCHITECTURE.md", "docs/PRIOR_ART.md",
        "results/failures/README.md", "web/judge.html"]
ALLOW = ROOT / "report" / "number_allowlist.txt"
STALE = ROOT / "report" / "stale_claims.txt"
HTML_STRIP = [re.compile(r"<(script|style|pre)\b.*?</\1>", re.S | re.I), re.compile(r"<!--.*?-->", re.S),
              re.compile(r"<[^>]+>"), re.compile(r"&[a-z]+;|&#\d+;")]

NUM = re.compile(r"(?<![\w.\-/#])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)(?![\w\-]|\.\d)")
FRACTION = re.compile(r"(?<![\w.])(\d+)\s*/\s*(\d+)(?![\w.])")
STRIP = [
    re.compile(r"```.*?```", re.S),                 # fenced code
    re.compile(r"`[^`]*`"),                         # code spans
    re.compile(r"\]\([^)]*\)"),                     # link targets
    re.compile(r"https?://\S+"),
    re.compile(r"!\[[^\]]*\]"),                     # image alt text
    re.compile(r"\b\d{4}-\d{2}-\d{2}(?:[T ][\d:]+Z?)?"),   # dates
    re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b"),    # times
    re.compile(r"\b(?:D|Q|S|P|W|G)-?\d+[a-z]?\b"),  # decision/question/slice/gate ids, P1, W3, G1
    re.compile(r"#\d+"),                            # issue numbers
    re.compile(r"\bv?\d+\.\d+\.\d+(?:\.\d+)?\b"),   # versions
    re.compile(r"\b(?:19|20)\d{2}\b"),                # years (citations, dates in prose)
    re.compile(r"\b(?:Python|python|py)\s*\d+(?:\.\d+)*"),
    re.compile(r"\b[A-Za-z]+\d+[A-Za-z0-9]*\b"),    # identifiers with digits: m9g, sm_120, Graviton5, h264
    re.compile(r"\b(?:Oct|Nov|Sep|Jul|Aug|Mon|Tue|Wed|Thu|Fri|Sat|Sun)\w*\.? \d{1,2}\b"),
    re.compile(r"<!--.*?-->", re.S),
]


def tracked_results() -> list[Path]:
    out = subprocess.run(["git", "ls-files", "results"], cwd=ROOT, check=True, capture_output=True, text=True).stdout
    return [ROOT / p for p in out.split() if p.endswith((".csv", ".json", ".md", ".txt", ".sha256"))]


def corpus(files: list[Path]) -> set[str]:
    s: set[str] = set()
    tok = re.compile(r"-?\d+(?:\.\d+)?(?:[eE]-?\d+)?")
    for f in files:
        for t in tok.findall(f.read_text(encoding="utf-8", errors="ignore")):
            t = t.lstrip("-")
            s.add(t)
            try:
                v = float(t)
            except ValueError:
                continue
            if v != v or v in (float("inf"), float("-inf")):
                continue
            if v == int(v) and "." not in t and "e" not in t.lower():
                s.add(str(int(v)))
                continue
            for d in (1, 2, 3):
                s.add(f"{v:.{d}f}")
            if 0 <= v <= 1:
                for d in (0, 1):
                    s.add(f"{100 * v:.{d}f}")
    return s


def allowlist() -> set[str]:
    if not ALLOW.exists():
        return set()
    return {ln.split()[0] for ln in ALLOW.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.lstrip().startswith("#")}


def doc_numbers(text: str) -> list[tuple[int, str]]:
    lines = []
    for i, ln in enumerate(text.splitlines(), 1):
        lines.append((i, ln))
    joined = "\n".join(ln for _, ln in lines)
    for rx in STRIP:
        joined = rx.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), joined)
    out = []
    for i, ln in enumerate(joined.splitlines(), 1):
        ln2 = FRACTION.sub(lambda m: f"{m.group(1)} {m.group(2)}", ln)
        for m in NUM.finditer(ln2):
            out.append((i, m.group(1).replace(",", "")))
    return out


def visible_text(p: Path) -> str:
    text = p.read_text(encoding="utf-8")
    if p.suffix == ".html":
        for rx in HTML_STRIP:
            text = rx.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)
    return text


def stale_claims() -> list[tuple[re.Pattern, str]]:
    if not STALE.exists():
        return []
    out = []
    for ln in STALE.read_text(encoding="utf-8").splitlines():
        if ln.strip() and not ln.lstrip().startswith("#"):
            rx, _, why = ln.partition("\t")
            out.append((re.compile(rx, re.I), why.strip()))
    return out


def check_stale(paths: list[Path], rules: list[tuple[re.Pattern, str]]) -> list[tuple[str, int, str]]:
    bad = []
    for p in paths:
        if not p.exists():
            continue
        for i, ln in enumerate(visible_text(p).splitlines(), 1):
            for rx, why in rules:
                m = rx.search(ln)
                if m:
                    bad.append((str(p.relative_to(ROOT)), i, f"stale claim '{m.group(0)}': {why}"))
    return bad


def check(paths: list[Path], known: set[str], allowed: set[str]) -> list[tuple[str, int, str]]:
    bad = []
    for p in paths:
        if not p.exists():
            continue
        for line, n in doc_numbers(visible_text(p)):
            if n in known or n in allowed:
                continue
            if "." not in n and int(n) <= 20:
                continue
            bad.append((str(p.relative_to(ROOT)), line, n))
    return bad


def main() -> None:
    known = corpus(tracked_results())
    paths = [ROOT / d for d in DOCS]
    bad = check(paths, known, allowlist())
    for f, line, n in bad:
        print(f"{f}:{line}: {n} not found in any committed results file")
    stale = check_stale(paths, stale_claims())
    for f, line, msg in stale:
        print(f"{f}:{line}: {msg}")
    print(f"{len(bad)} untraced number(s), {len(stale)} stale claim(s)")
    sys.exit(1 if bad or stale else 0)


if __name__ == "__main__":
    main()
