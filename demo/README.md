# 出差制度智能体 DEMO

用**分级目录 + 工具调用 + 渐进式披露**回答出差相关制度问题。本阶段没有向量库、没有 BM25。前后端用 **SSE**，不用 WebSocket。

## 知识库

`files/出差相关制度` 中 8 份 PDF（2022/2018）。评测金标准已按这些原文重标，不再使用评测表里的 2025 年出差规定或《付款管理规定》。

`3-6-1 因公出国（境）管理规定` 为扫描件。抽取时用本机 Tesseract（`chi_sim+eng`）OCR：先按框线切单元格再识别表格，正文页提高对比度后按块识别。数字版 PDF 的表格用 PyMuPDF `find_tables` 抽成 Markdown，避免把单元格读成乱序长句。流程图/空白表格页若几乎没有可复制文字，同样走 OCR。

中文语言包放在 `demo/data/tessdata/chi_sim.traineddata`。Tesseract 安装目录约定为 `C:\Program Files\Tesseract-OCR`。依赖含 Pillow，用于扫描页去灰底和单元格裁切。

## 一键重建数据

```powershell
cd E:\ibox_qarr\demo
python scripts\run_pipeline.py
```

流水线：`PDF → 条款 JSONL/Markdown → catalog.json（条款 ID 校验）→ testcases.json → 工具冒烟`。

用公司大模型刷新目录摘要（可选）：

```powershell
python scripts\build_catalog.py --llm
```

## 启动 DEMO

```powershell
copy .env.example .env
# 按需修改 LLM_BASE_URL / LLM_MODEL
python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

浏览器打开 `http://127.0.0.1:8000`。聊天走 `POST /api/chat`（`text/event-stream`）：`token` / `tool_call` / `tool_result` / `done` / `error`。

方案第 0–5 步的成果冻结说明见 [方案0-5步成果说明.md](方案0-5步成果说明.md)。

## 评测

天花板试跑（通读全文、不经工具）见 [eval/ceiling_report.md](eval/ceiling_report.md)。

对 17 条跑 Agent：

```powershell
python eval\run_eval.py
```

产出 `eval/eval_report.md` 与 `eval/eval_results.json`。

本轮 17 条自动判定：`likely_ok` 8、`partial` 3、`miss_clause` 5、`unanswerable_fail` 1。对照表见评测报告。天花板通读结论见 [eval/ceiling_report.md](eval/ceiling_report.md)。

## 工具

- `list_catalog` 看文件/章
- `list_section` 看条款标题和摘要
- `read_clause` 读原文（作答前必须）
- `lookup_keyword` 字面检索，纠偏用

每次模型补全会丢掉旧的目录大段结果，只保留最近两次条款原文，避免撑满 32K。
