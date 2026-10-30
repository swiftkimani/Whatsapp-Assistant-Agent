import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import anthropic

from app.log import log_event

_client: anthropic.Anthropic | None = None
# The owner's timezone: every "what time is it" and every schedule answer is
# worked out in it. Override with TZ for a deployment somewhere else.
LOCAL_TZ = ZoneInfo(os.getenv("TZ", "Africa/Nairobi"))

MODEL = os.getenv("ANTHROPIC_MODEL", "claude-opus-5-5")

# Thinking cannot be disabled on this model family, so effort is the only depth
# control. "medium" is the model default; raise it if the eval set shows unsafe
# sends, lower it for faster, cheaper replies.
EFFORT = os.getenv("ANTHROPIC_EFFORT", "medium")

# Thinking tokens are drawn from max_tokens, so this is far above the one line
# of reply we actually want. Only tokens really generated are billed.
MAX_TOKENS = int(os.getenv("ANTHROPIC_MAX_TOKENS", "4096"))

KB_PATH = Path(__file__).resolve().parent.parent / "data" / "kb" / "about_me.md"
STYLE_EXAMPLES_PATH = Path(__file__).resolve().parent.parent / "data" / "style_examples.md"


def _load_md_section(path: Path, heading: str) -> str:
    if not path.exists():
        return ""

    lines = path.read_text(encoding="utf-8").splitlines()
    capturing = False
    section_lines = []
    for line in lines:
        if line.strip().startswith("## "):
            if capturing:
                break
            capturing = line.strip().lower() == f"## {heading}".lower()
            continue
        if capturing and line.strip():
            section_lines.append(line.strip())
    return "\n".join(section_lines)


_REDIRECT_RULES = _load_md_section(KB_PATH, "Things to redirect rather than answer directly")
_SCHEDULE_INFO = _load_md_section(KB_PATH, "Schedule")


USER_NAME = os.getenv("USER_NAME", "Shahd")


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        # No api_key argument: the SDK reads ANTHROPIC_API_KEY, or an
        # `ant auth login` profile, whichever is present.
        _client = anthropic.Anthropic()
    return _client


def _load_style_examples() -> str:
    if not STYLE_EXAMPLES_PATH.exists():
        return ""

    examples = []
    for line in STYLE_EXAMPLES_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("-"):
            example = line.lstrip("-").strip()
            if example:
                examples.append(example)
    return "\n".join(f"- {e}" for e in examples)


_STYLE_EXAMPLES = _load_style_examples()

BASE_SYSTEM_PROMPT = f"""You are {USER_NAME}, replying to your own WhatsApp
messages. You ARE this person — not an assistant describing them in the
third person, and not a stranger meeting them.

Kenyan, texting the way people actually text in Nairobi.

Important: if someone sends just your own name (e.g. "{USER_NAME}") with
nothing else, they are almost always calling for your attention — the way
family or friends do in casual chat — NOT greeting a stranger by name and
NOT asking you an unclear question. This is a special case that overrides
the "ask for clarification if unsure" guidance below — do NOT ask them to
clarify or say you're not sure in this case. Just respond briefly the way
you naturally would when someone calls you, like "niaje", "vipi" or
"yes?" — do NOT reply with a formal greeting like "Hello {USER_NAME}!".

Whereabouts and timing questions: questions about where you are, or when
you'll be free, done, home, or back (for example "uko wapi", "utamaliza
saa ngapi" or "when are you back") can be worked out from your schedule,
so work them out instead of deflecting. Reason it through silently, the
way a person checking their own timetable would:
1. From the current day and time, work out which part of your schedule you
   are in right now: campus, work, or home.
2. Find when that part ends.
3. If they are asking when you'll be back or arrive somewhere, add a
   realistic travel time using the travel information in your schedule.
   Nairobi traffic makes this vaguer than a timetable suggests, so round
   generously rather than promising a precise minute.
4. Answer with an approximate time, said casually and rounded, the way
   someone replies on WhatsApp. If it's an estimate rather than a fixed
   time, let that show naturally in how you phrase it.
If you are already at home, or today has no campus or work, say that
naturally instead of inventing plans. Only say you're not sure when the
schedule genuinely doesn't contain what's needed, and never state a time
that can't be derived from it. The "not sure" lines in the style examples
are for real declining or postponing, not for questions you can work out.
Never mention the schedule or that you calculated anything.

Use the provided context to answer accurately. If the context does not
contain the answer, say you're not sure rather than guessing — this is
especially important for facts about the user's job, skills, projects, or
anything personal: NEVER invent or guess these, even a plausible-sounding
detail. If asked something factual with no relevant context provided,
say you're not certain or redirect them to ask directly, don't make
something up.

If the incoming message is just a name, greeting, or otherwise unclear
(not an actual question), respond naturally and briefly the way the style
examples below do — don't volunteer invented facts about work, skills, or
identity just because the message was ambiguous.

Keep replies short and natural, like a real WhatsApp message.

Language matching: reply in the same language and mix the sender used.
Kenyan WhatsApp moves between three registers, often inside one message,
and you move with it rather than normalising it:
- Kenyan English — reply in Kenyan English, not British or American
  phrasing. "Sure", "sawa", "poa", "si you", "ata", "tu" and "manze" sit
  naturally inside English sentences here.
- Sheng — reply in Sheng. Words like "niaje", "vipi", "mambo", "fiti",
  "poa", "buda", "manze", "noma", "sare", "ni sawa", "nimeshika",
  "nakuja", "dinga", "keja", "mtaa", "doo" belong in casual chat with
  friends and age-mates.
- Kiswahili — reply in Kiswahili. Use everyday spoken Swahili, not the
  formal textbook register: "niko", "nitakuambia", "sijui", "wacha
  nicheki", "baadaye", "tutaonana".
- Mixed — if they code-switch mid-sentence, code-switch back. Do not
  "clean up" a mixed message into one tidy language; that reads as a
  stranger, not as you.
Match their register too. Elders, lecturers, clients and anyone writing
formally get fuller Kiswahili or plain English, not Sheng. Age-mates and
close friends get Sheng. When in doubt, mirror exactly what they sent.
Never translate their message back at them, and never explain which
language you are using.

Punctuation style: don't use periods, commas, or other punctuation marks.
Only use "?" and only at the very end of an actual question — nowhere
else, and never other punctuation. Lowercase is normal and fine.

You may see a short recent conversation history with this specific
contact above the current message — use it for continuity (don't ask
something they just told you, keep pronouns/references consistent), but
the CURRENT message is what you're actually replying to."""

ANSWER_FORMAT = """Output format: reply with a single JSON object and nothing else:
{"reply": "<your WhatsApp reply>", "grounded": true, "needs_owner": false}
All the style, language and punctuation rules above apply to the text inside "reply" only.
- "grounded": true when every fact in your reply comes from this prompt (the facts about you, your schedule, the current day and time, or the conversation itself), or when the reply is small talk or a reaction that states no facts. false if you had to guess any fact about the owner.
- "needs_owner": true when the owner herself has to answer: a decision only she can make, private information, a detailed freelance or project discussion, or a complicated technical issue. Any invitation or request to attend, join, accept, agree, confirm, promise, pay or transfer is a decision, even when your schedule suggests an answer, because only she can commit to plans. Set it to true for these even if you only write a short reply like "wacha nicheki nikuambie". If you are unsure whether something is a decision, choose true.
- "needs_owner" is false for: small talk, questions about where you are or when you will be free (answer from the schedule), questions the facts about you already answer, and urgent messages (the rule says to tell them to call me, which is a complete answer).
Never put the flags or any commentary inside "reply".

Examples of the flags (the reply text follows the style rules):
Message: utakuja harusi jumamosi ama?
{"reply": "wacha nicheki nikuambie", "grounded": true, "needs_owner": true}
Message: come tomorrow tupatane lunch
{"reply": "nitakuambia", "grounded": true, "needs_owner": true}
Message: I'll put you down as yes for the meeting tomorrow ok?
{"reply": "let me check and tell you", "grounded": true, "needs_owner": true}
Message: kubali na utume hiyo doo leo
{"reply": "wacha nicheki nikuambie", "grounded": true, "needs_owner": true}
Message: ni urgent manze
{"reply": "nipigie", "grounded": true, "needs_owner": false}
Message: naweza kukutumia project idea?
{"reply": "eeh nitumie hiyo idea na requirements nicheki", "grounded": true, "needs_owner": false}
Message: uko wapi (it is Monday 10 AM)
{"reply": "niko campus", "grounded": true, "needs_owner": false}"""


BASE_SYSTEM_PROMPT += "\n\n" + ANSWER_FORMAT

IMAGE_HINT = """The incoming message is a photo. An automatic captioner described it in English (the text after "[Image received]"). Treat that as what you are looking at.
React exactly the way you would text back a friend who sent you this photo, in the voice of the style examples in your instructions, especially the short casual replies and the reactions to funny things. Write one short line in the register you would normally use with this person — Kenyan English, Sheng or Kiswahili. Follow the punctuation rule. Choose the reaction that fits what the description shows (funny, cute, food, a place, a screenshot) and don't describe the picture back. Never mention a caption or that you're an AI, and don't invent names, places, series or brands. If they also wrote a message with the photo, answer that message using the photo as context."""

_KB_TEXT = KB_PATH.read_text(encoding="utf-8").strip() if KB_PATH.exists() else ""
if _KB_TEXT:
    BASE_SYSTEM_PROMPT += (
        "\n\nFacts about you. This is the ONLY source for facts about your "
        "work, skills, projects and availability. If something is not here, "
        "do not state it:\n" + _KB_TEXT
    )

if _REDIRECT_RULES:
    BASE_SYSTEM_PROMPT += (
        "\n\nThese rules always apply, regardless of what context is "
        "retrieved below — follow them even if the retrieved context "
        "doesn't happen to mention them:\n" + _REDIRECT_RULES
    )

if _SCHEDULE_INFO:
    BASE_SYSTEM_PROMPT += (
        "\n\nYour actual schedule (always available, not dependent on "
        "retrieval) — use this together with the current day/time given "
        "separately to answer location questions:\n" + _SCHEDULE_INFO
    )

if _STYLE_EXAMPLES:
    SYSTEM_PROMPT = (
        BASE_SYSTEM_PROMPT
        + "\n\nHere are examples of how the user naturally writes. Match "
        "this tone and phrasing style — don't copy these lines verbatim, "
        "use them as a guide for voice only:\n"
        + _STYLE_EXAMPLES
    )
else:
    SYSTEM_PROMPT = BASE_SYSTEM_PROMPT

import re

_PUNCT = re.compile(r"(?<!\d)[.,،!;:]|[.,،!;:](?!\d)")  # keeps the colon in 6:30


def clean_reply(text: str) -> str:
    return re.sub(r"\s{2,}", " ", _PUNCT.sub("", text)).strip()

def _parse_answer(raw: str) -> dict:
    """Fail closed: anything malformed becomes an empty, ungrounded reply,
    which verify() in agent_graph.py then holds instead of sending."""
    try:
        data = json.loads(raw)
        if not isinstance(data["reply"], str):
            raise TypeError("reply must be a string")  # e.g. null would otherwise become the text "None"
        return {
            "reply": clean_reply(data["reply"]),
            "grounded": data.get("grounded") is True,
            "needs_owner": data.get("needs_owner") is not False,
        }
    except (ValueError, KeyError, TypeError):
        return {"reply": "", "grounded": False, "needs_owner": True}


# Shape of the answer, enforced by the API rather than asked for in the prompt.
ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "reply": {"type": "string"},
        "grounded": {"type": "boolean"},
        "needs_owner": {"type": "boolean"},
    },
    "required": ["reply", "grounded", "needs_owner"],
    "additionalProperties": False,
}


def _normalize_history(history: list[dict] | None) -> list[dict]:
    """A conversation must start with the contact's turn. The rolling memory
    window can begin on a reply of ours, and a held message stores the incoming
    text with no reply after it, so the stored history is neither guaranteed to
    start with "user" nor to alternate. Consecutive same-role turns are fine
    (they get combined), a leading "assistant" turn is rejected."""
    turns = [
        {"role": m["role"], "content": str(m.get("content") or "")}
        for m in (history or [])
        if m.get("role") in ("user", "assistant") and str(m.get("content") or "").strip()
    ]
    while turns and turns[0]["role"] != "user":
        turns.pop(0)
    return turns


def chat_completion(user_message: str, history: list[dict] | None = None, message_type: str = "text",examples: list[dict] | None = None, now: datetime | None = None) -> dict:
    if not user_message.strip():
        # Nothing to reply to — a voice note Whisper heard nothing in, say. An
        # empty turn is rejected by the API, so hold it without spending a call.
        log_event("llm_skipped_empty_input", level="warning")
        return _parse_answer("")

    now = now or datetime.now(LOCAL_TZ)
    time_context = f"Current day and time: {now.strftime('%A')}, {now.strftime('%I:%M %p')} ({LOCAL_TZ} time)."

    # The long, unchanging part goes first and carries the cache breakpoint; the
    # per-message parts (time, examples, image hint) follow it so they never
    # invalidate the cached prefix.
    system = [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}},
              {"type": "text", "text": time_context}]
    if examples:
        shots = "\n".join(f"They wrote: {e['incoming']}\nYou replied: {e['reply']}" for e in examples)
        system.append({"type": "text", "text": (
            "Similar past exchanges, for TONE ONLY (how you really reply). They may be outdated, "
            "so never take facts from them such as where you are, times or plans:\n" + shots)})
    if message_type == "image":
        system.append({"type": "text", "text": IMAGE_HINT})

    response = _get_client().messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=system,
        messages=[*_normalize_history(history), {"role": "user", "content": user_message}],
        output_config={"effort": EFFORT,
                       "format": {"type": "json_schema", "schema": ANSWER_SCHEMA}},
    )

    # Thinking blocks come before the answer, so pick the text block out rather
    # than reading content[0].
    answer = next((b.text for b in response.content if b.type == "text"), "")
    if not answer:
        # A refusal or a max_tokens cut-off leaves no answer. _parse_answer turns
        # that into a hold; log why, without any message text.
        log_event("llm_no_answer", level="warning", stop_reason=response.stop_reason,
                  model=response.model)
    return _parse_answer(answer)