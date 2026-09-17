from __future__ import annotations

import json
import re
from contextvars import ContextVar

from .store import compact_node, find_node, find_parent, load_catalog, load_clauses

CURRENT_QUERY: ContextVar[str] = ContextVar("CURRENT_QUERY", default="")

QUERY_EXPAND = [
    ("差旅预订平台", ["商旅软件", "商旅"]),
    ("差旅平台", ["商旅软件", "商旅"]),
    ("差旅", ["商旅", "出差"]),
    ("订票", ["机票预定", "购票"]),
    ("预订", ["预定"]),
    ("补助", ["津贴", "出差津贴"]),
    ("超过差标", ["超出标准", "个人承担", "第十七条"]),
    ("指定住宿", ["超出标准", "个人承担", "第十七条"]),
    ("逾期", ["3个月"]),
    ("紧急出差", ["出差申请", "前置审批"]),
    ("公派车辆", ["提供交通工具", "公务车", "不得报销车费", "第十三条"]),
    ("津贴", ["出差津贴", "17:30", "第十二条"]),
    ("无票", ["另行预定", "酒店预定", "机票"]),
    ("无房", ["另行预定", "酒店预定"]),
    ("网约车", ["出租车"]),
    ("油费", ["燃油补贴", "私车公用"]),
]

DOC_TITLE_TO_ID = {
    "员工日常业务支出规定": "3-1-12",
    "出差管理规定": "3-1-13",
    "报销管理办法": "3-1-14",
    "商旅管理软件使用规定": "3-1-21",
    "商旅管理软件": "3-1-21",
    "车辆管理规定": "3-1-22",
    "房屋与车辆租赁管理规定": "3-1-23",
    "办公用品管理办法": "3-1-26",
    "因公出国（境）管理规定": "3-6-1",
}


def _doc_title_to_id() -> dict[str, str]:
    mapping = dict(DOC_TITLE_TO_ID)
    try:
        from .config import DOCS_META_PATH

        if DOCS_META_PATH.exists():
            meta = json.loads(DOCS_META_PATH.read_text(encoding="utf-8"))
            for did, info in meta.items():
                title = (info.get("title") or "").strip()
                if title:
                    mapping[title] = did
    except Exception:
        pass
    return mapping


CLAUSE_NO_RE = re.compile(r"第[一二三四五六七八九十百零〇0-9]+条")
CROSS_REF_RE = re.compile(
    r"《([^》]+)》[^第《]{0,12}(第[一二三四五六七八九十百零〇0-9]+条)"
)
PARALLEL_HINT = (
    "摘要不能当原文。对摘要/关键词命中的条款、has_table 的条款、以及 query_rank 靠前的条款，"
    "请一次并行 read_clause，不要只读第一条像的。不要对章节 id 调用 read_clause。"
)
NAV_KEYS = (
    "提供交通工具",
    "公派车辆",
    "市内交通",
    "津贴",
    "17:30",
    "个人承担",
    "超标",
    "不得报销",
    "自行预定",
    "另行预定",
    "私车公用",
    "油费",
    "出差申请",
)


def expand_query_tokens(query: str) -> list[str]:
    q = (query or "").strip()
    tokens = [t for t in re.split(r"[\s,，。？?！!]+", q) if t]
    for src, dsts in QUERY_EXPAND:
        if src in q:
            tokens.extend(dsts)
    return list(dict.fromkeys(tokens))


def _query_score(blob: str, tokens: list[str]) -> int:
    if not blob or not tokens:
        return 0
    return sum(blob.count(t) for t in tokens if t and t in blob)


def _collect_clause_nodes(node: dict) -> list[dict]:
    out: list[dict] = []

    def walk(n: dict) -> None:
        if n.get("clause_id"):
            out.append(n)
        for c in n.get("children") or []:
            walk(c)

    walk(node)
    return out


def _parallel_read_list(node: dict, limit: int = 12) -> list[dict]:
    tokens = expand_query_tokens(CURRENT_QUERY.get())
    ranked: list[tuple[int, dict]] = []
    for n in _collect_clause_nodes(node):
        kws = n.get("keywords") or []
        blob = " ".join([n.get("title") or "", n.get("summary") or "", " ".join(kws)])
        score = _query_score(blob, tokens)
        if n.get("has_table"):
            score += 5
        score += min(len(kws), 6)
        ranked.append(
            (
                score,
                {
                    "id": n["clause_id"],
                    "title": n.get("title"),
                    "has_table": n.get("has_table", False),
                    "keywords": kws[:8],
                    "summary": n.get("summary"),
                    "query_rank": score,
                },
            )
        )
    ranked.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in ranked[:limit]]


def lookup_nav_hits(query: str, limit: int = 6) -> str:
    data = json.loads(lookup_keyword(query, limit=limit))
    hits = [
        {
            "id": h["id"],
            "breadcrumb": h.get("breadcrumb"),
            "has_table": h.get("has_table", False),
        }
        for h in data.get("hits") or []
    ]
    return json.dumps(
        {
            "hits": hits,
            "expanded": data.get("expanded") or [],
            "sparse": len(hits) <= 2,
            "hint": (
                "字面检索线索，不是原文。请对相关 id 并行 read_clause。"
                "若与问题情形明显不符，不得用该条硬答。"
                + ("命中很少，更可能库内无专门规定；读完后原文未覆盖该情形必须回答未在制度库中找到明确规定。" if len(hits) <= 2 else "")
            ),
        },
        ensure_ascii=False,
    )


def root_catalog_brief() -> str:
    data = json.loads(list_catalog())
    files = []
    for c in data.get("children") or []:
        files.append(
            {
                "id": c.get("id"),
                "title": c.get("title"),
                "summary": c.get("summary"),
                "keywords": c.get("keywords") or [],
            }
        )
    return json.dumps(
        {
            "files": files,
            "note": "根目录已注入，不要再 list_catalog 根节点。请 list_section 相关文件/章，或并行 read_clause。",
        },
        ensure_ascii=False,
    )


def list_catalog(parent_id: str | None = None) -> str:
    node = find_node(parent_id)
    if not node:
        return json.dumps({"error": f"未找到目录节点 {parent_id}"}, ensure_ascii=False)
    payload = {
        "current": compact_node(node, include_children=False) if node.get("id") else {"level": "root"},
        "children": [compact_node(c, include_children=False) for c in (node.get("children") or [])],
        "hint": "根目录已在首轮注入时请跳过。请根据 summary/keywords 选择下一层，调用 list_section 或并行 read_clause。",
    }
    return json.dumps(payload, ensure_ascii=False)


def list_section(node_id: str) -> str:
    node = find_node(node_id)
    if not node:
        return json.dumps({"error": f"未找到章节 {node_id}"}, ensure_ascii=False)
    children = node.get("children") or []
    clause_nodes = _collect_clause_nodes(node)
    tokens = expand_query_tokens(CURRENT_QUERY.get())

    def clause_item(n: dict) -> dict:
        blob = " ".join([n.get("title") or "", n.get("summary") or "", " ".join(n.get("keywords") or [])])
        return {
            "id": n["clause_id"],
            "title": n.get("title"),
            "summary": n.get("summary"),
            "has_table": n.get("has_table", False),
            "keywords": n.get("keywords") or [],
            "query_rank": _query_score(blob, tokens),
        }

    clause_ids = [clause_item(n) for n in clause_nodes[:50]]
    clause_ids.sort(key=lambda x: x.get("query_rank") or 0, reverse=True)
    payload = {
        "current": compact_node(node, include_children=False),
        "items": [compact_node(c, include_children=False) for c in children],
        "clause_ids": clause_ids,
        "parallel_read": _parallel_read_list(node),
        "hint": PARALLEL_HINT,
    }
    return json.dumps(payload, ensure_ascii=False)


def _see_also(clause_id: str, text: str) -> list[dict]:
    clauses = load_clauses()
    seen: set[str] = set()
    out: list[dict] = []

    def add(cid: str, reason: str) -> None:
        if not cid or cid == clause_id or cid in seen:
            return
        row = clauses.get(cid)
        if not row:
            return
        seen.add(cid)
        out.append(
            {
                "id": cid,
                "title": row.get("clause_no") or row.get("title"),
                "breadcrumb": row.get("breadcrumb"),
                "reason": reason,
            }
        )

    doc_id = clause_id.split(":", 1)[0]
    title_map = _doc_title_to_id()
    for title, no in CROSS_REF_RE.findall(text or ""):
        mapped = next((did for name, did in title_map.items() if name in title), None)
        if mapped:
            add(f"{mapped}:{no}", f"参见《{title}》{no}")
    for no in CLAUSE_NO_RE.findall(text or ""):
        add(f"{doc_id}:{no}", "正文交叉引用")

    parent = find_parent(clause_id)
    if parent:
        for sib in _collect_clause_nodes(parent):
            sid = sib.get("clause_id")
            if sib.get("has_table"):
                add(sid, "同章含表条款")
            kws = " ".join(sib.get("keywords") or [])
            if any(k in kws for k in NAV_KEYS):
                add(sid, "同章易混/例外条款")

    doc_node = find_node(doc_id)
    current_node = find_node(clause_id) or {}
    current_kws = set(current_node.get("keywords") or [])
    if doc_node:
        for n in _collect_clause_nodes(doc_node):
            sid = n.get("clause_id")
            other = set(n.get("keywords") or [])
            shared = current_kws & other & set(NAV_KEYS)
            if shared:
                add(sid, "同文件相关条款：" + "、".join(list(shared)[:3]))
    return out[:12]


def _coverage_hint(text: str, query: str) -> str | None:
    q = (query or "").strip()
    if not q or not text:
        return None
    cores = [t for t in re.findall(r"[\u4e00-\u9fff]{3,}", q)]
    skip = {"怎么办", "如何处理", "是否还能", "计算标准", "费用报销", "报销流程"}
    distinctive = [t for t in cores if t not in skip]
    if distinctive and any(t in text for t in distinctive):
        return None
    if _query_score(text, expand_query_tokens(q)) >= 3:
        return None
    return (
        "本条正文未直接写用户所问情形的处理步骤。"
        "若没有其它更相关条款，应回答未在制度库中找到明确规定，建议咨询综合部。"
    )


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
            tokens = expand_query_tokens(CURRENT_QUERY.get())
            ranked = []
            for kid in kids:
                blob = " ".join([kid.get("id") or "", kid.get("title") or "", kid.get("summary") or ""])
                ranked.append((_query_score(blob, tokens), kid))
            ranked.sort(key=lambda x: x[0], reverse=True)
            return json.dumps(
                {
                    "error": f"{clause_id} 是目录节点不是条款原文。请用下面的条款 id 调用 read_clause。",
                    "candidates": [k for _, k in ranked[:40]],
                    "parallel_read": _parallel_read_list(node),
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
        "see_also": _see_also(clause_id, row.get("text") or ""),
        "coverage_hint": _coverage_hint(row.get("text") or "", CURRENT_QUERY.get()),
        "hint": "see_also 不是原文。coverage_hint 也不是原文。需要其中条款时请并行 read_clause。",
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
            "hint": "这是字面检索，不是向量检索。命中后仍须 read_clause。若 hits 为空，请改用 list_section。",
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
            "description": "查看制度知识目录某一层。根目录已在首轮注入，无需再查根节点；parent_id 填文件或章节 id 时查看其子节点。",
            "parameters": {
                "type": "object",
                "properties": {
                    "parent_id": {
                        "type": "string",
                        "description": "父节点 id。省略表示根目录（通常不必调用）。",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_section",
            "description": "展开某个文件或章节，返回其下条款号、标题、摘要、关键词与建议并行读取的条款（不含原文）。",
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
            "description": "按条款 id 读取完整原文。可一次并行读取多条。引用数字、金额、天数、流程前必须调用。",
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
            "description": "在条款标题、关键词和正文中做字面检索，用于目录选错或已读原文与问题对不上时纠偏。不是向量检索。",
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
