"""Extract policy PDFs into cleaned text, then split into clause atoms."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pymupdf
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

ROOT = Path(__file__).resolve().parents[1]
PDF_DIR = Path(r"E:\ibox_qarr\files\出差相关制度")
OUT_DIR = ROOT / "data" / "extracted"
CLAUSES_PATH = ROOT / "data" / "clauses.jsonl"
DOCS_META_PATH = ROOT / "data" / "docs_meta.json"

DOC_META = {
    "3-1-12": {
        "id": "3-1-12",
        "title": "员工日常业务支出规定",
        "doc_no": "沪华虹计通【2022】001号",
        "effective": "2022-03-18",
        "filename": "3-1-12 沪华虹计通【2022】001号 员工日常业务支出规定.pdf",
    },
    "3-1-13": {
        "id": "3-1-13",
        "title": "出差管理规定",
        "doc_no": "沪华虹计通【2022】002号",
        "effective": "2022-03-18",
        "filename": "3-1-13 沪华虹计通【2022】002号 出差管理规定.pdf",
    },
    "3-1-14": {
        "id": "3-1-14",
        "title": "报销管理办法",
        "doc_no": "沪华虹计通【2022】003号",
        "effective": "2022-03-18",
        "filename": "3-1-14 沪华虹计通【2022】003号 报销管理办法.pdf",
    },
    "3-1-21": {
        "id": "3-1-21",
        "title": "商旅管理软件使用规定",
        "doc_no": "沪华虹计通【2022】015号",
        "effective": "2022-07-25",
        "filename": "3-1-21 沪华虹计通【2022】015号 商旅管理软件使用规定.pdf",
    },
    "3-1-22": {
        "id": "3-1-22",
        "title": "车辆管理规定",
        "doc_no": "沪华虹计通【2022】016号",
        "effective": "2022-07-25",
        "filename": "3-1-22 沪华虹计通【2022】016号 车辆管理规定.pdf",
    },
    "3-1-23": {
        "id": "3-1-23",
        "title": "房屋与车辆租赁管理规定",
        "doc_no": "沪华虹计通【2022】017号",
        "effective": "2022-07-25",
        "filename": "3-1-23 沪华虹计通【2022】017号 房屋与车辆租赁管理规定.pdf",
    },
    "3-1-26": {
        "id": "3-1-26",
        "title": "办公用品管理办法",
        "doc_no": "沪华虹计通【2022】025号",
        "effective": "2022-08-01",
        "filename": "3-1-26 沪华虹计通【2022】025号 办公用品管理办法.pdf",
    },
    "3-6-1": {
        "id": "3-6-1",
        "title": "因公出国（境）管理规定",
        "doc_no": "沪华虹计通【2018】06号",
        "effective": "2018",
        "filename": "3-6-1 沪华虹计通【2018】06号 因公出国（境）管理规定.pdf",
    },
}

CHAPTER_TITLES = {
    "3-1-12": {
        "第一章": "总则",
        "第二章": "业务支出执行标准",
        "第三章": "具体操作要求",
        "第四章": "监督检查",
        "第五章": "附则",
    },
    "3-1-13": {
        "第一章": "总则",
        "第二章": "职责",
        "第三章": "出差申请",
        "第四章": "出差期间各项规定",
        "第五章": "差旅费报销",
        "第六章": "其他",
    },
    "3-1-14": {
        "第一章": "总则",
        "第二章": "环节与责任",
        "第三章": "执行程序及标准",
        "第四章": "单据逾期报销处理",
        "第五章": "附则",
    },
    "3-1-21": {
        "第一章": "总则",
        "第二章": "职责",
        "第三章": "公司指定商旅管理软件使用注意事项",
        "第四章": "其他",
    },
    "3-1-22": {
        "第一章": "总则",
        "第二章": "车辆使用管理",
        "第三章": "车辆日常管理",
        "第四章": "车辆的维修和养护",
        "第五章": "安全用车和驾驶员的管理",
        "第六章": "附则",
    },
    "3-1-23": {
        "第一章": "总则",
        "第二章": "房屋租赁规范",
        "第三章": "车辆租赁规范",
        "第四章": "附则",
    },
    "3-1-26": {
        "第一章": "总则",
        "第二章": "管理体系",
        "第三章": "管理程序",
        "第四章": "附则",
    },
    "3-6-1": {
        "第一章": "总则",
        "第二章": "出访审定与选派",
        "第三章": "报批程序与材料",
        "第四章": "出国纪律与费用",
        "第五章": "附则",
    },
}

ARTICLE_TO_CHAPTER = {
    "3-1-12": [
        (1, 3, "第一章"),
        (4, 10, "第二章"),
        (11, 20, "第三章"),
        (21, 23, "第四章"),
        (24, 24, "第五章"),
    ],
    "3-1-13": [
        (1, 2, "第一章"),
        (3, 4, "第二章"),
        (5, 7, "第三章"),
        (8, 9, "第四章"),
        (10, 17, "第五章"),
        (18, 18, "第六章"),
    ],
    "3-1-14": [
        (1, 4, "第一章"),
        (5, 8, "第二章"),
        (9, 20, "第三章"),
        (21, 22, "第四章"),
        (23, 24, "第五章"),
    ],
    "3-1-21": [
        (1, 2, "第一章"),
        (3, 5, "第二章"),
        (6, 12, "第三章"),
        (13, 13, "第四章"),
    ],
    "3-1-22": [
        (1, 3, "第一章"),
        (4, 6, "第二章"),
        (7, 10, "第三章"),
        (11, 19, "第四章"),
        (20, 26, "第五章"),
        (27, 27, "第六章"),
    ],
    "3-1-23": [
        (1, 3, "第一章"),
        (4, 12, "第二章"),
        (13, 20, "第三章"),
        (21, 30, "第四章"),
    ],
    "3-1-26": [
        (1, 3, "第一章"),
        (4, 5, "第二章"),
        (6, 7, "第三章"),
        (8, 8, "第四章"),
    ],
    "3-6-1": [
        (1, 3, "第一章"),
        (4, 5, "第二章"),
        (6, 11, "第三章"),
        (12, 20, "第四章"),
        (21, 22, "第五章"),
    ],
}


def cn_to_int(s: str) -> int:
    s = s.strip()
    if s.isdigit():
        return int(s)
    digits = {"零": 0, "〇": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    if s == "十":
        return 10
    if s.startswith("十"):
        return 10 + digits.get(s[1:], 0)
    if "十" in s:
        a, b = s.split("十", 1)
        return digits.get(a, 0) * 10 + (digits.get(b, 0) if b else 0)
    if s.startswith("二十"):
        rest = s[2:]
        return 20 + digits.get(rest, 0)
    return digits.get(s, 0)


HEADING_LINE = re.compile(
    r"^(第[一二三四五六七八九十百零〇0-9]+[章节条]|附件[一二三四五六七八九十0-9]+|版本号)"
)
TESS_DIR = Path(r"C:\Program Files\Tesseract-OCR")
TESSERACT = TESS_DIR / "tesseract.exe"
TESSDATA = ROOT / "data" / "tessdata"
OCR_ZOOM = 4.0
_TESS_STARTUPINFO = None
if os.name == "nt":
    _TESS_STARTUPINFO = subprocess.STARTUPINFO()
    _TESS_STARTUPINFO.dwFlags |= subprocess.STARTF_USESHOWWINDOW


def normalize_text(text: str) -> str:
    text = text.replace("\u3000", " ")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"第\s*(\d+)\s*页共\s*\d+\s*页", "", text)
    text = re.sub(r"===== PAGE \d+ =====", "\n", text)
    lines = text.split("\n")
    merged: list[str] = []
    for line in lines:
        s = line.strip()
        if not s:
            continue
        if "|" in s and not s.startswith("|") and s.count("|") >= 3:
            if merged and merged[-1].startswith("|") and "---" not in merged[-1]:
                continue
            s = "| " + s.lstrip("| ").rstrip("| ").replace(" | ", " | ")
            if not s.endswith("|"):
                s += " |"
            if not s.startswith("|"):
                s = "| " + s
        is_table = s.startswith("|")
        prev_table = bool(merged) and merged[-1].startswith("|")
        if is_table or prev_table or HEADING_LINE.match(s):
            merged.append(s)
            continue
        if merged and merged[-1] and not HEADING_LINE.match(merged[-1]):
            prev = merged[-1]
            if re.search(r"[\u4e00-\u9fff]$", prev) and re.match(r"[\u4e00-\u9fff]", s):
                merged[-1] = prev + s
                continue
        merged.append(s)
    text = "\n".join(merged)
    text = re.sub(r" +", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(
        r"(?m)^([^|\n][^\n]*\|[^\n]*\|[^\n]*\|)\s*\n(\| ---)",
        r"| \1\n\2",
        text,
    )
    return text.strip()


def _cell(value: str | None) -> str:
    return (value or "").replace("\n", "<br>").replace("|", "\\|").strip()


def table_to_markdown(table) -> str:
    rows = table.extract()
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    norm = [list(r) + [""] * (width - len(r)) for r in rows]
    header = [_cell(c) or " " for c in norm[0]]
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    empty_run = 0
    for row in norm[1:]:
        cells = [_cell(c) for c in row]
        if not any(cells):
            empty_run += 1
            if empty_run > 1:
                continue
        else:
            empty_run = 0
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def splice_tables(page) -> str:
    try:
        found = page.find_tables()
        tables = list(found.tables)
    except Exception:
        tables = []
    if not tables:
        return page.get_text("text", sort=True) or ""

    packed: list[tuple] = []
    for t in tables:
        if t.row_count < 2 or t.col_count < 2:
            continue
        md = table_to_markdown(t)
        if md.count("|") < 8:
            continue
        packed.append((pymupdf.Rect(t.bbox), md))
    if not packed:
        return page.get_text("text", sort=True) or ""

    items: list[tuple] = []
    for block in page.get_text("blocks"):
        x0, y0, x1, y1, text, *_ = block
        blob = str(text or "").strip()
        if not blob:
            continue
        if packed and blob.count("|") >= 2:
            continue
        rect = pymupdf.Rect(x0, y0, x1, y1)
        cy, cx = (rect.y0 + rect.y1) / 2, (rect.x0 + rect.x1) / 2
        if any(box.y0 - 3 <= cy <= box.y1 + 3 and box.x0 - 3 <= cx <= box.x1 + 3 for box, _ in packed):
            continue
        area = max(rect.get_area(), 1.0)
        if any((rect & box).get_area() / area > 0.25 for box, _ in packed):
            continue
        items.append((y0, x0, blob))
    for box, md in packed:
        items.append((box.y0, box.x0, md))
    items.sort(key=lambda x: (round(x[0], 1), x[1]))
    return "\n\n".join(part for _, _, part in items)


def _tesseract_env() -> dict:
    env = os.environ.copy()
    env["PATH"] = str(TESS_DIR) + os.pathsep + env.get("PATH", "")
    env["TESSDATA_PREFIX"] = str(TESSDATA)
    return env


def tesseract_image(path: Path, psm: int = 4) -> str:
    cmd = [
        str(TESSERACT),
        str(path),
        "stdout",
        "-l",
        "chi_sim+eng",
        "--oem",
        "1",
        "--psm",
        str(psm),
        "--tessdata-dir",
        str(TESSDATA),
        "-c",
        "preserve_interword_spaces=1",
    ]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        env=_tesseract_env(),
        startupinfo=_TESS_STARTUPINFO,
    )
    raw = proc.stdout
    for enc in ("utf-8", "gbk"):
        try:
            return raw.decode(enc).strip()
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace").strip()


def page_to_pil(page, zoom: float = OCR_ZOOM) -> Image.Image:
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False, colorspace=pymupdf.csGRAY)
    img = Image.frombytes("L", (pix.width, pix.height), pix.samples)
    img = ImageOps.autocontrast(img, cutoff=0.4)
    img = ImageEnhance.Contrast(img).enhance(1.3)
    return img.filter(ImageFilter.UnsharpMask(radius=1.0, percent=130, threshold=2))


def _longest_dark_run(values, thr: int) -> int:
    best = cur = 0
    for p in values:
        if p < thr:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def detect_grid(img: Image.Image, thr: int = 130) -> tuple[list[int], list[int]]:
    w, h = img.size
    px = img.tobytes()

    def run_row(y: int) -> int:
        base = y * w
        return _longest_dark_run((px[base + x] for x in range(w)), thr)

    def run_col(x: int) -> int:
        return _longest_dark_run((px[y * w + x] for y in range(h)), thr)

    v_scores = [run_col(x) for x in range(w)]
    vclus: list[list[int]] = []
    for x in range(w):
        if v_scores[x] <= h * 0.10:
            continue
        if vclus and x - vclus[-1][-1] <= 5:
            vclus[-1].append(x)
        else:
            vclus.append([x])
    v_lines = [max(c, key=lambda x: v_scores[x]) for c in vclus]

    h_scores = [run_row(y) for y in range(h)]
    hclus: list[list[int]] = []
    for y in range(h):
        if h_scores[y] <= w * 0.22:
            continue
        if hclus and y - hclus[-1][-1] <= 5:
            hclus[-1].append(y)
        else:
            hclus.append([y])
    h_lines = [max(c, key=lambda y: h_scores[y]) for c in hclus]
    return v_lines, h_lines


def is_table_grid(v_lines: list[int], h_lines: list[int]) -> bool:
    return len(v_lines) >= 4 and len(h_lines) >= 4


def is_mostly_blank(img: Image.Image, ink_thr: int = 140) -> bool:
    px = img.tobytes()
    if not px:
        return True
    step = max(1, len(px) // 8000)
    dark = sum(1 for i in range(0, len(px), step) if px[i] < ink_thr)
    return dark < max(3, (len(px) // step) * 0.01)


def ocr_pil(img: Image.Image, psm: int, tmp: Path, name: str, collapse: bool = True) -> str:
    if img.width < 8 or img.height < 8 or is_mostly_blank(img):
        return ""
    work = img
    if img.height < 40 or img.width < 40:
        work = img.resize((max(8, img.width * 2), max(8, img.height * 2)), Image.Resampling.LANCZOS)
    path = tmp / name
    work.save(path)
    text = tesseract_image(path, psm=psm)
    if collapse:
        return re.sub(r"\s+", " ", text).strip()
    return text.strip()


def _header_like(row: list[str]) -> bool:
    blob = "".join(row)
    return any(k in blob for k in ("区域", "序号", "名称", "标准", "日期", "部门", "人员"))


def ocr_grid_markdown(img: Image.Image, v_lines: list[int], h_lines: list[int], tmp: Path) -> str:
    rows: list[list[str]] = []
    for ri in range(len(h_lines) - 1):
        y0, y1 = h_lines[ri] + 3, h_lines[ri + 1] - 3
        row: list[str] = []
        for ci in range(len(v_lines) - 1):
            x0, x1 = v_lines[ci] + 3, v_lines[ci + 1] - 3
            if x1 - x0 < 8 or y1 - y0 < 8:
                row.append("")
                continue
            cell = img.crop((x0, y0, x1, y1))
            psm = 7 if (y1 - y0) < 90 else 6
            row.append(ocr_pil(cell, psm, tmp, f"r{ri}c{ci}.png").replace("|", "\\|"))
        if any(c.strip() for c in row):
            rows.append(row)
    if not rows:
        return ""
    caption = ""
    filled = sum(1 for c in rows[0] if c.strip())
    if len(rows) > 1 and _header_like(rows[1]) and not _header_like(rows[0]):
        caption = " ".join(c for c in rows[0] if c.strip())
        rows = rows[1:]
    elif filled <= 2 and len(rows) > 1:
        caption = " ".join(c for c in rows[0] if c.strip())
        rows = rows[1:]
    compact: list[list[str]] = []
    serial_kept = 0
    for row in rows:
        nonempty = [c for c in row if c.strip()]
        serial_only = bool(nonempty) and all(re.fullmatch(r"\d+", c.strip()) for c in nonempty)
        if serial_only:
            serial_kept += 1
            if serial_kept > 1:
                continue
        compact.append(row)
    rows = compact or rows
    width = max(len(r) for r in rows)
    padded = [r + [""] * (width - len(r)) for r in rows]
    header = [c or " " for c in padded[0]]
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    for row in padded[1:]:
        lines.append("| " + " | ".join(row) + " |")
    md = "\n".join(lines)
    return f"{caption}\n{md}".strip() if caption else md


def cleanup_ocr_text(text: str) -> str:
    text = text.replace("〈", "（").replace("〉", "）").replace("﹙", "（").replace("﹚", "）")
    text = re.sub(r"出国\s*[（(]?\s*境\s*[）)]?", "出国（境）", text)
    text = re.sub(r"第\s*([一二三四五六七八九十百零〇0-9]+)\s*([章节条])", r"第\1\2", text)
    text = text.replace("住条费", "住宿费").replace("住害费", "住宿费").replace("困组", "团组")
    text = re.sub(
        r"(信息公开制度)\s*\n+(事前不少于)",
        r"\1\n第九条 事前不少于",
        text,
    )
    return text


def ocr_page(page) -> str:
    if not TESSERACT.exists() or not (TESSDATA / "chi_sim.traineddata").exists():
        return ""
    img = page_to_pil(page)
    v_lines, h_lines = detect_grid(img)
    with tempfile.TemporaryDirectory() as tmp_name:
        tmp = Path(tmp_name)
        if is_table_grid(v_lines, h_lines):
            parts: list[str] = []
            y_top, y_bot = h_lines[0], h_lines[-1]
            if y_top > 48:
                parts.append(
                    ocr_pil(img.crop((0, 0, img.width, y_top - 4)), 4, tmp, "top.png", collapse=False)
                )
            parts.append(ocr_grid_markdown(img, v_lines, h_lines, tmp))
            if img.height - y_bot > 48:
                parts.append(
                    ocr_pil(
                        img.crop((0, y_bot + 4, img.width, img.height)),
                        4,
                        tmp,
                        "bottom.png",
                        collapse=False,
                    )
                )
            text = "\n\n".join(p for p in parts if p)
        else:
            full = tmp / "page.png"
            img.save(full)
            text = tesseract_image(full, psm=4)
    return cleanup_ocr_text(text)


def extract_page(page) -> tuple[str, bool]:
    native = (page.get_text("text") or "").strip()
    if len(native) < 80:
        ocr = ocr_page(page)
        if len(ocr) > max(len(native), 20):
            return ocr, True
    return splice_tables(page), False


def extract_pdf(path: Path) -> tuple[str, bool]:
    doc = pymupdf.open(path)
    pages = []
    ocr_pages = 0
    for i, page in enumerate(doc):
        t, used_ocr = extract_page(page)
        if used_ocr:
            ocr_pages += 1
        pages.append(f"\n\n===== PAGE {i + 1} =====\n{t}")
    doc.close()
    return "".join(pages), ocr_pages == len(pages) and ocr_pages > 0


def cleanup_travel_article_12(text: str) -> str:
    """Fallback if a housing-furniture table still leaked into 第十二条."""
    marker = "（四）出差津贴具体列表如下："
    if marker not in text:
        return text
    head, rest = text.split(marker, 1)
    table_start = rest.find("| 出差类别")
    if table_start < 0:
        table_start = rest.find("出差类别")
    if table_start < 0:
        return text
    chunk = rest[table_start:].lstrip()
    if not chunk.startswith("|"):
        chunk = "| " + chunk
    return head + marker + "\n" + chunk


SPLIT_RE = re.compile(
    r"(?<![\u4e00-\u9fffA-Za-z0-9])(?=第[一二三四五六七八九十百零〇0-9]+章)"
    r"|(?<![\u4e00-\u9fffA-Za-z0-9])(?=第[一二三四五六七八九十百零〇0-9]+条)"
    r"|(?<![\u4e00-\u9fffA-Za-z0-9])(?=附件[一二三四五六七八九十0-9]+[：:]?)"
    r"|(?<![\u4e00-\u9fffA-Za-z0-9])(?=版本号)"
)


def chapter_for_article(doc_id: str, n: int) -> tuple[str, str]:
    for lo, hi, chap in ARTICLE_TO_CHAPTER.get(doc_id, []):
        if lo <= n <= hi:
            title = CHAPTER_TITLES.get(doc_id, {}).get(chap, "")
            return chap, title
    return "", ""


def split_clauses(doc_id: str, meta: dict, text: str) -> list[dict]:
    if len(text) < 80:
        return [
            {
                "id": f"{doc_id}:扫描件",
                "doc_id": doc_id,
                "doc_title": meta["title"],
                "doc_no": meta["doc_no"],
                "clause_no": "扫描件",
                "level": "file",
                "chapter": "",
                "chapter_title": "",
                "breadcrumb": f"《{meta['title']}》> 扫描件未能抽取正文",
                "title": "扫描件未能抽取正文",
                "text": (
                    f"《{meta['title']}》（{meta['doc_no']}）为扫描版 PDF，"
                    "本 DEMO 未能 OCR 出条款原文。涉及因公出国（境）标准时，"
                    "应明确告知未找到可引用原文，建议查阅纸质/可检索版本或咨询综合部。"
                ),
                "has_table": False,
                "keywords": ["因公出国", "出境", "扫描件"],
            }
        ]

    parts = [p.strip() for p in SPLIT_RE.split(text) if p and p.strip()]
    clauses: list[dict] = []
    seen: dict[str, int] = {}
    for part in parts:
        m_art = re.match(r"(第[一二三四五六七八九十百零〇0-9]+条)", part)
        m_ch = re.match(r"(第[一二三四五六七八九十百零〇0-9]+章)", part)
        m_ax = re.match(r"(附件\s*[一二三四五六七八九十0-9]*)", part)
        if m_art:
            clause_no = m_art.group(1)
            n = cn_to_int(re.sub(r"[第条]", "", clause_no))
            chap, chap_title = chapter_for_article(doc_id, n)
            body = part
            if doc_id == "3-1-13" and n == 12:
                body = cleanup_travel_article_12(part)
            seen[clause_no] = seen.get(clause_no, 0) + 1
            suffix = f"-{seen[clause_no]}" if seen[clause_no] > 1 else ""
            cid = f"{doc_id}:{clause_no}{suffix}"
            title = clause_no
            breadcrumb = f"《{meta['title']}》> {chap} {chap_title} > {clause_no}".replace("  ", " ")
            has_table = ("|" in body and "---" in body) or any(
                k in body for k in ("标准如下", "具体列表", "上限", "一线城市", "二线城市")
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
                    "title": title,
                    "text": body,
                    "has_table": has_table,
                    "keywords": [],
                }
            )
        elif m_ax:
            ax = re.sub(r"\s+", "", m_ax.group(1))
            cid = f"{doc_id}:{ax}"
            clauses.append(
                {
                    "id": cid,
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
                    "keywords": ["附件", "城市", "旺季"] if doc_id == "3-1-13" else ["附件"],
                }
            )
        elif part.startswith("版本号"):
            cid = f"{doc_id}:版本修订"
            clauses.append(
                {
                    "id": cid,
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
            continue
    return merge_false_splits(clauses)


def merge_false_splits(clauses: list[dict]) -> list[dict]:
    """Cross-references like '根据本制度第六条' must not become new atoms."""
    out: list[dict] = []
    for c in clauses:
        no = c["clause_no"]
        if re.search(r"-\d+$", no) and out and out[-1]["level"] == "clause":
            out[-1]["text"] = out[-1]["text"].rstrip() + "\n" + c["text"]
            continue
        if no in {"附件一", "附件二"} and len(c["text"]) < 80:
            continue
        out.append(c)
    return out


def write_markdown(doc_id: str, meta: dict, clauses: list[dict]) -> None:
    lines = [
        f"# 《{meta['title']}》",
        f"- 文号：{meta['doc_no']}",
        f"- 生效：{meta.get('effective', '')}",
        f"- 文件：{meta['filename']}",
        "",
    ]
    for c in clauses:
        lines.append(f"## {c['breadcrumb']}")
        lines.append(f"<!-- id: {c['id']} -->")
        lines.append("")
        lines.append(c["text"])
        lines.append("")
    path = OUT_DIR / f"{doc_id}.md"
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (ROOT / "data").mkdir(parents=True, exist_ok=True)
    all_clauses: list[dict] = []
    pdfs = {p.name: p for p in PDF_DIR.glob("*.pdf")}
    for doc_id, meta in DOC_META.items():
        pdf = pdfs.get(meta["filename"])
        if not pdf:
            raise FileNotFoundError(meta["filename"])
        raw, scanned = extract_pdf(pdf)
        if scanned:
            meta = {**meta, "scanned": True}
        raw_path = OUT_DIR / f"{doc_id}.raw.txt"
        raw_path.write_text(raw, encoding="utf-8")
        text = normalize_text(raw)
        clauses = split_clauses(doc_id, meta, text)
        write_markdown(doc_id, meta, clauses)
        all_clauses.extend(clauses)
        print(f"{doc_id} 《{meta['title']}》 clauses={len(clauses)} chars={len(text)} ocr_all={scanned}")
        for c in clauses[:8]:
            print(f"  {c['id']}  {c['breadcrumb'][:60]}  {len(c['text'])}c")
        if len(clauses) > 8:
            print(f"  ... {len(clauses) - 8} more")

    with CLAUSES_PATH.open("w", encoding="utf-8") as f:
        for c in all_clauses:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    DOCS_META_PATH.write_text(json.dumps(DOC_META, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {len(all_clauses)} clauses -> {CLAUSES_PATH}")


if __name__ == "__main__":
    main()
