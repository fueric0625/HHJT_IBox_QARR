"""Build a hierarchical catalog from clauses.jsonl.

Default path writes a deterministic tree (phrase-aware summaries + ID check).
--llm refreshes file/chapter/clause summaries via the company OpenAI-compatible API.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import OrderedDict
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
CLAUSES = ROOT / "data" / "clauses.jsonl"
DOCS_META = ROOT / "data" / "docs_meta.json"
OUT = ROOT / "data" / "catalog.json"

FILE_SUMMARIES = {
    "3-1-12": {
        "summary": "规范员工日常业务消费：加班就餐、业务招待、出租车/用车、差旅引用、会务、住宿报销衔接及监督检查。紧急用车补办只适用于用车，不是出差审批。",
        "keywords": ["业务招待", "出租车", "紧急用车", "加班餐", "会务费", "差旅引用"],
    },
    "3-1-13": {
        "summary": "国内出差主制度：出差申请须事先审批；交通等级在第八条，市内80元/公派车辆在第十三条；住宿差标在第九条，超标自理在第十七条；津贴17:30表在第十二条。",
        "keywords": ["出差申请", "差旅费", "住宿标准", "出差津贴", "市内交通", "公派车辆", "私车公用", "商旅预定"],
    },
    "3-1-14": {
        "summary": "报销执行层办法：审批环节、差旅/招待/会务/租赁报销流程、私车油费、单据逾期处理。差旅报销另有提前2天申请口径。",
        "keywords": ["报销流程", "差旅费报销", "逾期", "私车公用", "业务招待报销", "会务费", "提前2天"],
    },
    "3-1-21": {
        "summary": "指定商旅软件使用：钉钉入口、前置审批、机票/酒店/火车票预定及自行预定例外。自行订机票看第九条，无票无房看第十条。",
        "keywords": ["商旅软件", "钉钉", "机票", "酒店预定", "无房", "自行预订", "工作请示"],
    },
    "3-1-22": {
        "summary": "公务车辆调度、申请（含提前2天与紧急用车补办）、维修保养与驾驶员安全。紧急补办仅限用车申请。",
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
    ("3-1-13", "第三章"): (
        "出差申请：须提前填写出差申请，批准后有效；不提倡私车离沪；原则上统一商旅软件预定。紧急出差不能从本章读出补办时限。",
        ["出差申请", "事先审批", "私车", "商旅"],
    ),
    ("3-1-13", "第四章"): (
        "出差期间交通等级表、往返机场交通、市内公共交通原则（第八条）及住宿差标、旺季/重大活动上浮（第九条）。公派车辆/市内80元上限不在本章，在第五章第十三条。",
        ["交通标准", "住宿", "差标", "旺季", "重大活动"],
    ),
    ("3-1-13", "第五章"): (
        "差旅费构成、报销流程、津贴17:30表（第十二条）、市内交通80元上限与公司提供交通工具不得报销车费（第十三条）、发票与超标个人承担（第十七条）。含表条款须并行读原文。",
        ["津贴", "17:30", "80元", "公派车辆", "提供交通工具", "超标", "个人承担"],
    ),
    ("3-1-14", "第三章"): (
        "差旅/私车油费/出国/招待/会务/租赁及其他费用的报销程序与注意事项。差旅报销含提前2天申请及主办方书面例外。",
        ["差旅费报销", "油费", "会务费", "提前2天"],
    ),
    ("3-1-14", "第四章"): ("费用单据逾期：原则上 3 个月内报销，逾期 3 个月以上原则上不予报销。", ["逾期", "3个月"]),
    ("3-1-21", "第三章"): (
        "商旅软件绑定、前置审批、机票/酒店/火车票预定规则及企业支付。自行预定看第九条，无票无房看第十条。",
        ["机票", "酒店", "火车票", "工作请示", "自行预订"],
    ),
    ("3-1-12", "第二章"): ("加班就餐、招待餐标、车辆使用、差旅/出国/通讯/交通标准的引用入口。", ["招待", "出租车", "差旅"]),
    ("3-1-12", "第三章"): (
        "就餐申请、招待申请、出租车含紧急补办、租赁、会务、住宿费报销操作。紧急补办只针对用车，不是出差审批。",
        ["紧急用车", "补办", "住宿费"],
    ),
}

DISTINGUISH_PHRASES = [
    "提供交通工具",
    "不得报销车费",
    "公派",
    "过路费",
    "80 元",
    "80元",
    "17:30",
    "12:00",
    "120 元",
    "120元",
    "个人承担",
    "工作请示",
    "须事先",
    "提前 2 天",
    "提前2天",
    "3个月",
    "1 元/公里",
    "1元/公里",
    "自行预定",
    "自行预订",
    "商旅软件",
    "紧急用车",
    "重大活动",
    "旺季",
    "超出标准",
    "主办方",
]


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
        "出差申请",
        "私车公用",
        "商旅",
        "津贴",
        "住宿",
        "市内交通",
        "出租车",
        "机票",
        "酒店",
        "逾期",
        "工作请示",
        "八项规定",
        "差旅费报销",
        "业务招待",
        "会务",
        "派车",
        "过路费",
        "旺季",
        "重大活动",
        "钉钉",
        "紧急",
        "提供交通工具",
        "公派车辆",
        "不得报销车费",
        "个人承担",
        "超标",
        "17:30",
        "12:00",
        "自行预订",
        "自行预定",
        "提前2天",
        "须事先",
        "主办方",
    ]
    found = [w for w in lexicon if w in blob]
    if "公司提供交通工具" in blob and "公派车辆" not in found:
        found.append("公派车辆")
    if "17:30" in blob and "津贴" in blob:
        found.append("出差津贴")
    if c.get("has_table"):
        found.append("含表格须读原文")
    return list(dict.fromkeys(found + c.get("keywords", [])))


def clause_summary(c: dict) -> str:
    base = first_sentence(c["text"])
    extras = [p for p in DISTINGUISH_PHRASES if p in c["text"] and p not in base]
    if extras:
        base = f"{base} 要点：{'、'.join(extras[:6])}"
    if c.get("has_table"):
        base += " 【本条含表格，作答应读原文全表】"
    return base


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
            kws = clause_keywords(c)
            valid_ids.add(c["id"])
            node = {
                "id": c["id"],
                "level": "clause" if c["level"] == "clause" else c["level"],
                "title": f"{c['clause_no']} {c['title']}".replace(f"{c['clause_no']} {c['clause_no']}", c["clause_no"]),
                "summary": clause_summary(c),
                "keywords": kws,
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
        "version": "demo-1.1",
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


def _strip_llm_json(text: str) -> str:
    text = text or ""
    text = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.I)
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.I | re.M)
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return text[start : end + 1]
    return text


def _llm_json(client, model: str, system: str, user: str) -> dict:
    kwargs = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0,
        "max_tokens": 1200,
    }
    try:
        resp = client.chat.completions.create(
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
            **kwargs,
        )
    except Exception:
        resp = client.chat.completions.create(**kwargs)
    raw = resp.choices[0].message.content or "{}"
    return json.loads(_strip_llm_json(raw))


def maybe_llm_summaries(catalog: dict, clauses: list[dict], only_ids: set[str] | None = None) -> dict:
    from openai import OpenAI
    import httpx

    base = os.getenv("LLM_BASE_URL", "http://172.16.120.211:31210/v1")
    model = os.getenv("LLM_MODEL", "qwen")
    key = os.getenv("LLM_API_KEY", "dummy")
    client = OpenAI(base_url=base, api_key=key, http_client=httpx.Client(trust_env=False, timeout=60.0))
    clauses_by_id = {c["id"]: c for c in clauses}
    valid_ids = set(clauses_by_id)

    clause_sys = (
        "你为制度目录生成导航摘要。只输出 JSON："
        '{"summary":"本章不超过60字，写明含表条款和易混点",'
        '"keywords":["书面或口语"],'
        '"clauses":[{"id":"必须是输入已有id","summary":"一句话区分同章兄弟条，保留关键数字/例外","keywords":[]}]}'
        "禁止编造条款 id。不要 Markdown。"
    )
    file_sys = (
        "你为制度文件写导航摘要。只输出 JSON："
        '{"file_summary":"不超过70字，写明易混点与应读条款号","file_keywords":[]}'
        "不要编造不存在的条款。"
    )

    for file_node in catalog["nodes"]:
        if only_ids is not None and file_node["id"] not in only_ids:
            continue
        print(f"LLM summarizing {file_node['id']} {file_node['title']}", flush=True)
        chapter_briefs = []
        for ch in file_node.get("children") or []:
            items = []
            for n in ch.get("children") or []:
                cid = n.get("clause_id")
                if not cid:
                    continue
                row = clauses_by_id.get(cid) or {}
                items.append(
                    {
                        "id": cid,
                        "title": n.get("title"),
                        "has_table": n.get("has_table", False),
                        "text": (row.get("text") or "")[:180],
                    }
                )
            if not items:
                continue
            payload = {"chapter_id": ch["id"], "title": ch.get("title"), "clauses": items}
            try:
                data = _llm_json(client, model, clause_sys, json.dumps(payload, ensure_ascii=False))
            except Exception as e:
                print(f"  skip chapter {ch['id']}: {e}", flush=True)
                continue
            if data.get("summary"):
                ch["summary"] = str(data["summary"])[:220]
            if data.get("keywords"):
                ch["keywords"] = list(dict.fromkeys([str(x) for x in data["keywords"][:10]]))
            by_cl = {c.get("id"): c for c in data.get("clauses") or [] if c.get("id") in valid_ids}
            for n in ch.get("children") or []:
                extra = by_cl.get(n.get("clause_id") or "")
                if not extra:
                    continue
                summary = str(extra.get("summary") or n.get("summary") or "")
                if n.get("has_table") and "含表格" not in summary:
                    summary += " 【本条含表格，作答应读原文全表】"
                n["summary"] = summary[:240]
                kws = list(n.get("keywords") or [])
                kws.extend(str(x) for x in (extra.get("keywords") or [])[:8])
                n["keywords"] = list(dict.fromkeys(kws))
            chapter_briefs.append({"id": ch["id"], "title": ch.get("title"), "summary": ch.get("summary")})
            print(f"  ok {ch['id']}", flush=True)

        try:
            fdata = _llm_json(
                client,
                model,
                file_sys,
                json.dumps({"title": file_node["title"], "chapters": chapter_briefs}, ensure_ascii=False),
            )
            if fdata.get("file_summary"):
                file_node["summary"] = str(fdata["file_summary"])[:160]
            if fdata.get("file_keywords"):
                file_node["keywords"] = list(dict.fromkeys([str(x) for x in fdata["file_keywords"][:10]]))
            print(f"  file summary ok {file_node['id']}", flush=True)
        except Exception as e:
            print(f"  skip file summary {file_node['id']}: {e}", flush=True)
    return catalog


def apply_mixup_hints(catalog: dict) -> dict:
    """Keep human mix-up hints at file/chapter level so LLM cannot erase them."""
    for file_node in catalog.get("nodes") or []:
        fs = FILE_SUMMARIES.get(file_node["id"])
        if fs:
            file_node["summary"] = fs["summary"]
            file_node["keywords"] = list(dict.fromkeys(list(fs.get("keywords") or []) + list(file_node.get("keywords") or [])))
        for ch in file_node.get("children") or []:
            chap_name = (ch.get("id") or "").split(":", 1)[-1]
            hint = CHAPTER_SUMMARIES.get((file_node["id"], chap_name))
            if not hint:
                continue
            ch["summary"] = hint[0]
            ch["keywords"] = list(dict.fromkeys(list(hint[1]) + list(ch.get("keywords") or [])))
    return catalog


def upsert_file(doc_id: str, use_llm: bool = True) -> dict:
    """Rebuild one file node and merge it into the existing catalog.

    Other files keep their current summaries (including prior LLM clause text).
    """
    clauses = load_clauses()
    meta = json.loads(DOCS_META.read_text(encoding="utf-8"))
    fresh = build_tree(clauses, meta)
    new_file = next((n for n in fresh["nodes"] if n["id"] == doc_id), None)
    if new_file is None:
        raise SystemExit(f"doc_id not in tree: {doc_id}")
    if use_llm:
        maybe_llm_summaries({"nodes": [new_file], "valid_clause_ids": []}, clauses, only_ids={doc_id})
    if OUT.exists():
        catalog = json.loads(OUT.read_text(encoding="utf-8"))
        catalog["nodes"] = [n for n in (catalog.get("nodes") or []) if n.get("id") != doc_id]
        catalog["nodes"].append(new_file)
    else:
        catalog = fresh
    catalog["valid_clause_ids"] = sorted({c["id"] for c in clauses})
    catalog["built_from"] = "clauses.jsonl"
    catalog = apply_mixup_hints(catalog)
    validate(catalog, clauses)
    OUT.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
    return catalog


def rebuild(only_ids: set[str] | None = None, use_llm: bool = False) -> dict:
    clauses = load_clauses()
    meta = json.loads(DOCS_META.read_text(encoding="utf-8"))
    catalog = build_tree(clauses, meta)
    if use_llm:
        catalog = maybe_llm_summaries(catalog, clauses, only_ids=only_ids)
    catalog = apply_mixup_hints(catalog)
    validate(catalog, clauses)
    OUT.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
    return catalog


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--llm", action="store_true", help="refresh summaries via LLM")
    parser.add_argument(
        "--hints-only",
        action="store_true",
        help="re-apply file/chapter mix-up hints on the existing catalog.json without rebuilding",
    )
    args = parser.parse_args()
    clauses = load_clauses()
    if args.hints_only:
        catalog = json.loads(OUT.read_text(encoding="utf-8"))
        catalog = apply_mixup_hints(catalog)
        validate(catalog, clauses)
        OUT.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"re-applied mix-up hints -> {OUT}")
        return
    catalog = rebuild(use_llm=args.llm)
    print(f"wrote catalog with {len(catalog['nodes'])} files -> {OUT}")


if __name__ == "__main__":
    main()
