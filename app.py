"""
AgentLoop demo app — FastAPI backend.

The demo is a guided 3-step loop:
  1. Visitor asks a question → agent gives a confidently wrong answer
  2. Visitor provides the correct answer → AgentLoop stores it as memory
  3. Visitor asks again → agent now answers correctly (memory retrieved)

Each visitor gets a unique user_id from the frontend (sessionStorage). All
memories are scoped to that user_id and tagged "demo" so they only affect
that visitor's session and can be cleaned up periodically.

All three steps hit real AgentLoop endpoints (search, annotate). Nothing
is simulated. The demo is a live integration, not a mock.
"""
import os
import secrets
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from openai import OpenAI
from agentloop import AgentLoop
from agentloop_openai import wrap_openai

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

# Single AgentLoop client, default URL (api.getagentloop.io).
loop = AgentLoop(api_key=AGENTLOOP_API_KEY)

# Wrapped OpenAI client. The wrapper auto-searches before each call and
# auto-logs the turn after. We pass user_id per-request via the agentloop
# field so each visitor's session is isolated.
raw_openai = OpenAI(api_key=OPENAI_API_KEY)
wrapped_openai = wrap_openai(raw_openai, loop=loop)

# The agent's persona. Deliberately generic — no fake company. Domain-agnostic.
# The system prompt tells the model to invent plausible-but-wrong specifics
# when asked, which is exactly the failure mode AgentLoop solves.
SYSTEM_PROMPT = (
    "You are a customer support assistant. Answer in 1-2 sentences, "
    "directly and confidently. If the trusted facts below contain relevant "
    "information, use it verbatim. Otherwise answer based on common "
    "knowledge — never refuse to answer.\n\n"
    "Trusted facts from prior corrections:\n{memories}"
)

# ---- FastAPI app ----------------------------------------------------------

app = FastAPI(title="AgentLoop Demo")


# ---- /api/ask -------------------------------------------------------------

class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=500)
    user_id: str = Field(..., min_length=1, max_length=64)


class AskResponse(BaseModel):
    answer: str
    memories_used: int  # How many memories were retrieved + injected


@app.post("/api/ask", response_model=AskResponse)
def ask(req: AskRequest):
    """Step 1 / Step 3 — ask the agent a question.

    Searches AgentLoop for relevant past corrections from THIS visitor
    (scoped via user_id), injects them into the system prompt, then asks
    the LLM. The wrapped client also auto-logs the turn for review.

    Identical code path for Step 1 (no memories yet → wrong answer) and
    Step 3 (memory exists → correct answer). The only difference is the
    state of the visitor's memory pool.
    """
    try:
        # Manually search so we can show the count in the response.
        # The wrapped client would also auto-search, but it doesn't expose
        # how many memories it found. Doing it explicitly here gives us the
        # number for the UI badge.
        memories = loop.search(
            req.question,
            user_id=req.user_id,
            limit=3,
            tags=["demo"],
        )
        memory_block = (
            "\n".join(f"- {m.fact}" for m in memories)
            if memories
            else "(no prior corrections yet)"
        )
        system = SYSTEM_PROMPT.format(memories=memory_block)

        completion = wrapped_openai.chat.completions.create(
            model=OPENAI_MODEL,
            temperature=0.3,
            max_tokens=120,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": req.question},
            ],
            # Per-call AgentLoop options. user_id scopes auto-logging.
            # We pass tags so demo turns are easy to find/clean in the dashboard.
            agentloop={
                "user_id": req.user_id,
                "tags": ["demo"],
            },
        )
        answer = completion.choices[0].message.content.strip()
        return AskResponse(answer=answer, memories_used=len(memories))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ask failed: {e}")


# ---- /api/correct ---------------------------------------------------------

class CorrectRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=500)
    agent_response: str = Field(..., min_length=1, max_length=2000)
    correction: str = Field(..., min_length=1, max_length=1000)
    user_id: str = Field(..., min_length=1, max_length=64)


class CorrectResponse(BaseModel):
    annotation_id: str
    memory_id: str | None
    # When a visitor saves a new correction, we mint a fresh user_id and
    # save the annotation under it. The frontend then swaps to this new
    # ID for subsequent /ask calls. Net effect: only the LATEST correction
    # is reachable from this browser tab — older corrections (e.g. from
    # someone correcting twice and changing their mind) still exist in the
    # backend but are scoped to old user_ids this tab no longer uses, so
    # the demo always reflects the user's most recent correction. This
    # sidesteps "which conflicting memory wins?", which is a real product
    # question still being decided — see HANDOVER_5 §"product gaps".
    new_user_id: str


@app.post("/api/correct", response_model=CorrectResponse)
def correct(req: CorrectRequest):
    """Step 2 — record the visitor's correction.

    Creates an annotation directly (bypassing the review queue) and tags
    it with a FRESH user_id (returned to the frontend, which swaps to it).
    Annotations from earlier corrections in the same browser session stay
    in the backend but are scoped to user_ids the tab no longer uses, so
    only the latest correction is reachable on the next /api/ask call.
    """
    try:
        # Mint the fresh user_id BEFORE saving so the annotation goes
        # directly into the new scope. No need to ever delete the old one.
        new_user_id = "demo_" + secrets.token_urlsafe(6)
        result = loop.annotate(
            question=req.question,
            agent_response=req.agent_response,
            correction=req.correction,
            rating="incorrect",
            root_cause="context",
            user_id=new_user_id,
            tags=["demo"],
            reviewer="demo-visitor",
        )
        return CorrectResponse(
            annotation_id=result.annotation_id,
            memory_id=result.memory_id,
            new_user_id=new_user_id,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"correct failed: {e}")


# ---- /api/health ----------------------------------------------------------

@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "model": OPENAI_MODEL,
        "agentloop_configured": bool(AGENTLOOP_API_KEY),
        "openai_configured": bool(OPENAI_API_KEY),
    }


# ---- Static UI ------------------------------------------------------------

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