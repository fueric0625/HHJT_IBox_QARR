"""Local tool-protocol smoke test (no LLM). Covers plan phase-1 cases 11/16/4/6."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.tools import list_catalog, list_section, lookup_keyword, read_clause  # noqa: E402


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    root = json.loads(list_catalog())
    titles = [c["title"] for c in root["children"]]
    assert any("出差管理规定" in t for t in titles), titles
    assert any("商旅" in t for t in titles), titles
    print("list_catalog files:", titles)

    travel = json.loads(list_section("3-1-13"))
    print("3-1-13 chapters:", [c["title"] for c in travel["items"]])

    clause = json.loads(read_clause("3-1-13:第十三条"))
    assert "不得报销" in clause["text"], clause["text"][:80]
    print("read_clause 第十三条 ok", clause["breadcrumb"])

    overdue = json.loads(read_clause("3-1-14:第二十一条"))
    assert "3" in overdue["text"]
    print("read_clause 逾期 ok")

    hotel = json.loads(read_clause("3-1-21:第十条"))
    assert "另行预定" in hotel["text"]
    print("read_clause 酒店预定 ok")

    hits = json.loads(lookup_keyword("出差津贴"))
    ids = [h["id"] for h in hits["hits"]]
    assert any(i.startswith("3-1-13") for i in ids), ids
    print("lookup_keyword 出差津贴 ->", ids[:5])
    print("SMOKE_OK")


if __name__ == "__main__":
    main()
