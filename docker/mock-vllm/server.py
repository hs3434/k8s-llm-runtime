"""Mock vLLM server — OpenAI-compatible /v1/chat/completions echo.

For demo / CI when real vLLM can't run (no GPU, image too large, etc).
Echoes the user's last message with a fixed prefix; mimics the
fields a real vLLM server would return.
"""
from __future__ import annotations

import os
import time
import uuid

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="mock-vllm", version="0.0.1")

MOCK_MODEL = os.environ.get("MOCK_MODEL_NAME", "mock-model")
MOCK_PREFIX = os.environ.get("MOCK_PREFIX", "[mock] ")


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: str
    messages: list[ChatMessage]
    temperature: float = 1.0
    max_tokens: int = 1024
    stream: bool = False


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/chat/completions")
async def chat_completions(req: ChatRequest) -> dict[str, object]:
    last_user = next(
        (m.content for m in reversed(req.messages) if m.role == "user"),
        "",
    )
    text = f"{MOCK_PREFIX}echo: {last_user}"
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": req.model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            },
        ],
        "usage": {
            "prompt_tokens": sum(len(m.content) for m in req.messages) // 4,
            "completion_tokens": len(text) // 4,
            "total_tokens": 0,
        },
    }