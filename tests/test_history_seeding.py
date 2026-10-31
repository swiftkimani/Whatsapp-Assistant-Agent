"""The first reply to someone should not be written blind: WhatsApp has been
holding the conversation all along, so it is pulled in once."""
import httpx
import pytest

from app import db, memory

THREAD = {"messages": [
    {"ts": 1, "from_me": False, "body": "niaje", "kind": ""},
    {"ts": 2, "from_me": True, "body": "poa, uko aje", "kind": ""},
    {"ts": 3, "from_me": False, "body": "", "kind": "Voice note"},
]}
CHAT = "254712345678@c.us"


@pytest.fixture()
def bridge(monkeypatch):
    calls = []

    def fake_post(path, payload, timeout):
        calls.append({"path": path, "payload": payload})
        return httpx.Response(200, json=THREAD)

    monkeypatch.setattr(memory.bridge, "post_sync", fake_post)
    monkeypatch.delenv("SEED_HISTORY", raising=False)
    monkeypatch.delenv("HISTORY_TURNS", raising=False)
    return calls


def test_the_real_thread_becomes_the_opening_context(fresh_db, bridge):
    assert memory.seed_from_whatsapp(CHAT) == 3
    assert bridge[0]["path"] == "/thread"
    assert [(m["role"], m["content"]) for m in memory.get_history(CHAT)] == [
        ("user", "niaje"),
        ("assistant", "poa, uko aje"),
        ("user", "[Voice note]"),       # an attachment still happened; a blank turn would mislead
    ]


def test_what_you_sent_is_marked_as_yours(fresh_db, bridge):
    memory.seed_from_whatsapp(CHAT)
    roles = [m["role"] for m in memory.get_history(CHAT)]
    assert roles[1] == "assistant"      # from_me, so it was the owner speaking


def test_a_bridge_that_is_down_costs_context_not_the_reply(fresh_db, monkeypatch):
    def unreachable(path, payload, timeout):
        raise httpx.ConnectError("no route")

    monkeypatch.setattr(memory.bridge, "post_sync", unreachable)
    assert memory.seed_from_whatsapp(CHAT) == 0
    assert memory.get_history(CHAT) == []


def test_a_bridge_error_is_not_mistaken_for_an_empty_conversation(fresh_db, monkeypatch):
    monkeypatch.setattr(memory.bridge, "post_sync",
                        lambda path, payload, timeout: httpx.Response(500, text="boom"))
    assert memory.seed_from_whatsapp(CHAT) == 0


def test_seeding_can_be_switched_off(fresh_db, bridge, monkeypatch):
    monkeypatch.setenv("SEED_HISTORY", "false")
    assert memory.seed_from_whatsapp(CHAT) == 0
    assert bridge == []


def test_history_depth_is_configurable_and_bounded(monkeypatch):
    monkeypatch.setenv("HISTORY_TURNS", "3")
    assert memory._keep() == 6
    monkeypatch.setenv("HISTORY_TURNS", "not a number")
    assert memory._keep() == 24
    monkeypatch.setenv("HISTORY_TURNS", "9999")
    assert memory._keep() == 100          # capped, so one contact cannot blow up the prompt


def test_the_agent_only_seeds_when_it_has_nothing(fresh_db, bridge):
    from app import agent_graph

    db.add_message(CHAT, "user", "already known", keep=24)
    state = agent_graph.fetch_history({"contact_id": CHAT})
    assert [m["content"] for m in state["history"]] == ["already known"]
    assert bridge == []                   # the stored conversation wins; no round trip
