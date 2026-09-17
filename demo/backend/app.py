from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .agent import ask, ask_stream
from .config import ROOT
from .store import load_catalog

app = FastAPI(title="出差制度智能体 DEMO")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatBody(BaseModel):
    question: str
    history: list[dict] | None = None


@app.get("/api/health")
def health():
    cat = load_catalog()
    return {"ok": True, "files": len(cat.get("nodes", [])), "clauses": len(cat.get("valid_clause_ids", []))}


@app.get("/api/catalog")
def catalog_root():
    cat = load_catalog()
    return [{"id": n["id"], "title": n["title"], "summary": n["summary"]} for n in cat["nodes"]]


@app.post("/api/chat")
def chat(body: ChatBody):
    def gen():
        try:
            for event in ask_stream(body.question, history=body.history):
                yield f"event: {event['event']}\ndata: {json.dumps(event['data'], ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"event: error\ndata: {json.dumps({'message': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.post("/api/chat_sync")
def chat_sync(body: ChatBody):
    return ask(body.question, history=body.history)


frontend = ROOT / "frontend"
if frontend.exists():
    app.mount("/", StaticFiles(directory=frontend, html=True), name="frontend")
