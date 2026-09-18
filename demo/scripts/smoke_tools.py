"""Local tool-protocol smoke test (no LLM). Covers navigation hints for 第十二/十三条."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.store import load_catalog, load_clauses  # noqa: E402
from backend.route import catalog_outline, parse_route_text  # noqa: E402
from backend.tools import (  # noqa: E402
    CURRENT_QUERY,
    list_catalog,
    list_section,
    lookup_keyword,
    lookup_nav_hits,
    read_clause,
    root_catalog_brief,
)


def _blob(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    load_catalog.cache_clear()
    load_clauses.cache_clear()

    root = json.loads(list_catalog())
    titles = [c["title"] for c in root["children"]]
    assert any("出差管理规定" in t for t in titles), titles
    assert any("商旅" in t for t in titles), titles
    print("list_catalog files:", titles)

    brief = json.loads(root_catalog_brief())
    assert brief.get("files"), brief
    assert any(f.get("id") == "3-1-13" for f in brief["files"]), brief["files"]
    print("root_catalog_brief files:", len(brief["files"]))

    outline = catalog_outline()
    ch_ids = [c["id"] for f in outline for c in f.get("chapters") or []]
    assert any(f.get("id") == "3-1-13" for f in outline), outline
    assert "3-1-13:第五章" in ch_ids, ch_ids
    print("catalog_outline files:", len(outline), "chapters:", len(ch_ids))

    parsed = parse_route_text(
        '前文\n```json\n{"direction":"津贴","candidates":[{"id":"3-1-13:第五章","title":"第五章","why":"津贴表"}],"maybe_unanswerable":false}\n```'
    )
    assert parsed["direction"] == "津贴", parsed
    assert parsed["candidates"][0]["id"] == "3-1-13:第五章", parsed
    fake = parse_route_text('{"direction":"x","candidates":[{"id":"不存在:第九十九条"}]}')
    assert fake["candidates"] == [], fake
    print("parse_route_text ok")

    travel = json.loads(list_section("3-1-13"))
    print("3-1-13 chapters:", [c["title"] for c in travel["items"]])
    assert travel.get("parallel_read"), travel.keys()

    ch5 = json.loads(list_section("3-1-13:第五章"))
    by_id = {c["id"]: c for c in ch5["clause_ids"]}
    c12 = _blob(by_id["3-1-13:第十二条"])
    c13 = _blob(by_id["3-1-13:第十三条"])
    ch5_blob = _blob(ch5)
    assert "津贴" in c12, c12
    assert "17:30" in c12 or "17:30" in ch5_blob, c12
    assert "公派" in c13 or "提供交通工具" in c13, c13
    print("list_section 第五章 第十二/十三条 keywords ok")

    clause = json.loads(read_clause("3-1-13:第十三条"))
    assert "不得报销" in clause["text"], clause["text"][:80]
    see_ids = [x["id"] for x in clause.get("see_also") or []]
    assert any(i == "3-1-13:第十二条" for i in see_ids), see_ids
    print("read_clause 第十三条 ok", clause["breadcrumb"], "see_also", see_ids[:6])

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

    tok = CURRENT_QUERY.set("公派车辆出差，是否还能报销交通费用？")
    try:
        nav = json.loads(lookup_nav_hits("公派车辆出差，是否还能报销交通费用？"))
        nav_ids = [h["id"] for h in nav["hits"]]
        assert "3-1-13:第十三条" in nav_ids, nav_ids
        c13 = json.loads(read_clause("3-1-13:第八条"))
        see = [x["id"] for x in c13.get("see_also") or []]
        assert "3-1-13:第十三条" in see, see
        print("nav 公派车辆 ->", nav_ids[:5], "see_also from 第八条", see[:6])
    finally:
        CURRENT_QUERY.reset(tok)

    nav17 = json.loads(lookup_nav_hits("公司出差津贴的计算标准"))
    nav17_ids = [h["id"] for h in nav17["hits"]]
    assert "3-1-13:第十二条" in nav17_ids, nav17_ids
    print("nav 津贴 ->", nav17_ids[:5])
    print("SMOKE_OK")


if __name__ == "__main__":
    main()
