import json

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from entity import ChatRequest, ChatResponse
from agents.graph import graph
from agents.mcp_client import get_flight_tools, get_hotel_tools
from agents.nodes import _extract_tool_result

app = FastAPI(title="TripWeaver API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def hello():
    return {"message": "TripWeaver API is running."}


@app.get("/hotels")
async def list_hotels():
    """Convenience REST endpoint — internally goes through the same MCP tool
    the Hotel Agent uses, so there's still only one path to the outside world."""
    tools = await get_hotel_tools()
    list_tool = next(t for t in tools if t.name == "list_hotels")
    raw_result = await list_tool.ainvoke({})
    return _extract_tool_result(raw_result)


@app.get("/flights")
async def list_flights():
    tools = await get_flight_tools()
    list_tool = next(t for t in tools if t.name == "list_flights")
    raw_result = await list_tool.ainvoke({})
    return _extract_tool_result(raw_result)


def _build_initial_state(message: str) -> dict:
    # Only the *new* turn is submitted here — the graph's checkpointer
    # (agents/graph.py) already holds everything before it for this
    # thread_id, and entity.py's `messages` reducer appends this onto that
    # persisted history rather than replacing it. This is also what fixes a
    # real bug from before memory/context existed: the old approach kept a
    # single module-level `conversation_history_messages` list shared by
    # every request the process ever handled, across all users/sessions —
    # there was no actual per-conversation isolation. Per-thread_id state
    # here fixes that alongside adding the stretch feature.
    return {
        "messages": [message],
        "intent": "general_qa",
        "activity": "routing",
        "hotel_results": [],
        "flight_results": [],
        "response_text": "",
        "tool_error": False,
    }


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Non-streaming chat endpoint. Simple request/response — useful for
    curl/testing and for any client that doesn't need live token streaming."""
    initial_state = _build_initial_state(request.message)
    config = {"configurable": {"thread_id": request.thread_id}}
    result = await graph.ainvoke(initial_state, config=config)

    response_text = result.get("response_text") or "Something went wrong. Please try again."

    return ChatResponse(
        response=response_text,
        hotels=result.get("hotel_results") or None,
        flights=result.get("flight_results") or None,
    )


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, default=str)}\n\n"


@app.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    """Streaming chat endpoint (SSE).

    Emits two kinds of events as the graph runs:
      - {"type": "activity", "activity": "...", "node": "..."} whenever a node
        finishes and updates its activity state (ROUTING/SEARCHING/BOOKING/
        CLARIFYING/RESPONDING from spec section 6).
      - {"type": "token", "content": "..."} for each token as the agent's
        final reply is generated.
    And finally one {"type": "done", ...} event with the full structured
    result (final text + any hotel/flight results + whether a tool errored).
    """
    initial_state = _build_initial_state(request.message)
    config = {"configurable": {"thread_id": request.thread_id}}

    async def event_generator():
        final_payload: dict = {}
        final_intent = None
        streamed_any_token = False
        try:
            async for mode, chunk in graph.astream(
                initial_state, config=config, stream_mode=["updates", "messages", "custom"]
            ):
                if mode == "updates":
                    for node_name, node_output in chunk.items():
                        if not isinstance(node_output, dict):
                            continue
                        activity = node_output.get("activity")
                        if activity:
                            yield _sse({"type": "activity", "node": node_name, "activity": activity})
                        if node_name == "router":
                            final_intent = node_output.get("intent")
                        if node_name in ("hotel_agent", "flight_agent", "general_qa_agent"):
                            final_payload = node_output

                elif mode == "custom":
                    # Mid-node activity events (e.g. SEARCHING/BOOKING) emitted by
                    # agents/nodes.py via get_stream_writer() *before* a tool call
                    # actually runs. This is what makes those states visible while
                    # the MCP call is in flight, not just after the node finishes.
                    if isinstance(chunk, dict) and chunk.get("type") == "activity":
                        yield _sse(chunk)

                elif mode == "messages":
                    message_chunk, _metadata = chunk
                    if getattr(message_chunk, "content", None):
                        streamed_any_token = True
                        yield _sse({"type": "token", "content": message_chunk.content})

            # Defensive fallback: if the LLM/langgraph version in use doesn't
            # surface native token-stream events for any reason, we still give
            # the frontend a token-like stream instead of one giant blob.
            if not streamed_any_token and final_payload.get("response_text"):
                for word in final_payload["response_text"].split(" "):
                    yield _sse({"type": "token", "content": word + " "})

        except Exception as e:
            # E3: streaming itself must degrade gracefully, never hang or crash the client.
            yield _sse(
                {
                    "type": "error",
                    "message": "Something went wrong while processing your request. Please try again.",
                }
            )
            yield _sse({"type": "done", "response_text": "", "hotels": None, "flights": None, "tool_error": True})
            return

        response_text = final_payload.get("response_text") or "Something went wrong. Please try again."

        # hotels/flights: pass the real list through as-is (even if empty) when
        # this turn's intent was hotel/flight — an empty list means "searched,
        # found nothing" which the frontend renders as a real empty state,
        # distinct from `null` meaning "not applicable this turn" (e.g. a
        # general_qa turn). Collapsing [] to null here would make those two
        # cases indistinguishable to the frontend.
        hotels = final_payload.get("hotel_results", []) if final_intent == "hotel" else None
        flights = final_payload.get("flight_results", []) if final_intent == "flight" else None

        yield _sse(
            {
                "type": "done",
                "response_text": response_text,
                "intent": final_intent,
                "hotels": hotels,
                "flights": flights,
                "tool_error": final_payload.get("tool_error", False),
            }
        )

    return StreamingResponse(event_generator(), media_type="text/event-stream")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
