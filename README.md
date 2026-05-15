# AgentLoop demo app

Live at `https://demo.getagentloop.io`. A guided 3-step demo of AgentLoop's
runtime learning loop:

1. **Ask** — visitor asks a question, agent answers (probably wrong)
2. **Correct** — visitor provides the right answer, AgentLoop stores it
3. **Ask again** — visitor re-asks, agent now answers correctly

Every step hits real AgentLoop endpoints. Nothing is mocked. Each visitor's
corrections are scoped to their session via `user_id`, so they only see
their own memories and corrections from other visitors don't leak in.

## Architecture

- **FastAPI backend** (`app.py`) — three endpoints: `/api/ask`, `/api/correct`, `/api/health`
- **Static frontend** (`static/`) — one HTML file, vanilla JS, no framework
- **AgentLoop integration** — uses `agentloop-py-openai` for the wrapped client; calls `loop.search()` and `loop.annotate()` directly

The wrapped OpenAI client auto-logs every turn to the review queue. The
demo also creates direct annotations (skipping review) when the visitor
clicks "Save correction" — this is what makes the memory immediately
available for the next ask.

## Local development

```bash
# Install dependencies (using uv, the project default)
uv sync

# Copy env template and fill in your keys
cp .env.example .env
# Edit .env with your AGENTLOOP_API_KEY and OPENAI_API_KEY

# Run
uv run python app.py
# or
uv run uvicorn app:app --reload --port 8000
```

Visit `http://localhost:8000`.

## Deployment

Deploys to Render via the existing service (`agentloop-demo.onrender.com`,
pointed at `demo.getagentloop.io` via Cloudflare DNS).

Push to the repo's main branch → Render auto-deploys.

If env vars need updating, do it in Render's dashboard:
- `AGENTLOOP_API_KEY` — required, the demo org's API key
- `OPENAI_API_KEY` — required
- `OPENAI_MODEL` — optional, defaults to `gpt-4o-mini`
- `AGENTLOOP_BASE_URL` — **don't set**, SDK defaults to `api.getagentloop.io`

## Memory pollution / cleanup

Each visitor's memories are tagged `demo` and scoped to a per-session
`user_id`. They accumulate in the demo org over time. At ~50 demos/day
× 1 memory each, this is ~1,500/month — fine for now.

When demo memory volume becomes a problem, add a Cloud Scheduler job
that runs daily and deletes memories where `tags` contains `demo` AND
`created_at < now() - 24h`. The backend already has the structure for
this; just needs the endpoint + scheduler.

## Design notes

The demo deliberately:

- **Has no fictional company name** — visitors project their own context
- **Uses three numbered steps**, not tabs — the visitor experiences the loop, doesn't browse alternatives
- **Shows the actual code** (Step 04 explainer) — developers can see how to integrate
- **Matches the marketing site aesthetic** — Fraunces serif, terracotta accent, paper background — so visitors arriving from `getagentloop.io` feel continuity

The system prompt instructs the model to answer confidently from training
data when no memory is present. This is what produces the "confidently
wrong" failure mode that AgentLoop solves — and what makes the demo
compelling without staging anything.
