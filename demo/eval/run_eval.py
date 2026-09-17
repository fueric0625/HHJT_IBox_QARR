"""Run 17 test cases against the agent (non-streaming) and write a comparison report."""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.agent import ask  # noqa: E402
from backend.config import TESTCASES_PATH  # noqa: E402

OUT_JSON = ROOT / "eval" / "eval_results.json"
OUT_MD = ROOT / "eval" / "eval_report.md"


def score_case(case: dict, result: dict) -> dict:
    answer = result.get("answer") or ""
    error = result.get("error")
    trace = result.get("trace") or []
    read_ids = []
    for ev in trace:
        if ev.get("type") == "result" and ev.get("name") == "read_clause":
            args = ev.get("arguments") or {}
            if args.get("clause_id"):
                read_ids.append(args["clause_id"])
    gold = case.get("gold_clause_ids") or []
    hit = [g for g in gold if g in read_ids]
    miss = [g for g in gold if g not in read_ids]
    must = case.get("gold_must_include") or []
    must_not = case.get("gold_must_not") or []
    include_ok = all(k in answer for k in must) if answer else False
    exclude_ok = all(k not in answer for k in must_not) if answer else False
    if error:
        verdict = "error"
    elif case.get("unanswerable"):
        verdict = "unanswerable_ok" if ("未在制度库中找到" in answer or "未找到" in answer) else "unanswerable_fail"
    elif gold and not hit:
        verdict = "miss_clause"
    elif must and not include_ok:
        verdict = "partial"
    elif must_not and not exclude_ok:
        verdict = "partial"
    else:
        verdict = "likely_ok"
    return {
        "id": case["id"],
        "question": case["question"],
        "ibox_score": case.get("ibox_score"),
        "ibox_verdict": case.get("ibox_verdict"),
        "bucket": case.get("bucket"),
        "gold_clause_ids": gold,
        "read_clause_ids": read_ids,
        "clause_hit": hit,
        "clause_miss": miss,
        "must_include_ok": include_ok,
        "must_not_ok": exclude_ok,
        "verdict": verdict,
        "tool_calls": result.get("tool_calls"),
        "rounds": result.get("rounds"),
        "error": error,
        "answer": answer,
    }


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    payload = json.loads(TESTCASES_PATH.read_text(encoding="utf-8"))
    rows = []
    for case in payload["cases"]:
        print(f"running {case['id']} {case['question'][:40]}", flush=True)
        try:
            result = ask(case["question"])
        except Exception as e:
            result = {"answer": "", "error": str(e), "trace": []}
        row = score_case(case, result)
        rows.append(row)
        print(f"  -> {row['verdict']} hit={row['clause_hit']}", flush=True)

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    counts = {}
    for r in rows:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    lines = [
        "# 出差制度智能体 DEMO 评测对照",
        "",
        f"- 时间：{datetime.now().isoformat(timespec='seconds')}",
        f"- 用例数：{len(rows)}",
        f"- 自动判定分布：{counts}",
        "",
        "判定说明：`likely_ok` 表示工具读到金标准条款且关键词命中，仍需人工看数字是否抄对。",
        "",
        "| ID | 分桶 | IBox | DEMO | 条款命中 | 问题 |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        q = r["question"].replace("|", "\\|")
        hit = ",".join(r["clause_hit"]) or "-"
        lines.append(
            f"| {r['id']} | {r['bucket']} | {r['ibox_score'] or '-'} / {r['ibox_verdict'] or '-'} | {r['verdict']} | {hit} | {q} |"
        )
    lines += ["", "## 逐条答案", ""]
    for r in rows:
        lines += [
            f"### {r['id']} {r['question']}",
            "",
            f"- gold: {r['gold_clause_ids']}",
            f"- read: {r['read_clause_ids']}",
            f"- IBox: {r['ibox_score']} {r['ibox_verdict']}",
            "",
            r["answer"] or r.get("error") or "(empty)",
            "",
        ]
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUT_MD}")


if __name__ == "__main__":
    main()
