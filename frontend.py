"""
TripWeaver — Gradio chat frontend.

Talks to the FastAPI backend's /chat/stream SSE endpoint so replies stream in
token-by-token, with visible agent-activity cues (spec section 6: ROUTING /
SEARCHING / BOOKING / CLARIFYING / RESPONDING) and user-friendly error text
instead of raw stack traces.
"""

import json
import os

import gradio as gr
import httpx

API_URL = os.environ.get("TRAVEL_PLANNER_API_URL", "http://127.0.0.1:8000/chat/stream")

ACTIVITY_LABELS = {
    "routing": "🧭 Understanding your request…",
    "searching": "🔎 Searching…",
    "booking": "📝 Booking…",
    "clarifying": "❓ Thinking of a follow-up question…",
    "responding": "✍️ Composing a reply…",
}


def format_hotels(hotels: list[dict]) -> str:
    if not hotels:
        return ""
    lines = ["**Hotels found:**"]
    for hotel in hotels:
        name = hotel.get("name", "Unknown hotel")
        city = hotel.get("city", "")
        if isinstance(city, dict):
            city = city.get("name", "")
        price = hotel.get("price", hotel.get("pricePerNight", "N/A"))
        currency = hotel.get("currency", "USD")
        hotel_id = hotel.get("_id", hotel.get("id", ""))
        lines.append(f"- **{name}** ({hotel_id}) — {city} — {currency} {price}/night")
    return "\n".join(lines)


def format_flights(flights: list[dict]) -> str:
    if not flights:
        return ""
    lines = ["**Flights found:**"]
    for flight in flights:
        airline = flight.get("airline", "Unknown airline")
        number = flight.get("flightNumber", flight.get("flight_number", "N/A"))
        origin = flight.get("origin", {})
        destination = flight.get("destination", {})
        origin_code = origin.get("airport", origin) if isinstance(origin, dict) else origin
        dest_code = destination.get("airport", destination) if isinstance(destination, dict) else destination
        price = flight.get("price", "N/A")
        currency = flight.get("currency", "USD")
        flight_id = flight.get("_id", flight.get("id", ""))
        lines.append(
            f"- **{airline} {number}** ({flight_id}) — {origin_code} → {dest_code} — {currency} {price}"
        )
    return "\n".join(lines)


async def respond(message, history):
    if history is None:
        history = []

    history = history + [{"role": "user", "content": message}, {"role": "assistant", "content": ""}]
    yield history, history

    streamed_text = ""
    activity_label = ""

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            async with client.stream(
                "POST", API_URL, json={"message": message}
            ) as response:
                if response.status_code != 200:
                    history[-1]["content"] = (
                        "⚠️ I couldn't reach the travel planner service right now. "
                        "Please try again shortly."
                    )
                    yield history, history
                    return

                async for line in response.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    payload = json.loads(line[len("data: "):])
                    event_type = payload.get("type")

                    if event_type == "activity":
                        activity_label = ACTIVITY_LABELS.get(payload.get("activity"), "")
                        history[-1]["content"] = f"_{activity_label}_" if not streamed_text else streamed_text
                        yield history, history

                    elif event_type == "token":
                        streamed_text += payload.get("content", "")
                        history[-1]["content"] = streamed_text
                        yield history, history

                    elif event_type == "error":
                        history[-1]["content"] = (
                            f"⚠️ {payload.get('message', 'Something went wrong. Please try again.')}"
                        )
                        yield history, history
                        return

                    elif event_type == "done":
                        final_text = payload.get("response_text") or streamed_text
                        extra = []
                        if payload.get("hotels"):
                            extra.append(format_hotels(payload["hotels"]))
                        if payload.get("flights"):
                            extra.append(format_flights(payload["flights"]))
                        if payload.get("tool_error"):
                            extra.append(
                                "_(Note: one of the travel services was temporarily unavailable — "
                                "some information above may be incomplete.)_"
                            )
                        full_text = "\n\n".join([final_text] + [e for e in extra if e])
                        history[-1]["content"] = full_text
                        yield history, history

    except httpx.RequestError:
        history[-1]["content"] = (
            "⚠️ I couldn't reach the travel planner service right now. Please check your "
            "connection and try again."
        )
        yield history, history


THEME = gr.themes.Soft(
    primary_hue="sky",
    secondary_hue="teal",
    neutral_hue="slate",
)

CUSTOM_CSS = """
#tripweaver-header { text-align: center; margin-bottom: 0.5rem; }
.gradio-container { max-width: 900px !important; margin: auto; }
"""


def main():
    with gr.Blocks(title="TripWeaver") as demo:
        gr.Markdown(
            "# ✈️ TripWeaver\n"
            "### Your AI travel planning assistant — hotels, flights, and travel advice in one chat.",
            elem_id="tripweaver-header",
        )
        chatbot = gr.Chatbot(
            height=520,
            avatar_images=(None, "✈️"),
            buttons=["copy"],
        )
        with gr.Row():
            message = gr.Textbox(
                label="",
                placeholder="e.g. \"Find hotels in Colombo from 2026-08-01 to 2026-08-05\"",
                scale=8,
                container=False,
            )
            submit = gr.Button("Send", scale=1, variant="primary")

        gr.Examples(
            examples=[
                "What are some good destinations for a beach holiday in July?",
                "Show me all hotels",
                "Find flights from CMB to BKK on 2026-08-10",
                "Search hotels in Colombo",
            ],
            inputs=message,
        )

        submit.click(respond, inputs=[message, chatbot], outputs=[chatbot, chatbot]).then(
            lambda: "", None, message
        )
        message.submit(respond, inputs=[message, chatbot], outputs=[chatbot, chatbot]).then(
            lambda: "", None, message
        )

    demo.queue().launch(
        server_name="0.0.0.0",
        server_port=int(os.environ.get("PORT", 7860)),
        theme=THEME,
        css=CUSTOM_CSS,
    )


if __name__ == "__main__":
    main()
