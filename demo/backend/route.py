from __future__ import annotations

import json
import re
from typing import Any

from .store import find_node, load_catalog

ROUTE_PROMPT = """你是公司规章制度助手的路由模块。不要回答用户问题，不要编造条款原文。

根据用户问题和下面的制度目录（只有文件/章的标题与摘要，不是原文），判断：
1. 问题方向（一句话，例如：出差津贴标准、公派车辆能否报交通费、紧急出差审批、商旅软件订票、单据逾期、库内可能无据）
2. 大致需要引用哪些文件或章节。必须使用目录里真实存在的 id，选 2～6 个最相关的。
3. 若目录摘要看起来覆盖不到该情形，把 maybe_unanswerable 设为 true。

只输出 JSON，不要其它文字：
{
  "direction": "问题方向",
  "reason": "为何选这些章节",
  "candidates": [
    {"id": "3-1-13:第五章", "title": "第五章 差旅费报销", "why": "津贴与公派车辆在本章"}
  ],
  "maybe_unanswerable": false
}

硬约束：
- 禁止输出目录中没有的 id、文件名或条款号。
- 不要把《日常业务支出》里的紧急用车补办套到出差审批。
- 「公派车辆 / 公司派车」优先看出差规定第五章（第十三条），不要只停在交通等级表。
- 「津贴 / 补助」优先看出差规定第五章（第十二条）。
- 跨文件问题时可以同时选出差规定、报销办法、商旅软件。

制度目录：
{CATALOG}
"""


def catalog_outline() -> list[dict]:
    """File + chapter titles/summaries for routing. No clause full text."""
    cat = load_catalog()
    files: list[dict] = []
    for n in cat.get("nodes") or []:
        chapters: list[dict] = []
        for ch in n.get("children") or []:
            clause_titles = [
                c.get("title") or c.get("clause_id")
                for c in (ch.get("children") or [])
                if c.get("clause_id") or c.get("level") in {"clause", "annex"}
            ]
            chapters.append(
                {
                    "id": ch.get("id"),
                    "title": ch.get("title"),
                    "summary": ch.get("summary") or "",
                    "keywords": (ch.get("keywords") or [])[:8],
                    "clauses": [t for t in clause_titles if t][:20],
                }
            )
        files.append(
            {
                "id": n.get("id"),
                "title": n.get("title"),
                "doc_no": n.get("doc_no") or "",
                "summary": n.get("summary") or "",
                "keywords": (n.get("keywords") or [])[:10],
                "chapters": chapters,
            }
        )
    return files


def catalog_outline_text() -> str:
    return json.dumps(catalog_outline(), ensure_ascii=False, indent=2)


def _extract_json(text: str) -> dict:
    raw = (text or "").strip()
    if not raw:
        return {}
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
    if fenced:
        raw = fenced.group(1).strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        data = json.loads(raw[start : end + 1])
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _known_node(node_id: str) -> dict | None:
    if not node_id:
        return None
    node = find_node(node_id)
    if node and node.get("id"):
        return node
    clauses = load_catalog().get("valid_clause_ids") or []
    if node_id in clauses:
        return {"id": node_id, "title": node_id, "level": "clause", "clause_id": node_id}
    return None


def sanitize_plan(raw: dict[str, Any]) -> dict[str, Any]:
    candidates: list[dict] = []
    seen: set[str] = set()
    for item in raw.get("candidates") or []:
        if not isinstance(item, dict):
            continue
        nid = str(item.get("id") or "").strip()
        node = _known_node(nid)
        if not node or nid in seen:
            continue
        seen.add(nid)
        candidates.append(
            {
                "id": nid,
                "title": item.get("title") or node.get("title") or nid,
                "why": str(item.get("why") or "").strip(),
                "level": node.get("level") or "",
            }
        )
        if len(candidates) >= 6:
            break
    return {
        "direction": str(raw.get("direction") or "").strip() or "未判定",
        "reason": str(raw.get("reason") or "").strip(),
        "candidates": candidates,
        "maybe_unanswerable": bool(raw.get("maybe_unanswerable")),
    }


def parse_route_text(text: str) -> dict[str, Any]:
    return sanitize_plan(_extract_json(text))


def format_route_block(plan: dict[str, Any]) -> str:
    lines = [
        "路由判断（不是原文，须先 list_section 拟引用章节，再 read_clause；禁止按本段硬答）：",
        f"方向：{plan.get('direction') or '未判定'}",
    ]
    if plan.get("reason"):
        lines.append(f"理由：{plan['reason']}")
    cands = plan.get("candidates") or []
    if cands:
        lines.append("拟引用章节：")
        for c in cands:
            why = f" — {c['why']}" if c.get("why") else ""
            lines.append(f"- {c['id']} {c.get('title') or ''}{why}".rstrip())
    else:
        lines.append("拟引用章节：未能从目录锁定，请 list_section 相关文件后再读条。")
    if plan.get("maybe_unanswerable"):
        lines.append("目录摘要可能覆盖不到该情形：读完拟引章节后，原文未写明处理方法必须回答未在制度库中找到明确规定。")
    return "\n".join(lines)
