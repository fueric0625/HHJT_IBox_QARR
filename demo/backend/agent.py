from __future__ import annotations

import json
import time
from collections.abc import Iterator
from typing import Any

from openai import OpenAI
import httpx

from .config import KEEP_FULL_CLAUSES, LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, MAX_ROUNDS, MAX_TOOL_CALLS
from .prompts import system_prompt
from .route import ROUTE_PROMPT, catalog_outline_text, format_route_block, parse_route_text
from .tools import CURRENT_QUERY, OPENAI_TOOLS, TOOL_IMPL, lookup_nav_hits, root_catalog_brief


def _client() -> OpenAI:
    http_client = httpx.Client(trust_env=False, timeout=120.0)
    return OpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY, http_client=http_client)


def _parse_args(raw: str | dict | None) -> dict:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    raw = str(raw).strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        if not raw.startswith("{"):
            raw = "{" + raw
        if not raw.endswith("}"):
            raw = raw + "}"
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}


def _tool_summary(name: str, arguments: dict, result: str) -> str:
    try:
        data = json.loads(result)
    except json.JSONDecodeError:
        data = {}
    if name == "read_clause":
        return data.get("breadcrumb") or arguments.get("clause_id") or name
    if name in {"list_catalog", "list_section"}:
        kids = data.get("children") or data.get("items") or []
        titles = [c.get("title") for c in kids[:6] if c.get("title")]
        return f"{name} -> " + "、".join(titles)
    if name == "lookup_keyword":
        hits = data.get("hits") or []
        return f"keyword hits: {len(hits)}"
    return name


def _trim_messages(messages: list[dict]) -> list[dict]:
    """Each model call can use a different context window.

    Keep system + original user question. Collapse old list_* results.
    Keep only the latest KEEP_FULL_CLAUSES read_clause full texts.
    """
    if len(messages) <= 2:
        return messages
    system, user, *rest = messages
    read_indexes = [
        i
        for i, m in enumerate(rest)
        if m.get("role") == "tool" and m.get("name") == "read_clause"
    ]
    keep_reads = set(read_indexes[-KEEP_FULL_CLAUSES:])
    trimmed: list[dict] = [system, user]
    for i, m in enumerate(rest):
        if m.get("role") != "tool":
            trimmed.append(m)
            continue
        name = m.get("name")
        content = m.get("content") or ""
        if name in {"list_catalog", "list_section", "lookup_keyword"}:
            try:
                data = json.loads(content)
                slim = {
                    "trimmed": True,
                    "name": name,
                    "current": (data.get("current") or {}).get("title") or (data.get("current") or {}).get("id"),
                    "ids": [
                        (c.get("id"), c.get("title"))
                        for c in (data.get("children") or data.get("items") or data.get("hits") or [])
                    ],
                }
                content = json.dumps(slim, ensure_ascii=False)
            except json.JSONDecodeError:
                content = content[:400]
        elif name == "read_clause" and i not in keep_reads:
            try:
                data = json.loads(content)
                content = json.dumps(
                    {
                        "trimmed": True,
                        "id": data.get("id"),
                        "breadcrumb": data.get("breadcrumb"),
                        "note": "原文已读过，需要细节请再次 read_clause",
                    },
                    ensure_ascii=False,
                )
            except json.JSONDecodeError:
                content = content[:200]
        trimmed.append({**m, "content": content})
    return trimmed


def _run_tools(tool_calls: list[dict]) -> list[dict]:
    events = []
    for tc in tool_calls:
        name = tc["name"]
        args = _parse_args(tc.get("arguments"))
        impl = TOOL_IMPL.get(name)
        if not impl:
            result = json.dumps({"error": f"未知工具 {name}"}, ensure_ascii=False)
        else:
            try:
                result = impl(**args)
            except Exception as e:
                result = json.dumps({"error": str(e)}, ensure_ascii=False)
        events.append(
            {
                "id": tc["id"],
                "name": name,
                "arguments": args,
                "result": result,
                "summary": _tool_summary(name, args, result),
            }
        )
    return events


def ask(question: str, history: list[dict] | None = None) -> dict[str, Any]:
    """Non-streaming path for eval."""
    tokens: list[str] = []
    trace: list[dict] = []
    citations: list[str] = []
    for event in ask_stream(question, history=history):
        et = event["event"]
        data = event["data"]
        if et == "token":
            tokens.append(data.get("text", ""))
        elif et == "route":
            trace.append({"type": "route", **data})
        elif et == "tool_call":
            trace.append({"type": "call", **data})
        elif et == "tool_result":
            trace.append({"type": "result", **data})
            if data.get("name") == "read_clause":
                citations.append(data.get("summary") or "")
        elif et == "error":
            return {"answer": "", "error": data.get("message"), "trace": trace, "citations": citations}
        elif et == "done":
            return {
                "answer": data.get("answer") or "".join(tokens),
                "trace": trace,
                "citations": [c for c in citations if c],
                "rounds": data.get("rounds"),
                "tool_calls": data.get("tool_calls"),
                "elapsed_ms": data.get("elapsed_ms"),
            }
    return {"answer": "".join(tokens), "trace": trace, "citations": citations}


def _complete_kwargs(messages: list[dict], use_tools: bool, stream: bool, temperature: float) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "model": LLM_MODEL,
        "messages": messages,
        "temperature": temperature,
        "stream": stream,
        "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
    }
    if use_tools:
        kwargs["tools"] = OPENAI_TOOLS
        kwargs["tool_choice"] = "auto"
    return kwargs


def _complete_stream(client: OpenAI, messages: list[dict], use_tools: bool):
    kwargs = _complete_kwargs(messages, use_tools=use_tools, stream=True, temperature=0.1)
    try:
        return client.chat.completions.create(**kwargs)
    except Exception:
        kwargs.pop("extra_body", None)
        return client.chat.completions.create(**kwargs)


def _complete_text(client: OpenAI, messages: list[dict]) -> str:
    kwargs = _complete_kwargs(messages, use_tools=False, stream=False, temperature=0)
    try:
        resp = client.chat.completions.create(**kwargs)
    except Exception:
        kwargs.pop("extra_body", None)
        resp = client.chat.completions.create(**kwargs)
    choice = resp.choices[0].message if resp.choices else None
    return (choice.content or "").strip() if choice else ""


def _plan_question(client: OpenAI, question: str) -> dict[str, Any]:
    messages = [
        {
            "role": "system",
            "content": ROUTE_PROMPT.replace("{CATALOG}", catalog_outline_text()),
        },
        {"role": "user", "content": question},
    ]
    try:
        raw = _complete_text(client, messages)
    except Exception:
        raw = ""
    plan = parse_route_text(raw)
    if not plan.get("candidates"):
        plan = {
            **plan,
            "direction": plan.get("direction") or "目录预判失败，改用根目录与字面检索",
            "candidates": [],
        }
    return plan


def ask_stream(question: str, history: list[dict] | None = None) -> Iterator[dict]:
    client = _client()
    started = time.perf_counter()
    q_token = CURRENT_QUERY.set(question)

    def elapsed_ms() -> int:
        return int((time.perf_counter() - started) * 1000)

    try:
        messages: list[dict] = [{"role": "system", "content": system_prompt()}]
        if history:
            messages.extend(history)
        yield {"event": "route_start", "data": {"elapsed_ms": elapsed_ms()}}
        try:
            plan = _plan_question(client, question)
        except Exception as e:
            plan = {
                "direction": "路由失败，改用根目录与字面检索",
                "reason": str(e),
                "candidates": [],
                "maybe_unanswerable": False,
            }
        yield {
            "event": "route",
            "data": {
                "direction": plan.get("direction"),
                "reason": plan.get("reason"),
                "candidates": plan.get("candidates") or [],
                "maybe_unanswerable": bool(plan.get("maybe_unanswerable")),
                "elapsed_ms": elapsed_ms(),
            },
        }

        extras = [format_route_block(plan)]
        if plan.get("candidates"):
            extras.append("勿再 list_catalog 根目录。")
        else:
            extras.append(
                "制度目录根层（路由未锁定章节，勿再 list_catalog 根目录）：\n" + root_catalog_brief()
            )
        extras.append("字面检索线索（不是原文，须并行 read_clause）：\n" + lookup_nav_hits(question))
        user_content = question + "\n\n---\n" + "\n".join(extras)
        messages.append({"role": "user", "content": user_content})

        rounds = 0
        tool_count = 0
        force_answer = False

        while True:
            rounds += 1
            if force_answer:
                messages.append(
                    {
                        "role": "user",
                        "content": "已达到工具调用上限。请仅根据已经 read_clause 的原文作答；若证据不足，回答未找到并建议咨询综合部。不要再调用工具。",
                    }
                )
            ctx = _trim_messages(messages)
            yield {
                "event": "round_start",
                "data": {
                    "round": rounds,
                    "force_answer": force_answer,
                    "elapsed_ms": elapsed_ms(),
                },
            }
            answer_started = False
            if force_answer:
                answer_started = True
                yield {
                    "event": "answer_start",
                    "data": {"round": rounds, "elapsed_ms": elapsed_ms()},
                }

            try:
                stream = _complete_stream(client, ctx, use_tools=not force_answer)
            except Exception as e:
                yield {"event": "error", "data": {"message": str(e), "elapsed_ms": elapsed_ms()}}
                return

            tool_acc: dict[int, dict] = {}
            content_parts: list[str] = []
            pending: list[str] = []
            mode: str | None = None
            try:
                for chunk in stream:
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
                    tcs = getattr(delta, "tool_calls", None) or []
                    if tcs:
                        mode = "tools"
                        pending.clear()
                        for tc in tcs:
                            idx = tc.index if getattr(tc, "index", None) is not None else 0
                            slot = tool_acc.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                            if tc.id:
                                slot["id"] = tc.id
                            fn = getattr(tc, "function", None)
                            if fn:
                                if fn.name:
                                    slot["name"] += fn.name
                                if fn.arguments:
                                    slot["arguments"] += fn.arguments
                    text = delta.content or ""
                    if not text:
                        continue
                    if mode == "tools":
                        continue
                    if mode is None:
                        if not text.strip():
                            pending.append(text)
                            continue
                        mode = "content"
                    if not answer_started:
                        answer_started = True
                        yield {
                            "event": "answer_start",
                            "data": {"round": rounds, "elapsed_ms": elapsed_ms()},
                        }
                    for piece in (*pending, text):
                        content_parts.append(piece)
                        yield {"event": "token", "data": {"text": piece, "round": rounds}}
                    pending.clear()
            except Exception as e:
                yield {"event": "error", "data": {"message": str(e), "elapsed_ms": elapsed_ms()}}
                return

            raw_calls = [tool_acc[i] for i in sorted(tool_acc)] if tool_acc else []
            if raw_calls and not force_answer:
                tool_calls_msg = []
                fake = []
                for i, tc in enumerate(raw_calls):
                    args_obj = _parse_args(tc.get("arguments"))
                    args_s = json.dumps(args_obj, ensure_ascii=False)
                    cid = tc.get("id") or f"call_{i}"
                    name = tc.get("name") or ""
                    fake.append({"id": cid, "name": name, "arguments": args_s})
                    tool_calls_msg.append(
                        {
                            "id": cid,
                            "type": "function",
                            "function": {"name": name, "arguments": args_s},
                        }
                    )
                    yield {
                        "event": "tool_call",
                        "data": {
                            "name": name,
                            "arguments": args_obj,
                            "round": rounds,
                            "elapsed_ms": elapsed_ms(),
                        },
                    }
                executed = _run_tools(fake)
                messages.append({"role": "assistant", "content": "", "tool_calls": tool_calls_msg})
                for item in executed:
                    tool_count += 1
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": item["id"],
                            "name": item["name"],
                            "content": item["result"],
                        }
                    )
                    yield {
                        "event": "tool_result",
                        "data": {
                            "name": item["name"],
                            "summary": item["summary"],
                            "arguments": item["arguments"],
                            "round": rounds,
                            "elapsed_ms": elapsed_ms(),
                        },
                    }
                if rounds >= MAX_ROUNDS or tool_count >= MAX_TOOL_CALLS:
                    force_answer = True
                continue

            answer = "".join(content_parts)
            if not answer_started:
                yield {
                    "event": "answer_start",
                    "data": {"round": rounds, "elapsed_ms": elapsed_ms()},
                }
            yield {
                "event": "done",
                "data": {
                    "answer": answer,
                    "rounds": rounds,
                    "tool_calls": tool_count,
                    "elapsed_ms": elapsed_ms(),
                },
            }
            return
    finally:
        # StreamingResponse may iterate this generator in a copied context.
        try:
            CURRENT_QUERY.reset(q_token)
        except (LookupError, ValueError):
            pass
