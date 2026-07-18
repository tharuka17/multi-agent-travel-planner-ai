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
mcp_servers/
  hotel_server.py  Standalone MCP server exposing list_hotels/search_hotels/
                   book_hotel. The only code that calls the hotel REST API.
  flight_server.py Standalone MCP server exposing list_flights/search_flights/
                   book_flight. The only code that calls the flight REST API.
main.py            FastAPI backend: /chat (blocking), /chat/stream (SSE
                   streaming with activity + token events), /hotels, /flights.
frontend.py         Gradio chat UI: streams tokens, shows activity cues,
                   travel-themed responsive layout.
app.py              Not used in the current Render deployment (frontend.py runs directly). Kept from the original Hugging Face Spaces plan in case you deploy there later.
render.yaml         Render Blueprint: deploys backend + both MCP servers as
                   three separate services.
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

## Design trade-offs (for viva discussion)

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