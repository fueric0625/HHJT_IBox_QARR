# 出差制度智能体 DEMO

用**分级目录 + 工具调用 + 渐进式披露**回答出差相关制度问题。本阶段没有向量库、没有 BM25。前后端用 **SSE**，不用 WebSocket。

第一轮冻结见 [方案0-5步成果说明_v1.md](方案0-5步成果说明_v1.md)。第二轮（准确率/速度）见 [方案0-5步成果说明_v2.md](方案0-5步成果说明_v2.md)。第三轮（真流式 + 添加 PDF）见 [方案0-5步成果说明_v3.md](方案0-5步成果说明_v3.md)。第四轮（目录路由后再调工具）见 [方案0-5步成果说明_v4.md](方案0-5步成果说明_v4.md)。

## 知识库

`files/出差相关制度` 中 8 份 PDF（2022/2018）。评测金标准已按这些原文重标，不再使用评测表里的 2025 年出差规定或《付款管理规定》。

`3-6-1 因公出国（境）管理规定` 为扫描件。抽取时用本机 Tesseract（`chi_sim+eng`）OCR：先按框线切单元格再识别表格，正文页提高对比度后按块识别。数字版 PDF 的表格用 PyMuPDF `find_tables` 抽成 Markdown，避免把单元格读成乱序长句。流程图/空白表格页若几乎没有可复制文字，同样走 OCR。

中文语言包放在 `demo/data/tessdata/chi_sim.traineddata`。Tesseract 安装目录约定为 `C:\Program Files\Tesseract-OCR`。依赖含 Pillow，用于扫描页去灰底和单元格裁切。

## 一键重建数据

```powershell
cd E:\ibox_qarr\demo
python scripts\run_pipeline.py
```

流水线：`PDF → 条款 JSONL/Markdown → catalog.json（LLM 摘要 + 条款 ID 校验 + 易混点回写）→ testcases.json → 工具冒烟`。

只刷新目录摘要：

```powershell
python scripts\build_catalog.py --llm
python scripts\build_catalog.py --hints-only   # 可选：保留条款摘要，只回写文件/章易混点
```

## 启动 DEMO

```powershell
copy .env.example .env
# 按需修改 LLM_BASE_URL / LLM_MODEL
python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

浏览器打开 `http://127.0.0.1:8000`。聊天走 `POST /api/chat`（`text/event-stream`）：`route_start` / `route` / `round_start` / `tool_call` / `tool_result` / `answer_start` / `token` / `done` / `error`。问题先对照目录判断方向并圈章节，再调工具；最终作答轮一旦开始即推 `answer_start`，随后 `token` 为模型真增量（不再按 24 字切块）。

侧栏可 **添加 PDF**：`POST /api/ingest`（multipart，SSE：`progress` / `done` / `error`）。抽取拆条后写回 `clauses.jsonl` / `catalog.json` 并热加载，不必重启 uvicorn。文件列表见 `GET /api/files`。

方案第 0–5 步第一轮成果见 [方案0-5步成果说明_v1.md](方案0-5步成果说明_v1.md)，第二轮见 [方案0-5步成果说明_v2.md](方案0-5步成果说明_v2.md)，第三轮见 [方案0-5步成果说明_v3.md](方案0-5步成果说明_v3.md)，第四轮见 [方案0-5步成果说明_v4.md](方案0-5步成果说明_v4.md)。

## 评测

天花板试跑（通读全文、不经工具）见 [eval/ceiling_report.md](eval/ceiling_report.md)。

对 17 条跑 Agent：

```powershell
python eval\run_eval.py
```

产出 `eval/eval_report.md` 与 `eval/eval_results.json`。

17 题评测与上一轮分开存放：第二轮 [eval/eval_report_v2.md](eval/eval_report_v2.md)；第四轮（目录路由）[eval/eval_report_v4.md](eval/eval_report_v4.md)。对照见 [方案0-5步成果说明_v4.md](方案0-5步成果说明_v4.md)。重跑不覆盖第二轮：`python eval\run_eval.py --tag v4`。天花板通读结论见 [eval/ceiling_report.md](eval/ceiling_report.md)。

## 工具

- `list_catalog` 看文件/章
- `list_section` 看条款标题和摘要
- `read_clause` 读原文（作答前必须）
- `lookup_keyword` 字面检索，纠偏用

每次模型补全会丢掉旧的目录大段结果，只保留最近四次条款原文，避免撑满 32K。提问后先做目录路由（方向 + 拟引用章节），再注入字面检索线索；不必再调用 `list_catalog` 根节点。
