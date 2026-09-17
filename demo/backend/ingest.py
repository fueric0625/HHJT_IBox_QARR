from __future__ import annotations

import importlib.util
import json
import re
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from .config import CATALOG_PATH, CLAUSES_PATH, DATA_DIR, DOCS_META_PATH, EXTRACTED_DIR, ROOT, UPLOADS_DIR
from .store import reload_kb

DOC_ID_RE = re.compile(r"^(\d+(?:-\d+){1,3})")
DOC_NO_RE = re.compile(r"(沪华虹计通[【\[][^】\]]+[】\]]\s*\d+号)")
DATE_RE = re.compile(r"(20\d{2}[-./年]\d{1,2}[-./月]\d{1,2}日?)")
CHAPTER_LINE_RE = re.compile(r"^(第[一二三四五六七八九十百零〇0-9]+章)\s*(.*)$")
ARTICLE_RE = re.compile(r"^(第[一二三四五六七八九十百零〇0-9]+条)")
ANNEX_RE = re.compile(r"^(附件\s*[一二三四五六七八九十0-9]*)")


_MODS: dict[str, Any] = {}


def _load_script(name: str):
    if name in _MODS:
        return _MODS[name]
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    _MODS[name] = mod
    return mod


def _extract_mod():
    return _load_script("extract_pdfs")


def _catalog_mod():
    return _load_script("build_catalog")


def list_files() -> dict[str, Any]:
    meta: dict[str, dict] = {}
    if DOCS_META_PATH.exists():
        meta = json.loads(DOCS_META_PATH.read_text(encoding="utf-8"))
    counts: dict[str, int] = {}
    if CLAUSES_PATH.exists():
        for line in CLAUSES_PATH.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            did = row.get("doc_id")
            if did:
                counts[did] = counts.get(did, 0) + 1
    cat_nodes = []
    if CATALOG_PATH.exists():
        cat_nodes = json.loads(CATALOG_PATH.read_text(encoding="utf-8")).get("nodes") or []
    order = [n.get("id") for n in cat_nodes if n.get("id")]
    items = []
    seen: set[str] = set()
    for did in [*order, *meta.keys()]:
        if did in seen or did not in meta:
            continue
        seen.add(did)
        info = meta[did]
        items.append(
            {
                "id": did,
                "title": info.get("title") or did,
                "doc_no": info.get("doc_no") or "",
                "filename": info.get("filename") or "",
                "clause_count": counts.get(did, 0),
                "uploaded": bool(info.get("uploaded")),
            }
        )
    return {
        "files": len(items),
        "clauses": sum(counts.values()),
        "items": items,
    }


def infer_doc_id(filename: str) -> str:
    stem = Path(filename).stem.strip()
    m = DOC_ID_RE.match(stem)
    if m:
        return m.group(1)
    slug = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", stem).strip("-")
    slug = slug[:48] or "file"
    return f"upload-{slug}"


def infer_meta(filename: str, text: str) -> dict[str, str]:
    stem = Path(filename).stem.strip()
    blob = f"{stem}\n{(text or '')[:4000]}"
    doc_no = ""
    m_no = DOC_NO_RE.search(blob)
    if m_no:
        doc_no = re.sub(r"\s+", "", m_no.group(1))
    title = stem
    rest = stem
    m_id = DOC_ID_RE.match(stem)
    if m_id:
        rest = stem[m_id.end() :].strip(" -_")
    if doc_no and doc_no in rest:
        rest = rest.replace(doc_no, "").strip(" -_")
    rest = re.sub(r"\s+", " ", rest).strip(" -_")
    if rest:
        title = rest
    title = re.sub(r"\.(pdf|PDF)$", "", title).strip() or stem
    effective = ""
    m_date = DATE_RE.search(blob)
    if m_date:
        effective = m_date.group(1).replace("年", "-").replace("月", "-").replace("日", "").replace(".", "-").replace("/", "-")
    return {"title": title, "doc_no": doc_no or "文号未识别", "effective": effective}


def _fallback_clause(doc_id: str, meta: dict, text: str) -> dict:
    body = (text or "").strip() or f"《{meta['title']}》未能抽出可引用条款原文。"
    return {
        "id": f"{doc_id}:全文",
        "doc_id": doc_id,
        "doc_title": meta["title"],
        "doc_no": meta["doc_no"],
        "clause_no": "全文",
        "level": "file",
        "chapter": "",
        "chapter_title": "",
        "breadcrumb": f"《{meta['title']}》> 全文",
        "title": meta["title"],
        "text": body[:20000],
        "has_table": "|" in body and "---" in body,
        "keywords": [],
    }


def generic_split_clauses(doc_id: str, meta: dict, text: str) -> list[dict]:
    extract = _extract_mod()
    if len(text or "") < 80:
        return [_fallback_clause(doc_id, meta, text)]

    parts = [p.strip() for p in extract.SPLIT_RE.split(text) if p and p.strip()]
    clauses: list[dict] = []
    seen: dict[str, int] = {}
    chap, chap_title = "", ""
    for part in parts:
        first = part.split("\n", 1)[0].strip()
        m_ch = CHAPTER_LINE_RE.match(first)
        m_art = ARTICLE_RE.match(part)
        m_ax = ANNEX_RE.match(part)
        if m_art:
            clause_no = m_art.group(1)
            seen[clause_no] = seen.get(clause_no, 0) + 1
            suffix = f"-{seen[clause_no]}" if seen[clause_no] > 1 else ""
            cid = f"{doc_id}:{clause_no}{suffix}"
            breadcrumb = f"《{meta['title']}》> {chap} {chap_title} > {clause_no}".replace("  ", " ")
            has_table = ("|" in part and "---" in part) or any(
                k in part for k in ("标准如下", "具体列表", "上限", "一线城市", "二线城市")
            )
            clauses.append(
                {
                    "id": cid,
                    "doc_id": doc_id,
                    "doc_title": meta["title"],
                    "doc_no": meta["doc_no"],
                    "clause_no": clause_no + suffix,
                    "level": "clause",
                    "chapter": chap,
                    "chapter_title": chap_title,
                    "breadcrumb": breadcrumb.strip(),
                    "title": clause_no,
                    "text": part,
                    "has_table": has_table,
                    "keywords": [],
                }
            )
        elif m_ax:
            ax = re.sub(r"\s+", "", m_ax.group(1))
            clauses.append(
                {
                    "id": f"{doc_id}:{ax}",
                    "doc_id": doc_id,
                    "doc_title": meta["title"],
                    "doc_no": meta["doc_no"],
                    "clause_no": ax,
                    "level": "annex",
                    "chapter": "附件",
                    "chapter_title": "附件",
                    "breadcrumb": f"《{meta['title']}》> {ax}",
                    "title": ax,
                    "text": part,
                    "has_table": True,
                    "keywords": ["附件"],
                }
            )
        elif part.startswith("版本号"):
            clauses.append(
                {
                    "id": f"{doc_id}:版本修订",
                    "doc_id": doc_id,
                    "doc_title": meta["title"],
                    "doc_no": meta["doc_no"],
                    "clause_no": "版本修订",
                    "level": "annex",
                    "chapter": "版本修订",
                    "chapter_title": "版本修订",
                    "breadcrumb": f"《{meta['title']}》> 版本修订",
                    "title": "版本修订记录",
                    "text": part,
                    "has_table": True,
                    "keywords": ["修订", "废止", "版本"],
                }
            )
        elif m_ch:
            chap = m_ch.group(1)
            rest = (m_ch.group(2) or "").strip()
            chap_title = re.split(r"[。；]", rest)[0][:40]
    clauses = extract.merge_false_splits(clauses)
    if not clauses:
        return [_fallback_clause(doc_id, meta, text)]
    return clauses


def _load_clauses() -> list[dict]:
    if not CLAUSES_PATH.exists():
        return []
    rows = []
    for line in CLAUSES_PATH.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _write_clauses(rows: list[dict]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with CLAUSES_PATH.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def ingest_pdf(filename: str, content: bytes) -> Iterator[dict]:
    extract = _extract_mod()
    catalog_mod = _catalog_mod()
    safe_name = Path(filename or "upload.pdf").name
    if not safe_name.lower().endswith(".pdf"):
        yield {"event": "error", "data": {"message": "只支持 PDF 文件"}}
        return
    if not content:
        yield {"event": "error", "data": {"message": "文件为空"}}
        return

    try:
        yield {"event": "progress", "data": {"stage": "save", "message": "正在保存 PDF…"}}
        UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
        EXTRACTED_DIR.mkdir(parents=True, exist_ok=True)
        dest = UPLOADS_DIR / safe_name
        dest.write_bytes(content)
        doc_id = infer_doc_id(safe_name)

        yield {"event": "progress", "data": {"stage": "extract", "message": "正在抽取文本…"}}
        raw, scanned = extract.extract_pdf(dest)
        raw_path = EXTRACTED_DIR / f"{doc_id}.raw.txt"
        raw_path.write_text(raw, encoding="utf-8")
        text = extract.normalize_text(raw)
        fields = infer_meta(safe_name, text)
        meta = {
            "id": doc_id,
            "title": fields["title"],
            "doc_no": fields["doc_no"],
            "effective": fields["effective"],
            "filename": safe_name,
            "uploaded": True,
            "scanned": bool(scanned),
        }

        yield {"event": "progress", "data": {"stage": "split", "message": "正在按条款拆分…"}}
        clauses = generic_split_clauses(doc_id, meta, text)
        extract.write_markdown(doc_id, meta, clauses)

        docs_meta: dict[str, dict] = {}
        if DOCS_META_PATH.exists():
            docs_meta = json.loads(DOCS_META_PATH.read_text(encoding="utf-8"))
        docs_meta[doc_id] = meta
        DOCS_META_PATH.write_text(json.dumps(docs_meta, ensure_ascii=False, indent=2), encoding="utf-8")

        all_clauses = [c for c in _load_clauses() if c.get("doc_id") != doc_id]
        all_clauses.extend(clauses)
        _write_clauses(all_clauses)

        yield {"event": "progress", "data": {"stage": "catalog", "message": "正在生成目录摘要…"}}
        try:
            catalog_mod.upsert_file(doc_id, use_llm=True)
        except SystemExit as e:
            yield {"event": "error", "data": {"message": f"目录校验失败：{e}"}}
            return
        except Exception as e:
            try:
                catalog_mod.upsert_file(doc_id, use_llm=False)
            except Exception as e2:
                yield {"event": "error", "data": {"message": f"写目录失败：{e} / {e2}"}}
                return

        reload_kb()
        listing = list_files()
        yield {
            "event": "done",
            "data": {
                "doc_id": doc_id,
                "title": meta["title"],
                "doc_no": meta["doc_no"],
                "clauses": len(clauses),
                "files": listing["files"],
                "total_clauses": listing["clauses"],
                "message": "已可提问",
            },
        }
    except Exception as e:
        yield {"event": "error", "data": {"message": str(e)}}
