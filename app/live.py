"""Notices that a WhatsApp conversation changed, pushed to open dashboards.

Only a chat id travels through here, never message text. The pane fetches the
conversation itself over the authenticated API, so the dashboard password stays
the only thing deciding who can read what, and nothing anyone wrote is held in
the server's memory on the way past.

In memory, so it covers one process. The deployment runs a single uvicorn
worker; more than one would need a shared bus between them.
"""
import asyncio

# Bounded, so a dashboard on a dead connection cannot grow without limit. On
# overflow the oldest notice goes: a client refetches the whole conversation
# anyway, so a lost notice costs a moment's lag and nothing else.
QUEUE_SIZE = 32

_subscribers: set[asyncio.Queue] = set()


def subscribe() -> asyncio.Queue:
    """One queue per open dashboard. Always paired with unsubscribe()."""
    queue: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_SIZE)
    _subscribers.add(queue)
    return queue


def unsubscribe(queue: asyncio.Queue) -> None:
    _subscribers.discard(queue)


def publish(chat_id: str, kind: str = "activity") -> int:
    """Tell every open dashboard that something happened in this conversation.

    "activity" is a message in or out; "draft" is a reply the assistant wrote
    and held, which the owner may want to act on straight away.
    """
    notice = (kind, chat_id)
    for queue in list(_subscribers):
        if queue.full():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        try:
            queue.put_nowait(notice)
        except asyncio.QueueFull:
            pass
    return len(_subscribers)


def listeners() -> int:
    return len(_subscribers)
