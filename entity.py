from pydantic import BaseModel
from typing import List, Optional

class ChatRequest(BaseModel):
    message: str
    # Identifies which conversation this belongs to, so the graph's
    # checkpointer (agents/graph.py) can load/persist the right history.
    # Optional so curl/testing without a frontend still works — everything
    # sharing the default thread_id shares one conversation, same as before
    # memory/context existed, so this is backward compatible.
    thread_id: Optional[str] = "default"


class ChatResponse(BaseModel):
    response: str
    hotels: Optional[List[dict]] = None
    flights: Optional[List[dict]] = None