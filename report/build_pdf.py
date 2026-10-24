"""report/REPORT.md → report/REPORT.pdf (md-to-pdf: marked + headless Chrome; images resolved relative to report/).

    python report/build_report_tables.py && python scripts/check_report_numbers.py && python report/build_pdf.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "report" / "REPORT.md"
PDF_OPTIONS = {"format": "Letter", "margin": {"top": "16mm", "bottom": "16mm", "left": "14mm", "right": "14mm"},
               "printBackground": True}


def main() -> None:
    npx = shutil.which("npx") or shutil.which("npx.cmd")
    if not npx:
        sys.exit("npx (Node.js) not found")
    cmd = [npx, "-y", "md-to-pdf@5.2.4", "report/REPORT.md", "--stylesheet", "report/pdf.css",   # relative: absolute Windows paths hang
           "--pdf-options", json.dumps(PDF_OPTIONS)]
    subprocess.run(cmd, cwd=ROOT, check=True)
    out = REPORT.with_suffix(".pdf")
    print(f"{out} ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
