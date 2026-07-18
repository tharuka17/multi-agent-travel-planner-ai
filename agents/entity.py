from typing import Annotated, List, Literal, Optional, TypedDict


# Activity states from the spec's Agent Activity & Tool-Call Lifecycle (section 6).
# The graph/agents set this on every state update so the frontend can show what's
# happening ("Searching hotel suggestions…", "Booking hotel…", etc).
ActivityState = Literal["routing", "searching", "booking", "responding", "clarifying"]


def _append_turns(existing: List[str], new: List[str]) -> List[str]:
    """Reducer for `messages`: each graph.ainvoke() call submits only the
    *new* turn(s) for this request (e.g. just the latest user message); this
    appends them onto whatever LangGraph's checkpointer has already persisted
    for this thread_id, instead of overwriting it. This is what makes
    multi-turn memory work — every other GraphState key intentionally has NO
    reducer (default overwrite), since those (hotel_results, activity, etc.)
    should reset fresh each turn, not accumulate.
    """
    return (existing or []) + (new or [])


class GraphState(TypedDict):
    # Full raw conversation so far, alternating user/assistant strings.
    messages: Annotated[List[str], _append_turns]

    # Set by the router node. Drives which agent node the graph dispatches to.
    intent: Literal["hotel", "flight", "general_qa"]

    # Set by whichever node is currently acting. Surfaced to the frontend.
    activity: ActivityState

    # Populated by hotel/flight agents when they successfully retrieve results,
    # so the API layer can also return structured data alongside the text reply.
    hotel_results: List[dict]
    flight_results: List[dict]

    # The final natural-language reply streamed back to the traveller.
    response_text: str

    # True if the last MCP tool call this turn failed — lets the API/frontend
    # distinguish "no results" from "the service was actually unavailable".
    tool_error: bool
