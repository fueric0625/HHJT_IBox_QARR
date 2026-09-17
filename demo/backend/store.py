from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from .config import CATALOG_PATH, CLAUSES_PATH


@lru_cache(maxsize=1)
def load_clauses() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for line in CLAUSES_PATH.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            out[row["id"]] = row
    return out


@lru_cache(maxsize=1)
def load_catalog() -> dict[str, Any]:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def reload_kb() -> None:
    load_clauses.cache_clear()
    load_catalog.cache_clear()


def find_node(node_id: str | None) -> dict | None:
    catalog = load_catalog()
    if not node_id:
        return {"id": None, "level": "root", "children": catalog["nodes"]}

    def walk(nodes: list[dict]) -> dict | None:
        for n in nodes:
            if n.get("id") == node_id:
                return n
            hit = walk(n.get("children") or [])
            if hit:
                return hit
        return None

    return walk(catalog["nodes"])


def find_parent(node_id: str) -> dict | None:
    catalog = load_catalog()

    def walk(nodes: list[dict], parent: dict | None) -> dict | None:
        for n in nodes:
            if n.get("id") == node_id or n.get("clause_id") == node_id:
                return parent
            hit = walk(n.get("children") or [], n)
            if hit is not None:
                return hit
        return None

    return walk(catalog["nodes"], None)


def compact_node(n: dict, include_children: bool = False) -> dict:
    item = {
        "id": n.get("id"),
        "level": n.get("level"),
        "title": n.get("title"),
        "summary": n.get("summary"),
        "keywords": n.get("keywords") or [],
        "doc_no": n.get("doc_no"),
        "has_table": n.get("has_table", False),
        "clause_id": n.get("clause_id"),
    }
    children = n.get("children") or []
    if include_children:
        item["children"] = [compact_node(c, include_children=False) for c in children]
    else:
        item["child_count"] = len(children)
    return {k: v for k, v in item.items() if v not in (None, [], "")}
