from langgraph.graph import END, START, StateGraph

from .entity import GraphState
from .nodes import flight_agent_node, general_qa_node, hotel_agent_node, route_after_intent, router


def build_graph() -> StateGraph:
    builder = StateGraph(GraphState)

    builder.add_node("router", router)
    builder.add_node("hotel_agent", hotel_agent_node)
    builder.add_node("flight_agent", flight_agent_node)
    builder.add_node("general_qa_agent", general_qa_node)

    builder.add_edge(START, "router")

    # E2: the graph decides where to go based on classified intent, not a fixed path.
    builder.add_conditional_edges(
        "router",
        route_after_intent,
        {
            "hotel": "hotel_agent",
            "flight": "flight_agent",
            "general_qa": "general_qa_agent",
        },
    )

    builder.add_edge("hotel_agent", END)
    builder.add_edge("flight_agent", END)
    builder.add_edge("general_qa_agent", END)

    return builder


graph = build_graph().compile()
