from __future__ import annotations

import json
import re

from .store import compact_node, find_node, load_clauses

QUERY_EXPAND = [
    ("差旅预订平台", ["商旅软件", "商旅"]),
    ("差旅平台", ["商旅软件", "商旅"]),
    ("差旅", ["商旅", "出差"]),
    ("订票", ["机票预定", "购票"]),
    ("预订", ["预定"]),
    ("补助", ["津贴", "出差津贴"]),
    ("超标", ["超出标准"]),
    ("逾期", ["3个月"]),
    ("紧急出差", ["出差申请", "前置审批"]),
    ("公派车辆", ["提供交通工具", "公务车", "不得报销车费", "第十三条"]),
    ("网约车", ["出租车"]),
    ("油费", ["燃油补贴", "私车公用"]),
]


def list_catalog(parent_id: str | None = None) -> str:
    node = find_node(parent_id)
    if not node:
        return json.dumps({"error": f"未找到目录节点 {parent_id}"}, ensure_ascii=False)
    payload = {
        "current": compact_node(node, include_children=False) if node.get("id") else {"level": "root"},
        "children": [compact_node(c, include_children=False) for c in (node.get("children") or [])],
        "hint": "请根据 summary/keywords 选择下一层节点，调用 list_section 或直接 read_clause。",
    }
    return json.dumps(payload, ensure_ascii=False)


def list_section(node_id: str) -> str:
    node = find_node(node_id)
    if not node:
        return json.dumps({"error": f"未找到章节 {node_id}"}, ensure_ascii=False)
    children = node.get("children") or []
    payload = {
        "current": compact_node(node, include_children=False),
        "items": [compact_node(c, include_children=False) for c in children],
        "clause_ids": [],
        "hint": "摘要不能当原文。对 clause_ids 里的 id 调用 read_clause。不要对章节 id 调用 read_clause。",
    }
    flat = []

    def collect(n: dict) -> None:
        if n.get("clause_id"):
            flat.append(
                {
                    "id": n["clause_id"],
                    "title": n.get("title"),
                    "summary": n.get("summary"),
                    "has_table": n.get("has_table", False),
                }
            )
        for c in n.get("children") or []:
            collect(c)

    collect(node)
    payload["clause_ids"] = flat[:50]
    return json.dumps(payload, ensure_ascii=False)


def read_clause(clause_id: str) -> str:
    clauses = load_clauses()
    row = clauses.get(clause_id)
    if not row:
        node = find_node(clause_id)
        if node and (node.get("children") or node.get("clause_id")):
            kids = []

            def collect(n: dict) -> None:
                if n.get("clause_id"):
                    kids.append({"id": n["clause_id"], "title": n.get("title"), "summary": n.get("summary")})
                for c in n.get("children") or []:
                    collect(c)

            collect(node)
            return json.dumps(
                {
                    "error": f"{clause_id} 是目录节点不是条款原文。请用下面的条款 id 调用 read_clause。",
                    "candidates": kids[:40],
                },
                ensure_ascii=False,
            )
        return json.dumps({"error": f"条款不存在: {clause_id}"}, ensure_ascii=False)
    payload = {
        "id": row["id"],
        "breadcrumb": row["breadcrumb"],
        "doc_title": row["doc_title"],
        "doc_no": row["doc_no"],
        "clause_no": row["clause_no"],
        "has_table": row.get("has_table", False),
        "text": row["text"],
    }
    return json.dumps(payload, ensure_ascii=False)


def lookup_keyword(query: str, limit: int = 8) -> str:
    q = (query or "").strip()
    if not q:
        return json.dumps({"error": "query 不能为空"}, ensure_ascii=False)
    tokens = [t for t in re.split(r"[\s,，]+", q) if t]
    for src, dsts in QUERY_EXPAND:
        if src in q:
            tokens.extend(dsts)
    tokens = list(dict.fromkeys(tokens))
    clauses = load_clauses().values()
    scored = []
    for row in clauses:
        blob = " ".join(
            [
                row.get("title", ""),
                row.get("breadcrumb", ""),
                " ".join(row.get("keywords") or []),
                row.get("text", "")[:800],
            ]
        )
        score = 0
        for t in tokens:
            if t in blob:
                score += blob.count(t) + (4 if t in (row.get("breadcrumb") or "") else 0)
        if score > 0:
            scored.append((score, row))
    scored.sort(key=lambda x: x[0], reverse=True)
    hits = []
    for score, row in scored[:limit]:
        hits.append(
            {
                "id": row["id"],
                "breadcrumb": row["breadcrumb"],
                "score": score,
                "preview": row["text"][:120].replace("\n", " "),
                "has_table": row.get("has_table", False),
            }
        )
    return json.dumps(
        {
            "query": q,
            "expanded": tokens,
            "hits": hits,
            "hint": "这是字面检索，不是向量检索。命中后仍须 read_clause。若 hits 为空，请改用 list_catalog。",
        },
        ensure_ascii=False,
    )


TOOL_IMPL = {
    "list_catalog": lambda **kw: list_catalog(kw.get("parent_id")),
    "list_section": lambda **kw: list_section(kw["node_id"]),
    "read_clause": lambda **kw: read_clause(kw["clause_id"]),
    "lookup_keyword": lambda **kw: lookup_keyword(kw["query"], int(kw.get("limit") or 8)),
}

OPENAI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_catalog",
            "description": "查看制度知识目录某一层。parent_id 为空时返回全部制度文件及摘要。",
            "parameters": {
                "type": "object",
                "properties": {
                    "parent_id": {
                        "type": "string",
                        "description": "父节点 id。省略或空字符串表示根目录（文件列表）。",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_section",
            "description": "展开某个文件或章节，返回其下条款号、标题与摘要（不含原文）。",
            "parameters": {
                "type": "object",
                "properties": {"node_id": {"type": "string", "description": "文件 id 或章节 id"}},
                "required": ["node_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_clause",
            "description": "按条款 id 读取完整原文。引用数字、金额、天数、流程前必须调用。",
            "parameters": {
                "type": "object",
                "properties": {"clause_id": {"type": "string", "description": "如 3-1-13:第五条"}},
                "required": ["clause_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_keyword",
            "description": "在条款标题、关键词和正文中做字面检索，用于目录选错时纠偏。不是向量检索。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 8},
                },
                "required": ["query"],
            },
        },
    },
]
