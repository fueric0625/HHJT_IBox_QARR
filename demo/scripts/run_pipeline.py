"""One-shot: extract PDFs -> clauses -> catalog -> testcases."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def run(script: str, extra: list[str] | None = None) -> None:
    cmd = [sys.executable, str(HERE / script), *(extra or [])]
    print(">", " ".join(cmd), flush=True)
    subprocess.check_call(cmd)


if __name__ == "__main__":
    run("extract_pdfs.py")
    run("export_testcases.py")
    run("build_catalog.py", ["--llm"])
    run("smoke_tools.py")
    print("pipeline done")
