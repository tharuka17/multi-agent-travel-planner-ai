# TripWeaver — MCP-Based Multi-Agent Travel Planner

TripWeaver is a conversational travel planning assistant. A traveller chats in
natural language; a LangGraph-orchestrated set of agents (General QA, Hotel,
Flight) interprets intent, reaches live hotel/flight services **only through
MCP (Model Context Protocol) tools**, and streams back a coherent reply.

## Architecture

```
                     User input
                         │
                         ▼
                  ┌─────────────┐
                  │   Router    │   (intent classification only)
                  └──────┬──────┘
             ┌───────────┼───────────┐
             ▼            ▼           ▼
     ┌───────────┐ ┌────────────┐ ┌──────────────┐
     │Hotel Agent│ │Flight Agent│ │General QA     │
     │(tool-call)│ │(tool-call) │ │Agent (no tool)│
     └─────┬─────┘ └─────┬──────┘ └──────────────┘
           │             │
           ▼             ▼
   ┌───────────────┐ ┌───────────────┐
   │ Hotel MCP      │ │ Flight MCP     │   ← separate processes
   │ Server         │ │ Server         │
   │ (list/search/  │ │ (list/search/  │
   │  book hotel)   │ │  book flight)  │
   └───────┬────────┘ └───────┬────────┘
           ▼                  ▼
      Hotel REST API     Flight REST API
```

**Why this shape:** the Hotel and Flight agents never call a REST API
directly — they call MCP tools (`list_hotels`, `search_hotels`, `book_hotel`,
etc). The MCP servers are the *only* code that knows the third-party API
exists. Swapping the hotel provider, or adding a brand-new service (e.g.
weather), means writing a new MCP server and pointing `HOTEL_MCP_URL` /
adding a new URL — no agent code changes.

Each Hotel/Flight agent is a real tool-calling agent: given the conversation,
it decides for itself whether to call `list`, `search`, or `book`, or whether
it needs to ask the user a follow-up question first — it isn't handed
pre-extracted slots by the router. The router's only job is intent
classification (hotel / flight / general_qa).

## Project layout

```
agents/
  entity.py       Shared LangGraph state (GraphState) — single source of truth
                   passed between nodes, including the current "activity"
                   (routing/searching/booking/clarifying/responding).
  graph.py         LangGraph StateGraph wiring: router → {hotel_agent,
                   flight_agent, general_qa_agent}.
  nodes.py         Node functions. Router does intent classification only;
                   hotel_agent_node/flight_agent_node run a real tool-calling
                   loop against MCP tools; general_qa_node is a plain LLM.
  mcp_client.py    The ONLY place agent code knows how to reach the MCP
                   servers (MultiServerMCPClient config).
  llm.py           LLM initialisation (OpenAI, override with your own).
  prompts.py       System prompts for intent classification + each agent.
  observability.py Structured JSON logging of routing decisions + MCP tool
                   calls (thread_id, intent/tool_name, status, duration_ms).
mcp_servers/
  hotel_server.py  Standalone MCP server exposing list_hotels/search_hotels/
                   book_hotel. The only code that calls the hotel REST API.
  flight_server.py Standalone MCP server exposing list_flights/search_flights/
                   book_flight. The only code that calls the flight REST API.
assets/
  bot_avatar.svg   Chatbot avatar icon — must be a real file path, not a
                   data URI (see Design trade-offs below).
main.py            FastAPI backend: /chat (blocking), /chat/stream (SSE
                   streaming with activity + token events), /hotels, /flights.
frontend.py         Gradio chat UI: streams tokens, shows activity cues,
                   result cards, retry/new-conversation controls.
app.py              Not used in the current Render deployment (frontend.py runs directly). Kept from the original Hugging Face Spaces plan in case you deploy there later.
render.yaml         Render Blueprint: deploys backend, both MCP servers, and
                   the frontend as four separate services.
Dockerfile          One shared image for all four services (see Deployment).
docker-compose.yml  Runs all four services together locally via Docker.
.github/workflows/ci.yml  Syntax + import smoke-test on every push/PR.
```

## Local setup

### 1. Clone and install

```bash
git clone <your-repo-url>
cd multi-agent-travel-planner-main
python -m venv env
source env/bin/activate    # Windows: env\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and set at minimum `OPENAI_API_KEY`. The MCP URLs already default
to `http://127.0.0.1:8001/mcp` and `http://127.0.0.1:8002/mcp` for local dev.

### 3. Run all four processes (separate terminals)

```bash
# Terminal 1 — Hotel MCP server
python mcp_servers/hotel_server.py

# Terminal 2 — Flight MCP server
python mcp_servers/flight_server.py

# Terminal 3 — FastAPI backend (agents + graph)
python main.py

# Terminal 4 — Gradio frontend
python frontend.py
```

Open the local Gradio URL printed in Terminal 4.

### 4. Quick smoke test (no frontend needed)

Once the MCP servers and backend are running:

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "show me all hotels"}'
```

Or check MCP tool discovery directly:

```python
import asyncio
from langchain_mcp_adapters.client import MultiServerMCPClient

async def main():
    client = MultiServerMCPClient({
        "hotel": {"url": "http://127.0.0.1:8001/mcp", "transport": "streamable_http"},
        "flight": {"url": "http://127.0.0.1:8002/mcp", "transport": "streamable_http"},
    })
    tools = await client.get_tools()
    for t in tools:
        print(t.name)

asyncio.run(main())
```

You should see: `list_hotels, search_hotels, book_hotel, list_flights,
search_flights, book_flight`.

### 5. Alternative: run everything with Docker Compose

Instead of the four manual terminals above, `docker-compose.yml` runs all
four services together:

```bash
# Make sure your real .env exists first (step 2 above) — the backend
# container reads OPENAI_API_KEY from it via env_file.
docker compose up --build
```

This brings up `hotel-mcp` (:8001), `flight-mcp` (:8002), `backend` (:8000),
and `frontend` (:7860) on one Docker network, using Compose's service-name
DNS (e.g. `http://hotel-mcp:8001/mcp`) for inter-service URLs instead of
`127.0.0.1` — see the `environment:` block per service in
`docker-compose.yml`. All four share one `Dockerfile`; only the `command:`
differs per service. Visit `http://localhost:7860` once it's up.

> **Note:** confirmed working via a real `docker compose up --build -d`
> locally. One practical gotcha worth knowing: running it in the foreground
> (without `-d`) got interrupted partway through in testing, leaving
> containers stuck at "Created" instead of actually starting — `docker
> compose up --build -d` (detached) reliably avoided this. If containers
> ever get stuck in that state, `docker compose down` then retry detached.
> Also make sure Docker Desktop itself is actually running (not just the
> CLI installed) before running any `docker compose` command — Windows in
> particular will throw a `dockerDesktopLinuxEngine` pipe error otherwise.

## MCP Server Setup Guide

Each MCP server is a standalone Python process built with the official MCP
Python SDK's `FastMCP` class, run over the `streamable-http` transport so it's
reachable over a normal URL (rather than stdio, which only works for
same-machine subprocess integration).

**To add a new capability to an existing server:** add a new `@mcp.tool()`
decorated function in `mcp_servers/hotel_server.py` or `flight_server.py` —
nothing elsewhere needs to change; the agent will discover it automatically
next time tools are (re)fetched.

**To add a brand-new service** (e.g. a weather MCP server): create
`mcp_servers/weather_server.py` following the same pattern, deploy it, add its
URL to `agents/mcp_client.py`, and give a new agent node access to
`await get_weather_tools()`. No existing agent/graph code changes.

**Environment variables per MCP server:**
| Variable | Server | Purpose |
|---|---|---|
| `HOTEL_API_BASE` | hotel | Upstream hotel REST API base URL |
| `HOTEL_MCP_HOST` / `PORT` | hotel | Bind address/port |
| `FLIGHT_API_BASE` | flight | Upstream flight REST API base URL |
| `FLIGHT_MCP_HOST` / `PORT` | flight | Bind address/port |

## Deployment

All four components (backend, both MCP servers, and the Gradio frontend)
deploy to **Render** as one Blueprint. HF Spaces was the original plan, but
Hugging Face changed their free-tier policy: new free accounts can no longer
create CPU Basic Gradio Spaces (only ZeroGPU, meant for GPU model inference,
or paid Docker). Since this app is a lightweight CPU-only chat UI calling an
external API, Render is the better fit and keeps all four services on one
platform with one deploy flow.

### All four services → Render

This repo includes `render.yaml`, a Render Blueprint that deploys four
separate services from the same repo:

1. Push this repo to GitHub.
2. In Render, choose **New → Blueprint**, point it at your repo. Render will
   read `render.yaml` and propose all four services.
3. Set the `OPENAI_API_KEY` secret on `tripweaver-backend` when prompted.
4. Deploy. Render assigns public URLs to all four services automatically.
5. **Important:** `render.yaml` hardcodes the expected URLs for the MCP
   servers and backend (e.g. `https://tripweaver-hotel-mcp.onrender.com/mcp`).
   If Render assigns different subdomains, update the relevant env var
   (`HOTEL_MCP_URL` / `FLIGHT_MCP_URL` on the backend, `TRAVEL_PLANNER_API_URL`
   on the frontend) on each affected service to match the real deployed URLs,
   then redeploy.

If you'd rather not use the Blueprint, create the four services manually as
regular Web Services pointing at this repo, using the `startCommand` values
from `render.yaml` for each.

**Free-tier note:** Render's free web services spin down after 15 minutes of
inactivity and take 30–60s to cold-start on the next request. With four
chained free services, a fully-cold first request can feel slow. Ping all
four (a simple `curl` to each) a few minutes before a live demo or viva so
they're warm.

## User Guide

Just type naturally — no special syntax or agent names needed:

- **General questions:** *"What's a good time of year to visit Thailand?"*
- **Browse:** *"Show me all hotels"* / *"Show me all flights"*
- **Search:** *"Find hotels in Colombo from 2026-08-01 to 2026-08-05"*,
  *"Flights from CMB to BKK on 2026-08-10"*
- **Book:** *"Book hotel H123 for John Doe, john@example.com, double room,
  2026-08-01 to 2026-08-05"* — if you leave out required details, the Hotel/
  Flight Agent will ask for exactly what's missing rather than guessing.

While the assistant works you'll see live activity cues (*"Searching…"*,
*"Booking…"*) before the streamed reply appears. If an external service is
temporarily unavailable, you'll get a clear, friendly message instead of an
error page — the rest of the app keeps working.

## Stretch features implemented

Beyond the Core (Required) items above, this project also implements:

- **Memory/context (multi-turn refinement):** the graph is compiled with a
  LangGraph `InMemorySaver` checkpointer (`agents/graph.py`), keyed by a
  `thread_id` the frontend generates once per browser session
  (`frontend.py`) and sends with every request. `GraphState.messages`
  (`agents/entity.py`) uses a custom reducer (`_append_turns`) so each
  request only submits the *new* turn — the checkpointer transparently
  merges it onto everything said before in that thread. This lets a
  traveller say "make it cheaper" or "different dates" without repeating
  earlier details. A "🔄 New conversation" button in the UI starts a fresh
  `thread_id`. Note: `InMemorySaver` resets on process restart — fine for
  this project's scope; swapping in a persistent checkpointer (e.g.
  Postgres) later wouldn't require touching any node code, same decoupling
  principle as the MCP layer.
  - **Bug fix found along the way:** the pre-stretch baseline kept
    conversation history in a single module-level Python list in `main.py`,
    shared by *every* request the process ever handled — there was no
    actual per-user/per-session isolation at all. Moving to per-`thread_id`
    checkpointer state fixes that alongside adding the feature.

- **Observability (structured logging):** `agents/observability.py` emits one
  JSON log line per routing decision and per MCP tool call — `intent`
  chosen and how long classification took, and `tool_name`/`status`
  (`succeeded`/`failed`)/`duration_ms` per tool call, all keyed by
  `thread_id` so a single conversation's behavior can be traced end-to-end
  in the logs. Deliberately excludes message content, tool arguments, and
  tool results — only metadata about what happened, to avoid leaking
  traveller PII (names, emails from booking calls) into logs. The
  `timed_tool_call` context manager always logs on exit, even if the tool
  call raises — so a real failure still produces a trace line instead of
  silently vanishing (mirrors the E3 philosophy: failures are visible, not
  swallowed, in the logs too).

- **Result presentation (cards):** `frontend.py`'s `build_hotel_cards_html`/
  `build_flight_cards_html` render hotel/flight results as styled HTML cards
  inside the chat bubble (name, price, route/city, ID) instead of a plain
  markdown bullet list.
- **Polish — real empty states:** the backend now distinguishes "this turn's
  intent wasn't hotel/flight" (`hotels`/`flights: null`) from "searched and
  found nothing" (`hotels`/`flights: []`) — `main.py`'s `/chat/stream` tracks
  `intent` from the router's own decision and only includes results for the
  agent that actually ran. Genuinely empty results get a real empty-state
  card ("No hotels matched that search…") instead of just vanishing
  silently, which is how the pre-stretch version behaved (`payload.get(...)
  or None` collapsed `[]` and `None` into the same thing).
- **Polish — retry affordance:** a "↻ Retry last message" button resends the
  last user message as a new turn (visible in the chat, not a silent
  replay) using the same `thread_id`, useful right after a tool/service
  failure without retyping.
- **Conversation niceties:** message history persists via the chatbot
  component + backend memory (above); replies are copyable via the
  chatbot's built-in copy button; `gr.Examples` gives one-click starting
  points. Dynamic per-turn contextual quick-replies (e.g. a button that
  reads "Book the first hotel") were considered but intentionally left out —
  implementing them reliably would need either extra client-side JS or a
  more complex Gradio event graph that I couldn't verify end-to-end without
  a live browser session in the time available, and a broken interactive
  element is worse than a static one.

- **CI:** `.github/workflows/ci.yml` runs on every push/PR — compiles every
  `.py` file (catches syntax errors) and import-smoke-tests every real
  entrypoint (`agents.graph`, `main`, `frontend`, both MCP servers) using a
  fake `OPENAI_API_KEY` so it needs no real credentials or network access to
  external services. This is deliberately scoped to catch the *exact* class
  of bug that broke a real Render deploy earlier in this project — a
  dependency imported in code but missing from `requirements.txt`, which
  only ever surfaced as a `ModuleNotFoundError` in Render's deploy logs. I
  verified this by temporarily uninstalling `langchain-mcp-adapters` locally
  and confirming `import main` fails with the identical error CI would
  catch, before reinstalling it.

- **Containerisation:** one shared `Dockerfile` (dependencies installed
  separately from app code for layer-cache efficiency) plus
  `docker-compose.yml` orchestrating all four services on one Docker
  network, using Compose's service-name DNS for inter-service URLs. See
  "Alternative: run everything with Docker Compose" above — including an
  honest note that I could validate the YAML but not actually run the build
  in the environment I was working in, so this needs a real local run
  before you rely on it.

## Design trade-offs 

- **Single-round tool calling per turn:** each Hotel/Flight agent call makes
  at most one round of tool calls before composing its final answer, rather
  than an open-ended ReAct loop. This keeps behaviour predictable and easy to
  reason about for an MVP; a multi-step itinerary (combining hotel + flight
  results) is a natural stretch extension on top of this same structure.
- **Streaming (three LangGraph stream modes combined):** `main.py` calls
  `graph.astream(..., stream_mode=["updates", "messages", "custom"])`.
  `"updates"` reports each node's activity once it finishes (ROUTING,
  RESPONDING, CLARIFYING). `"messages"` surfaces real LLM tokens from
  `llm.astream(...)` inside a node. `"custom"` is what makes SEARCHING and
  BOOKING visible while a tool call is still in flight, not only after the
  whole node returns: `agents/nodes.py` calls LangGraph's
  `get_stream_writer()` immediately before invoking an MCP tool to emit that
  intermediate state. A defensive word-by-word fallback in `main.py` also
  chunks the final text if no native token events are observed for a turn,
  so the UI never regresses to one giant blob.
- **MCP result normalization:** `langchain-mcp-adapters`' `tool.ainvoke()`
  returns MCP's raw content-block list (e.g. `[{"type": "text", "text":
  "<json>"}]`), not the Python dict the MCP server function actually
  returned. `agents/nodes.py`'s `_extract_tool_result()` unwraps this back
  into a plain dict before checking for `error`/`hotels`/`flights` keys —
  otherwise `tool_error` and the structured `hotel_results`/`flight_results`
  would silently never populate, even though the LLM itself would still read
  the tool's JSON text fine and respond sensibly.
- **Two MCP servers, not one:** matches the spec's proposed architecture and
  gives a concrete decoupling story — either service can be redeployed,
  scaled, or replaced independently of the other and of the backend.
- **Vague refinement language needs conversation context, not just any
  context:** early testing showed that after starting a **new** conversation
  (fresh `thread_id`, so correctly no memory of a prior city), asking
  "cheaper ones" made the Hotel Agent call `list_hotels` with no filter and
  pick the cheapest globally — technically "working" (it used a real tool,
  not fabricated data) but not what the user meant. The original prompt's
  rule ("if the user wants to browse everything, call the list tool") was
  too permissive: it let a dangling reference get misread as "browse
  everything." Fixed by adding an explicit rule to both `HOTEL_AGENT_SYSTEM_PROMPT`
  and `FLIGHT_AGENT_SYSTEM_PROMPT`: refinement language only re-searches a
  city/route already established *earlier in this same thread*; if none
  exists, ask instead of silently answering from unrelated results. A good
  illustration that "the tool call succeeded" and "the tool call was the
  right one to make" are different questions — E2's "handle missing inputs
  by asking follow-up questions" applies to *implied* missing inputs
  (a city implied by "cheaper ones" but never actually stated), not just
  literally-absent ones.
- **Chatbot avatar must be a real file, not a data URI:** `gr.Chatbot`'s
  `avatar_images` looks like it should accept any image reference, including
  an inline base64 `data:` URI — it doesn't. Its docs say "a path or URL
  within the working directory," and internally it either fetches a URL or
  reads a local file; a data URI is neither, so it fails silently and shows
  a broken/empty icon with no error. Fixed by writing the icon to a real
  `assets/bot_avatar.svg` file and passing its path instead. Confirmed by
  testing both approaches directly rather than assuming.