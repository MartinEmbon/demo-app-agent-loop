"""
AgentLoop demo app — FastAPI service.

Two routes, two integration patterns:

- POST /api/chat    — uses agentloop-py-langchain (Runnable + callback handler).
                      Demonstrates "drop AgentLoop into your existing LCEL chain."
- POST /api/triage  — uses agentloop-py-openai (wrapped client).
                      Demonstrates "drop AgentLoop in front of your OpenAI client."

Both routes log turns to the same demo org (whichever AGENTLOOP_API_KEY belongs to)
so they show up in the same dashboard during a live demo.
"""
import os
import json
import uuid
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
load_dotenv()  # Loads .env into os.environ. Must run before any code that reads env.

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from openai import OpenAI
from agentloop import AgentLoop
from agentloop_openai import wrap_openai

# LangChain pieces for the chat tab
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from agentloop_langchain import (
    AgentLoopCallbackHandler,
    AgentLoopMemoryInjector,
)

# ---- Config ---------------------------------------------------------------

AGENTLOOP_API_KEY = os.environ.get("AGENTLOOP_API_KEY", "").strip()
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini").strip()

if not AGENTLOOP_API_KEY:
    raise RuntimeError(
        "AGENTLOOP_API_KEY is not set. Copy .env.example to .env and fill it in."
    )
if not OPENAI_API_KEY:
    raise RuntimeError(
        "OPENAI_API_KEY is not set. Copy .env.example to .env and fill it in."
    )

# AgentLoop SDK uses its baked-in default URL when AGENTLOOP_BASE_URL is unset,
# which points at the deployed backend. Fine for both local dev and production.
loop = AgentLoop(api_key=AGENTLOOP_API_KEY)

# ---- Tab 1: chat (LangChain) ---------------------------------------------
# The full magic-loop pattern: an injector retrieves memories before the LLM
# call, a callback handler logs the turn after.

CHAT_SYSTEM_PROMPT = (
    "You are a customer support agent for LumaBank, a fictional Brazilian "
    "fintech. Be helpful, concise, and answer in 2-3 sentences. If you don't "
    "know a specific LumaBank policy or limit, say so honestly rather than "
    "guessing.\n\n"
    "Trusted facts from prior corrections:\n"
    "{agentloop_memories}"
)

chat_prompt = ChatPromptTemplate.from_messages([
    ("system", CHAT_SYSTEM_PROMPT),
    ("user", "{question}"),
])

chat_llm = ChatOpenAI(
    model=OPENAI_MODEL,
    api_key=OPENAI_API_KEY,
    temperature=0.2,
).with_config(callbacks=[AgentLoopCallbackHandler(loop=loop)])

chat_chain = (
    AgentLoopMemoryInjector(loop=loop, query_field="question")
    | chat_prompt
    | chat_llm
)

# ---- Tab 2: triage (direct OpenAI wrapper) -------------------------------
# Classification task: ticket text → one of {Billing, Technical, Fraud, Account}.
# Uses wrap_openai so AgentLoop sees both the input (ticket) and output (label).

raw_openai = OpenAI(api_key=OPENAI_API_KEY)
wrapped_openai = wrap_openai(raw_openai, loop=loop)

TRIAGE_CATEGORIES = ["Billing", "Technical", "Fraud", "Account", "Access"]
TRIAGE_SYSTEM_PROMPT = (
    "You are a customer support ticket classifier for LumaBank, a Brazilian "
    "fintech. Classify each ticket into exactly one of these categories: "
    f"{', '.join(TRIAGE_CATEGORIES)}.\n\n"
    "Respond with ONLY the category name, nothing else. No explanation, no "
    "punctuation, just one word from the list above."
)

# ---- FastAPI app ----------------------------------------------------------

app = FastAPI(title="AgentLoop Demo")


class ChatRequest(BaseModel):
    question: str
    user_id: str | None = None  # Optional. UI generates a per-session id.


class ChatResponse(BaseModel):
    answer: str
    turn_id: str | None = None


class TriageRequest(BaseModel):
    ticket: str
    user_id: str | None = None


class TriageResponse(BaseModel):
    category: str
    raw_answer: str
    turn_id: str | None = None


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    """Chat tab: LangChain chain wrapped with AgentLoop injector + callback.

    Note: we deliberately do NOT pass user_id to AgentLoop. The SDK uses the
    same user_id for both memory search and turn logging, and the search
    endpoint filters retrieved memories by user_id when one is provided.
    For a public demo where many users share the same corrections, that
    scoping would prevent any memory from being retrieved (the asker's
    user_id won't match the user_id of the original annotation).

    Tags are still useful for filtering demo turns in the dashboard.
    """
    try:
        result = chat_chain.invoke(
            {"question": req.question},
            config={"metadata": {"agentloop": {
                "tags": ["demo", "chat"],
            }}},
        )
        # ChatOpenAI returns an AIMessage; .content is the text.
        answer = result.content if hasattr(result, "content") else str(result)
        return ChatResponse(answer=answer, turn_id=None)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"chat failed: {e}")


@app.post("/api/triage", response_model=TriageResponse)
def triage(req: TriageRequest):
    """Triage tab: classify a ticket via the wrapped OpenAI client.

    Same user_id-omission reason as /api/chat — see that route's docstring.
    """
    try:
        completion = wrapped_openai.chat.completions.create(
            model=OPENAI_MODEL,
            temperature=0,
            max_tokens=20,
            messages=[
                {"role": "system", "content": TRIAGE_SYSTEM_PROMPT},
                {"role": "user", "content": req.ticket},
            ],
            agentloop={
                "tags": ["demo", "triage"],
            },
        )
        raw = completion.choices[0].message.content.strip()
        # Best-effort normalisation: pick the matching category if the model
        # added punctuation or extra words. Falls back to raw if no match.
        category = next(
            (c for c in TRIAGE_CATEGORIES if c.lower() in raw.lower()),
            raw,
        )
        return TriageResponse(category=category, raw_answer=raw, turn_id=None)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"triage failed: {e}")


@app.get("/api/health")
def health():
    """Sanity endpoint: confirms env is configured and the SDK can talk to the backend."""
    return {
        "status": "ok",
        "model": OPENAI_MODEL,
        "agentloop_configured": bool(AGENTLOOP_API_KEY),
        "openai_configured": bool(OPENAI_API_KEY),
    }


# ---- Static UI ------------------------------------------------------------
# Serve everything in static/ at /static/*, and index.html at /.

STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def index():
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        return {"error": "static/index.html not built yet"}
    return FileResponse(str(index_path))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
