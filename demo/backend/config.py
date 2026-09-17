from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

DATA_DIR = ROOT / "data"
CLAUSES_PATH = DATA_DIR / "clauses.jsonl"
CATALOG_PATH = DATA_DIR / "catalog.json"
TESTCASES_PATH = DATA_DIR / "testcases.json"

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://172.16.120.211:31210/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "dummy")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen")
MAX_ROUNDS = int(os.getenv("MAX_ROUNDS", "6"))
MAX_TOOL_CALLS = int(os.getenv("MAX_TOOL_CALLS", "10"))
KEEP_FULL_CLAUSES = int(os.getenv("KEEP_FULL_CLAUSES", "4"))
