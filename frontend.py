import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import gradio as gr

API_URL = os.environ.get("TRAVEL_PLANNER_API_URL", "http://127.0.0.1:8000/chat")


def format_flights(flights):
    lines = ["Flights:"]
    for flight in flights:
        lines.append(
            f"{flight.get('airline')} {flight.get('flightNumber')} from {flight['origin']['airport']} to {flight['destination']['airport']} "
            f"on {flight.get('flightDate')} {flight.get('departureTime')} - {flight.get('arrivalTime')} "
            f"- {flight.get('currency')} {flight.get('price')} - {flight.get('availableSeats')} seats"
        )
    return "\n".join(lines)


def format_hotels(hotels):
    lines = ["Hotels:"]
    for hotel in hotels:
        name = hotel.get("name") or "Unknown Hotel"
        city = hotel.get("city") or hotel.get("location", {}).get("city", "")
        price = hotel.get("price") or hotel.get("currency", "")
        lines.append(f"{name} in {city} - {price}")
    return "\n".join(lines)


def call_chat_api(message):
    payload = json.dumps({"message": message}).encode("utf-8")
    request = Request(API_URL, data=payload, headers={"Content-Type": "application/json"})

    try:
        response = urlopen(request, timeout=15)
        data = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        return f"Backend error {exc.code}: {exc.reason}"
    except URLError as exc:
        return f"Unable to reach backend at {API_URL}: {exc.reason}"
    except Exception as exc:
        return f"Unexpected error: {exc}"

    chat_text = data.get("response", "No response returned.")
    parts = [chat_text]

    if data.get("flights"):
        parts.append(format_flights(data["flights"]))
    if data.get("hotels"):
        parts.append(format_hotels(data["hotels"]))

    return "\n\n".join(parts)


def respond(message, history):
    if history is None:
        history = []

    answer = call_chat_api(message)
    history = history + [
        {"role": "user", "content": message},
        {"role": "assistant", "content": answer},
    ]
    return history, history


def main():
    with gr.Blocks() as demo:
        gr.Markdown(
            "# Travel Planner Chat\nAsk the backend for flights, hotels, or travel plans. ``TRAVEL_PLANNER_API_URL`` can be set to point to your FastAPI server."
        )
        chatbot = gr.Chatbot()
        message = gr.Textbox(label="Your message", placeholder="Find me flights from CAN to HAN on 2025-11-15")
        submit = gr.Button("Send")

        submit.click(respond, inputs=[message, chatbot], outputs=[chatbot, chatbot])
        message.submit(respond, inputs=[message, chatbot], outputs=[chatbot, chatbot])

    demo.launch()


if __name__ == "__main__":
    main()
