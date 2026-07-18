"""
TripWeaver — Gradio chat frontend.

Talks to the FastAPI backend's /chat/stream SSE endpoint so replies stream in
token-by-token, with visible agent-activity cues (spec section 6: ROUTING /
SEARCHING / BOOKING / CLARIFYING / RESPONDING) and user-friendly error text
instead of raw stack traces.
"""

import json
import os
import pathlib
import uuid

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


def _card(title: str, subtitle: str, meta: str, badge_id: str) -> str:
    return f"""
<div class="tw-card">
  <div class="tw-card-main">
    <div class="tw-card-title">{title}</div>
    <div class="tw-card-subtitle">{subtitle}</div>
  </div>
  <div class="tw-card-meta">{meta}</div>
  <div class="tw-card-id">ID: {badge_id}</div>
</div>
""".strip()


def build_hotel_cards_html(hotels: list[dict]) -> str:
    """Stretch: result presentation — render hotel results as cards instead
    of a plain bullet list. `hotels` is the raw list from the backend; an
    empty (but non-None) list means the Hotel Agent genuinely searched and
    found nothing, which gets its own empty-state card rather than silently
    showing no results section at all."""
    if not hotels:
        return (
            '<div class="tw-empty-state">🏨 No hotels matched that search. '
            "Try a different city or dates.</div>"
        )
    cards = []
    for hotel in hotels:
        name = hotel.get("name", "Unknown hotel")
        city = hotel.get("city", "")
        if isinstance(city, dict):
            city = city.get("name", "")
        price = hotel.get("price", hotel.get("pricePerNight", "N/A"))
        currency = hotel.get("currency", "USD")
        hotel_id = hotel.get("_id", hotel.get("id", ""))
        cards.append(_card(f"🏨 {name}", str(city), f"{currency} {price}/night", str(hotel_id)))
    return '<div class="tw-card-grid">' + "".join(cards) + "</div>"


def build_flight_cards_html(flights: list[dict]) -> str:
    if not flights:
        return (
            '<div class="tw-empty-state">✈️ No flights matched that search. '
            "Try a different route or date.</div>"
        )
    cards = []
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
        cards.append(
            _card(f"✈️ {airline} {number}", f"{origin_code} → {dest_code}", f"{currency} {price}", str(flight_id))
        )
    return '<div class="tw-card-grid">' + "".join(cards) + "</div>"


async def respond(message, history, thread_id):
    if history is None:
        history = []

    history = history + [{"role": "user", "content": message}, {"role": "assistant", "content": ""}]
    # Stretch: polish — last_message powers the Retry button below, so a
    # failed turn can be resent without retyping it.
    yield history, history, message

    streamed_text = ""
    activity_label = ""

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            async with client.stream(
                "POST", API_URL, json={"message": message, "thread_id": thread_id}
            ) as response:
                if response.status_code != 200:
                    history[-1]["content"] = (
                        "⚠️ I couldn't reach the travel planner service right now. "
                        "Please try again shortly."
                    )
                    yield history, history, message
                    return

                async for line in response.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    payload = json.loads(line[len("data: "):])
                    event_type = payload.get("type")

                    if event_type == "activity":
                        activity_label = ACTIVITY_LABELS.get(payload.get("activity"), "")
                        history[-1]["content"] = f"_{activity_label}_" if not streamed_text else streamed_text
                        yield history, history, message

                    elif event_type == "token":
                        streamed_text += payload.get("content", "")
                        history[-1]["content"] = streamed_text
                        yield history, history, message

                    elif event_type == "error":
                        history[-1]["content"] = (
                            f"⚠️ {payload.get('message', 'Something went wrong. Please try again.')}"
                        )
                        yield history, history, message
                        return

                    elif event_type == "done":
                        final_text = payload.get("response_text") or streamed_text
                        extra = []
                        # None = not applicable this turn (e.g. a general_qa
                        # reply); [] = genuinely searched and found nothing,
                        # which gets a real empty-state card, not silence.
                        if payload.get("hotels") is not None:
                            extra.append(build_hotel_cards_html(payload["hotels"]))
                        if payload.get("flights") is not None:
                            extra.append(build_flight_cards_html(payload["flights"]))
                        if payload.get("tool_error"):
                            extra.append(
                                '<div class="tw-error-note">⚠️ One of the travel services was '
                                "temporarily unavailable — try again in a moment, or use the "
                                "Retry button below to resend this message.</div>"
                            )
                        full_text = "\n\n".join([final_text] + [e for e in extra if e])
                        history[-1]["content"] = full_text
                        yield history, history, message

    except httpx.RequestError:
        history[-1]["content"] = (
            "⚠️ I couldn't reach the travel planner service right now. Please check your "
            "connection and try again."
        )
        yield history, history, message


THEME = gr.themes.Soft(
    primary_hue="sky",
    secondary_hue="teal",
    neutral_hue="slate",
)

CUSTOM_CSS = """
#tripweaver-header { text-align: center; margin-bottom: 0.5rem; }
.gradio-container { max-width: 900px !important; margin: auto; }

.tw-card-grid {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  margin-top: 0.5rem;
}
.tw-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  border: 1px solid var(--border-color-primary, #d9dce3);
  border-radius: 10px;
  padding: 0.6rem 0.9rem;
  background: var(--background-fill-secondary, #f7f9fc);
}
.tw-card-title { font-weight: 600; font-size: 0.95rem; }
.tw-card-subtitle { font-size: 0.85rem; opacity: 0.75; }
.tw-card-meta { font-weight: 600; white-space: nowrap; font-size: 0.9rem; }
.tw-card-id { font-size: 0.7rem; opacity: 0.5; white-space: nowrap; }
.tw-empty-state {
  margin-top: 0.5rem;
  padding: 0.6rem 0.9rem;
  border: 1px dashed var(--border-color-primary, #d9dce3);
  border-radius: 10px;
  font-size: 0.9rem;
  opacity: 0.8;
}
.tw-error-note {
  margin-top: 0.5rem;
  padding: 0.5rem 0.75rem;
  border-radius: 8px;
  background: #fff4e5;
  color: #8a5300;
  font-size: 0.85rem;
}
"""


def main():
    with gr.Blocks(title="TripWeaver") as demo:
        gr.Markdown(
            "# ✈️ TripWeaver\n"
            "### Your AI travel planning assistant — hotels, flights, and travel advice in one chat.",
            elem_id="tripweaver-header",
        )
        # Stretch: Memory/context. One thread_id per browser session (regenerated
        # only if the user explicitly resets), sent with every request so the
        # backend's checkpointer (agents/graph.py) knows which conversation's
        # history to load/persist — lets the traveller say "make it cheaper" or
        # "different dates" without repeating earlier details.
        thread_id = gr.State(lambda: str(uuid.uuid4()))
        # Stretch: polish — remembers the last sent message so the Retry
        # button can resend it without the user retyping anything.
        last_message = gr.State("")

        BOT_AVATAR = str(pathlib.Path(__file__).parent / "assets" / "bot_avatar.svg")
        chatbot = gr.Chatbot(
            height=520,
            avatar_images=(None, BOT_AVATAR),
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

        with gr.Row():
            new_chat = gr.Button("🔄 New conversation", size="sm")
            retry = gr.Button("↻ Retry last message", size="sm")

        gr.Examples(
            examples=[
                "What are some good destinations for a beach holiday in July?",
                "Show me all hotels",
                "Find flights from CMB to BKK on 2026-08-10",
                "Search hotels in Colombo",
            ],
            inputs=message,
        )

        submit.click(
            respond, inputs=[message, chatbot, thread_id], outputs=[chatbot, chatbot, last_message]
        ).then(lambda: "", None, message)
        message.submit(
            respond, inputs=[message, chatbot, thread_id], outputs=[chatbot, chatbot, last_message]
        ).then(lambda: "", None, message)
        # Retry resends whatever `last_message` holds, as a new turn (not a
        # silent replay) — visible in the chat like any other message, using
        # the same thread_id so it's still part of the same conversation.
        retry.click(
            respond, inputs=[last_message, chatbot, thread_id], outputs=[chatbot, chatbot, last_message]
        )
        # New conversation = fresh thread_id (so the backend starts a clean
        # checkpointer thread) + clear the visible chat history.
        new_chat.click(
            lambda: (str(uuid.uuid4()), [], [], ""),
            outputs=[thread_id, chatbot, chatbot, last_message],
        )

    demo.queue().launch(
        server_name="0.0.0.0",
        server_port=int(os.environ.get("PORT", 7860)),
        theme=THEME,
        css=CUSTOM_CSS,
    )


if __name__ == "__main__":
    main()