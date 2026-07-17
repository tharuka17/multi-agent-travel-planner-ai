from typing import List, Literal, Optional, TypedDict


# Activity states from the spec's Agent Activity & Tool-Call Lifecycle (section 6).
# The graph/agents set this on every state update so the frontend can show what's
# happening ("Searching hotel suggestions…", "Booking hotel…", etc).
ActivityState = Literal["routing", "searching", "booking", "responding", "clarifying"]


class GraphState(TypedDict):
    # Full raw conversation so far, alternating user/assistant strings.
    # This is the single source of truth passed between nodes (per spec section 7:
    # "all inter-agent communication flows through the shared agent state schema").
    messages: List[str]

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
