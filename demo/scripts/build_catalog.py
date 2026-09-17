"""Build a hierarchical catalog from clauses.jsonl.

Default path writes a deterministic, human-reviewed tree with summaries.
Optional --llm calls the company/OpenAI-compatible endpoint to refresh summaries.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLAUSES = ROOT / "data" / "clauses.jsonl"
DOCS_META = ROOT / "data" / "docs_meta.json"
OUT = ROOT / "data" / "catalog.json"

FILE_SUMMARIES = {
    "3-1-12": {
        "summary": "规范员工日常业务消费：加班就餐、业务招待、出租车/用车、差旅引用、会务、住宿报销衔接及监督检查。",
        "keywords": ["业务招待", "出租车", "紧急用车", "加班餐", "会务费", "差旅引用"],
    },
    "3-1-13": {
        "summary": "国内出差主制度：出差申请、交通住宿等级、市内交通、津贴计算、差旅报销构成与超标处理。",
        "keywords": ["出差申请", "差旅费", "住宿标准", "出差津贴", "市内交通", "私车公用", "商旅预定"],
    },
    "3-1-14": {
        "summary": "报销执行层办法：审批环节、差旅/招待/会务/租赁报销流程、私车油费、单据逾期处理。",
        "keywords": ["报销流程", "差旅费报销", "逾期", "私车公用", "业务招待报销", "会务费", "提前2天"],
    },
    "3-1-21": {
        "summary": "指定商旅软件使用：钉钉入口、前置审批、机票/酒店/火车票预定及自行预定例外。",
        "keywords": ["商旅软件", "钉钉", "机票", "酒店预定", "无房", "自行预订", "工作请示"],
    },
    "3-1-22": {
        "summary": "公务车辆调度、申请（含提前2天与紧急用车补办）、维修保养与驾驶员安全。",
        "keywords": ["公务用车", "派车", "车辆申请", "紧急用车", "驾驶员"],
    },
    "3-1-23": {
        "summary": "异地房屋与车辆租赁标准、申请、合同、报销及安全责任。",
        "keywords": ["租房", "租车", "项目部", "宿舍", "一线城市租金"],
    },
    "3-1-26": {
        "summary": "办公用品集中采购、部门申请与月度结算，原则上各部门不得自行采购。",
        "keywords": ["办公用品", "集中采购", "领用"],
    },
    "3-6-1": {
        "summary": "因公出国（境）统一审批：出访计划与提前报批、材料、归国公示、经费构成及护照管理。扫描件经 OCR，表格数字请以原文核对。",
        "keywords": ["因公出国", "出境", "护照", "外事", "出国经费", "归国公示"],
    },
}

CHAPTER_SUMMARIES = {
    ("3-1-13", "第三章"): ("出差申请：须提前填写出差申请；不提倡私车离沪；原则上统一商旅软件预定。", ["出差申请", "私车", "商旅"]),
    ("3-1-13", "第四章"): ("出差期间交通等级、往返机场交通、市内交通及住宿差标、旺季/重大活动上浮。", ["交通标准", "住宿", "差标", "旺季"]),
    ("3-1-13", "第五章"): ("差旅费构成、报销流程、津贴表、市内交通 80 元上限、公派车辆、发票与超标自理。", ["津贴", "80元", "公派车辆", "超标"]),
    ("3-1-14", "第三章"): ("差旅/私车油费/出国/招待/会务/租赁及其他费用的报销程序与注意事项。", ["差旅费报销", "油费", "会务费"]),
    ("3-1-14", "第四章"): ("费用单据逾期：原则上 3 个月内报销，逾期 3 个月以上原则上不予报销。", ["逾期", "3个月"]),
    ("3-1-21", "第三章"): ("商旅软件绑定、前置审批、机票/酒店/火车票预定规则及企业支付。", ["机票", "酒店", "火车票", "工作请示"]),
    ("3-1-12", "第二章"): ("加班就餐、招待餐标、车辆使用、差旅/出国/通讯/交通标准的引用入口。", ["招待", "出租车", "差旅"]),
    ("3-1-12", "第三章"): ("就餐申请、招待申请、出租车含紧急补办、租赁、会务、住宿费报销操作。", ["紧急用车", "补办", "住宿费"]),
}


def load_clauses() -> list[dict]:
    rows = []
    for line in CLAUSES.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def first_sentence(text: str, limit: int = 80) -> str:
    t = re.sub(r"\s+", "", text)
    t = re.sub(r"^第[一二三四五六七八九十百零〇0-9]+条", "", t)
    for sep in ("。", "；", "："):
        if sep in t:
            t = t.split(sep, 1)[0] + ("。" if sep == "。" else "")
            break
    return t[:limit]


def clause_keywords(c: dict) -> list[str]:
    blob = c["title"] + c["text"]
    lexicon = [
        "出差申请", "私车公用", "商旅", "津贴", "住宿", "市内交通", "出租车",
        "机票", "酒店", "逾期", "工作请示", "八项规定", "差旅费报销", "业务招待",
        "会务", "派车", "过路费", "旺季", "重大活动", "钉钉", "紧急",
    ]
    found = [w for w in lexicon if w in blob]
    if c.get("has_table"):
        found.append("含表格须读原文")
    return list(dict.fromkeys(found + c.get("keywords", [])))


def build_tree(clauses: list[dict], meta: dict) -> dict:
    by_doc: OrderedDict[str, list[dict]] = OrderedDict()
    for c in clauses:
        by_doc.setdefault(c["doc_id"], []).append(c)

    files = []
    valid_ids = set()
    for doc_id, items in by_doc.items():
        info = meta[doc_id]
        fs = FILE_SUMMARIES.get(doc_id, {"summary": info["title"], "keywords": []})
        chapters: OrderedDict[str, dict] = OrderedDict()
        annex_children = []
        for c in items:
            c = {
                **c,
                "summary": first_sentence(c["text"]),
                "keywords": clause_keywords(c),
            }
            valid_ids.add(c["id"])
            node = {
                "id": c["id"],
                "level": "clause" if c["level"] == "clause" else c["level"],
                "title": f"{c['clause_no']} {c['title']}".replace(f"{c['clause_no']} {c['clause_no']}", c["clause_no"]),
                "summary": c["summary"] + (" 【本条含表格，作答应读原文全表】" if c.get("has_table") else ""),
                "keywords": c["keywords"],
                "clause_id": c["id"],
                "has_table": c.get("has_table", False),
            }
            if c["level"] in {"annex", "file"} or not c.get("chapter") or c["chapter"] in {"附件", "版本修订"}:
                annex_children.append(node)
                continue
            chap_id = f"{doc_id}:{c['chapter']}"
            if chap_id not in chapters:
                hint = CHAPTER_SUMMARIES.get((doc_id, c["chapter"]))
                chapters[chap_id] = {
                    "id": chap_id,
                    "level": "chapter",
                    "title": f"{c['chapter']} {c['chapter_title']}".strip(),
                    "summary": hint[0] if hint else f"{info['title']} {c['chapter']} {c['chapter_title']}",
                    "keywords": hint[1] if hint else [],
                    "children": [],
                }
            chapters[chap_id]["children"].append(node)

        children = list(chapters.values())
        if annex_children:
            children.append(
                {
                    "id": f"{doc_id}:附件区",
                    "level": "chapter",
                    "title": "附件与版本修订",
                    "summary": "城市划分、旺季表、流程图、修订记录等附件。",
                    "keywords": ["附件", "城市划分", "旺季"],
                    "children": annex_children,
                }
            )
        files.append(
            {
                "id": doc_id,
                "level": "file",
                "title": f"《{info['title']}》",
                "doc_no": info["doc_no"],
                "effective": info.get("effective", ""),
                "summary": fs["summary"],
                "keywords": fs["keywords"],
                "children": children,
            }
        )
    return {
        "version": "demo-1.0",
        "built_from": "clauses.jsonl",
        "valid_clause_ids": sorted(valid_ids),
        "nodes": files,
    }


def validate(catalog: dict, clauses: list[dict]) -> None:
    existing = {c["id"] for c in clauses}

    def walk(nodes):
        for n in nodes:
            cid = n.get("clause_id")
            if cid and cid not in existing:
                raise SystemExit(f"hallucinated clause_id: {cid}")
            walk(n.get("children") or [])

    walk(catalog["nodes"])
    print(f"validated {len(existing)} clause ids")


def maybe_llm_summaries(catalog: dict) -> dict:
    from openai import OpenAI
    import httpx

    base = os.getenv("LLM_BASE_URL", "http://172.16.120.211:31210/v1")
    model = os.getenv("LLM_MODEL", "qwen")
    key = os.getenv("LLM_API_KEY", "dummy")
    client = OpenAI(base_url=base, api_key=key, http_client=httpx.Client(trust_env=False, timeout=120.0))
    for file_node in catalog["nodes"]:
        payload = {
            "title": file_node["title"],
            "chapters": [
                {"id": ch["id"], "title": ch["title"], "clauses": [c["title"] for c in ch.get("children", [])]}
                for ch in file_node.get("children", [])
            ],
        }
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": "你为公司制度生成导航摘要。只输出 JSON：{summary, chapters:[{id, summary, keywords}]}。"
                        "摘要不超过40字，keywords不超过6个。禁止编造不存在的条款。",
                    },
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                temperature=0,
            )
            text = resp.choices[0].message.content or "{}"
            text = re.sub(r"^```json|```$", "", text.strip(), flags=re.I | re.M)
            data = json.loads(text)
            if data.get("summary"):
                file_node["summary"] = data["summary"]
            by_id = {c["id"]: c for c in data.get("chapters", [])}
            for ch in file_node.get("children", []):
                extra = by_id.get(ch["id"])
                if extra:
                    if extra.get("summary"):
                        ch["summary"] = extra["summary"]
                    if extra.get("keywords"):
                        ch["keywords"] = extra["keywords"]
        except Exception as e:
            print(f"LLM summary skipped for {file_node['id']}: {e}")
    return catalog


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--llm", action="store_true", help="refresh summaries via LLM")
    args = parser.parse_args()
    clauses = load_clauses()
    meta = json.loads(DOCS_META.read_text(encoding="utf-8"))
    catalog = build_tree(clauses, meta)
    if args.llm:
        catalog = maybe_llm_summaries(catalog)
    validate(catalog, clauses)
    OUT.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote catalog with {len(catalog['nodes'])} files -> {OUT}")


if __name__ == "__main__":
    main()
