from __future__ import annotations

import json

from fastapi import FastAPI, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .agent import ask, ask_stream
from .config import ROOT
from .ingest import ingest_pdf, list_files
from .store import load_catalog

app = FastAPI(title="出差制度智能体 DEMO")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


class ChatBody(BaseModel):
    question: str
    history: list[dict] | None = None


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.get("/api/health")
def health():
    cat = load_catalog()
    return {"ok": True, "files": len(cat.get("nodes", [])), "clauses": len(cat.get("valid_clause_ids", []))}


@app.get("/api/catalog")
def catalog_root():
    cat = load_catalog()
    return [{"id": n["id"], "title": n["title"], "summary": n["summary"]} for n in cat["nodes"]]


@app.get("/api/files")
def files():
    return list_files()


@app.post("/api/chat")
def chat(body: ChatBody):
    def gen():
        try:
            for event in ask_stream(body.question, history=body.history):
                yield _sse(event["event"], event["data"])
        except (LookupError, ValueError) as e:
            if "ContextVar" in str(e) or "different Context" in str(e):
                return
            yield _sse("error", {"message": str(e)})
        except Exception as e:
            yield _sse("error", {"message": str(e)})

    return StreamingResponse(gen(), media_type="text/event-stream", headers=SSE_HEADERS)


@app.post("/api/chat_sync")
def chat_sync(body: ChatBody):
    return ask(body.question, history=body.history)


@app.post("/api/ingest")
async def ingest(file: UploadFile = File(...)):
    filename = file.filename or "upload.pdf"
    content = await file.read()

    def gen():
        try:
            for event in ingest_pdf(filename, content):
                yield _sse(event["event"], event["data"])
        except Exception as e:
            yield _sse("error", {"message": str(e)})

    return StreamingResponse(gen(), media_type="text/event-stream", headers=SSE_HEADERS)


frontend = ROOT / "frontend"
if frontend.exists():
    app.mount("/", StaticFiles(directory=frontend, html=True), name="frontend")
