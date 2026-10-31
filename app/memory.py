"""Per-contact conversation memory, stored in SQLite so it survives restarts.

Two sources. Everything the agent handles is appended as it happens; and the
first time someone writes, the conversation you have already had with them is
pulled from WhatsApp itself, so the first reply is not written blind. Without
that, a friend of ten years and a stranger look identical to the model.
"""
import os

import httpx

from app import bridge, db
from app.log import anon, log_event


def _turns() -> int:
    """Exchanges of context. Each is a message and a reply, so the model sees
    twice this many. WhatsApp messages are short, so this is cheap; it is an
    env var because the right depth depends on how the owner actually texts."""
    try:
        return max(1, min(int(os.getenv("HISTORY_TURNS", "12")), 50))
    except ValueError:
        return 12


def _keep() -> int:
    return _turns() * 2


def add_user_message(contact_id: str, text: str) -> None:
    db.add_message(contact_id, "user", text, keep=_keep())


def add_assistant_message(contact_id: str, text: str) -> None:
    db.add_message(contact_id, "assistant", text, keep=_keep())


def get_history(contact_id: str) -> list[dict]:
    return db.get_messages(contact_id, _keep())


def clear(contact_id: str) -> None:
    db.clear_messages(contact_id)


def seed_from_whatsapp(contact_id: str) -> int:
    """Fill an empty memory from the real WhatsApp thread. Returns how many
    messages were stored.

    Only ever called when nothing is stored for this contact, so it cannot
    duplicate or overwrite what the agent has already seen. Best effort: a
    bridge that is down or slow means no history, never a failed reply.
    """
    if os.getenv("SEED_HISTORY", "true").strip().lower() != "true":
        return 0
    try:
        response = bridge.post_sync(
            "/thread", {"chat_id": contact_id, "limit": _keep()}, timeout=20)
        if response.status_code != 200:
            log_event("history_seed_skipped", level="warning",
                      chat=anon(contact_id), status=response.status_code)
            return 0
        messages = response.json().get("messages", [])
    except (httpx.HTTPError, ValueError) as err:
        log_event("history_seed_skipped", level="warning",
                  chat=anon(contact_id), error=type(err).__name__)
        return 0

    stored = 0
    for message in messages[-_keep():]:
        # An attachment with no caption still happened, and saying so is better
        # context than a blank turn the model has to guess around.
        text = (message.get("body") or "").strip() or f"[{message.get('kind') or 'Attachment'}]"
        role = "assistant" if message.get("from_me") else "user"
        db.add_message(contact_id, role, text, keep=_keep())
        stored += 1

    log_event("history_seeded", chat=anon(contact_id), messages=stored)  # no text, no number
    return stored
