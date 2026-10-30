"""Dashboard assistant: chats with the owner and acts through a few tools.

Security model: incoming chats are never put in this context, so a contact's
message can't instruct it (prompt injection). show_messages is answered by a
plain database query and the page renders the rows itself, so the model never
reads message text and listing messages costs almost no tokens.

Sending: send_message goes out immediately when "direct send" is on (the page
performs it through the normal, validated /api/send-text route); draft_message
always shows a card to review first.
"""
import os
import re
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app import db
from app.controls import LOCAL_TZ, RANGE_LABELS, find_messages
from app.dashboard import _contact_names, require_auth
from app.lang import looks_swahili
from app.llm import EFFORT, MODEL, _STYLE_EXAMPLES, _get_client, _normalize_history

router = APIRouter()
AUTH = [Depends(require_auth)]
ASSISTANT_NAME = os.getenv("ASSISTANT_NAME", "Arianna")
# Short forms she is also called, comma-separated. The wake word in
# dashboard.html has its own list of spellings the recognizer may produce.
ASSISTANT_NICKNAMES = os.getenv("ASSISTANT_NICKNAMES", "Arie")

# Room for the thinking tokens that share this budget; a tool call or a chat
# reply is a few dozen tokens of it.
MAX_TOKENS = 4096


def _tool(name: str, description: str, properties: dict, required: list[str]) -> dict:
    # strict only where every parameter is required: it guarantees the arguments
    # validate against the schema. show_messages has optional filters instead,
    # and handle_call checks each of them against its allowed values anyway.
    tool = {"name": name, "description": description,
            "input_schema": {"type": "object", "properties": properties,
                             "required": required, "additionalProperties": False}}
    if set(required) == set(properties):
        tool["strict"] = True
    return tool


TOOLS = [
    _tool("send_message", "Send a WhatsApp text to one contact right now, in the owner's voice. Use when she tells you to send, tell or message someone.",
          {"contact": {"type": "string"}, "text": {"type": "string"}}, ["contact", "text"]),
    _tool("draft_message", "Write a message for the owner to review before it is sent. Use only when she asks you to write, draft or word something, or says to check with her first.",
          {"contact": {"type": "string"}, "text": {"type": "string"}}, ["contact", "text"]),
    _tool("send_location", "Send the owner's current location pin to one contact.",
          {"contact": {"type": "string"}}, ["contact"]),
    _tool("show_messages", "Show the owner the messages people sent her and the replies sent as her. Use when she asks who messaged her, what someone sent, or to list messages. The app displays them; you never see their content.",
          {"contact": {"type": "string", "description": "Omit to include everyone."},
           "range": {"type": "string", "enum": list(RANGE_LABELS)},
           "direction": {"type": "string", "enum": ["received", "sent", "both"]}}, []),
]


def _system_prompt(names: list[str], now: datetime) -> str:
    also = f" She also calls you {ASSISTANT_NICKNAMES}, so answer to that too." if ASSISTANT_NICKNAMES.strip() else ""
    return f"""Your name is {ASSISTANT_NAME}.{also} You are the owner's private assistant inside their WhatsApp dashboard. Talk with them naturally and helpfully in whatever language they write in: answer questions, help them think, help them word things. You can also act through tools.
It is {now.strftime('%A %d %B %Y, %I:%M %p')} (Nairobi time).
Known contacts (the only valid recipients and message filters): {", ".join(names) or "none"}.
Match their wording to a listed name, written exactly as listed (for example "mum", "mathe" or "mom" means the listed name for their mother). If you can't tell who they mean, ask. Never invent contacts, numbers or locations.
Tools:
- send_message: when they tell you to send, tell or message someone. It goes out immediately, so write the text the way they text: first person, short and casual, no punctuation except a final "?" for questions. Match the register they used — Kenyan English, Sheng or Kiswahili — and mirror a code-switched mix rather than tidying it into one language. If they dictate the words, keep them.
- draft_message: only when they ask you to write, draft or word something for them to review, or say to check with them first.
- send_location: to send their current location pin.
- show_messages: when they ask who messaged them, what someone sent, or to list messages. The app shows them itself. You can't read their content, so never describe, summarise or guess what any message says.
For anything else, just answer in text. Don't call a tool for normal conversation. Reply in the language they write in.
Voice examples for drafting:
{_STYLE_EXAMPLES}"""


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    history: list[dict] = Field(default_factory=list, max_length=10)


_SW_WHEN = {"today": "leo", "yesterday": "jana", "last_7_days": "siku saba zilizopita", "all": "kwa rekodi yote"}


def _sw_count(n: int) -> str:
    return "ujumbe mmoja" if n == 1 else "jumbe mbili" if n == 2 else f"jumbe {n}"


def _messages_reply(contact: str | None, period: str, direction: str, count: int, swahili: bool) -> str:
    if swahili:
        when = _SW_WHEN[period]
        if not count:
            return f"hakuna jumbe{' na ' + contact if contact else ''} {when}"
        n = _sw_count(count)
        if direction == "received":
            return f"umepokea {n}{' kutoka ' + contact if contact else ''} {when}:"
        if direction == "sent":
            return f"ulituma {n}{' kwa ' + contact if contact else ''} {when}:"
        return f"kuna {n}{' na ' + contact if contact else ''} {when}:"
    kind = {"received": "received ", "sent": "sent ", "both": ""}[direction]
    who = f" with {contact}" if contact else ""
    if not count:
        return f"No {kind}messages{who} {RANGE_LABELS[period]}."
    return f"{count} {kind}{'message' if count == 1 else 'messages'}{who} {RANGE_LABELS[period]}:"


def handle_call(fn: str, args: dict, names: list[str], direct: bool, swahili: bool = False) -> dict:
    """Turn one tool call into a response for the page. Pure logic, no model involved."""
    known = {n.strip().lower(): n for n in names}
    raw_contact = str(args.get("contact") or "").strip()
    contact = known.get(raw_contact.lower())
    unknown = "sijapata hiyo jina kwa contacts.json." if swahili else "I couldn't find that name in contacts.json."

    if fn == "show_messages":
        if raw_contact and not contact:
            return {"reply": unknown, "action": None}
        period = args.get("range") if args.get("range") in RANGE_LABELS else "today"
        direction = args.get("direction") if args.get("direction") in ("received", "sent", "both") else "both"
        items = find_messages(contact, period, direction, 50)
        reply = _messages_reply(contact, period, direction, len(items), swahili)
        return {"reply": reply, "action": {"type": "messages", "items": items} if items else None}

    if not contact:
        return {"reply": unknown, "action": None}

    if fn in ("send_message", "draft_message"):
        text = str(args.get("text", "")).strip()
        if not text:
            return {"reply": "ujumbe useme nini?" if swahili else "What should the message say?", "action": None}
        auto = direct and fn == "send_message"
        if swahili:
            reply = f"natuma kwa {contact}…" if auto else f"draft ya {contact}:"
        else:
            reply = f"Sending to {contact}…" if auto else f"Draft for {contact}:"
        return {"reply": reply, "action": {"type": "text", "contact": contact, "text": text, "auto": auto}}

    if fn == "send_location":
        if swahili:
            reply = f"natuma location yako kwa {contact}…" if direct else f"niko tayari kutuma location yako kwa {contact}."
        else:
            reply = f"Sending your location to {contact}…" if direct else f"Ready to send your current location to {contact}."
        return {"reply": reply, "action": {"type": "location", "contact": contact, "auto": direct}}

    return {"reply": "I can't do that one.", "action": None}


@router.post("/api/assistant", dependencies=AUTH)
def assistant(body: ChatRequest):  # plain def: runs in a thread pool
    names = _contact_names()
    history = _normalize_history(
        [{"role": m.get("role"), "content": str(m.get("content", ""))[:1500]} for m in body.history]
    )
    resp = _get_client().messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=_system_prompt(names, datetime.now(LOCAL_TZ)),
        tools=TOOLS,
        output_config={"effort": EFFORT},
        messages=[*history, {"role": "user", "content": body.message}],
    )

    swahili = looks_swahili(body.message)
    unclear = "sijaelewa, sema tena kwa njia ingine." if swahili else "I didn't catch that — try saying it another way."

    call = next((b for b in resp.content if b.type == "tool_use"), None)
    if call is None:
        # Plain conversation: the visible answer is the text blocks. Thinking
        # blocks are in content too, and are not part of the reply.
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        return {"reply": text or unclear, "action": None}

    if not isinstance(call.input, dict):
        return {"reply": unclear, "action": None}
    return handle_call(call.name, call.input, names, db.direct_send_enabled(), swahili)
