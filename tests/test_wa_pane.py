"""The dashboard's WhatsApp pane: reading the owner's own threads and answering
them. The shaping of chats and messages happens in whatsapp-bridge/wa_read.js
and is tested there (npm test)."""
from types import SimpleNamespace

import httpx
import pytest

from app import dashboard, db, live

CHATS = {"chats": [
    {"id": "254712345678@c.us", "name": "Jane", "is_group": False,
     "unread": 2, "ts": 1762000000, "preview": "niaje", "from_me": False},
]}
THREAD = {
    "chat": {"id": "254712345678@c.us", "name": "Jane", "is_group": False},
    "messages": [{"id": "A", "ts": 1762000000, "from_me": False, "author": "",
                  "body": "niaje", "kind": ""}],
}


@pytest.fixture()
def bridge(monkeypatch):
    """Stands in for the bridge: `calls` records what it was asked for, and a
    test can change `replies` to make one route fail."""
    fake = SimpleNamespace(
        calls=[],
        replies={"/chats": (200, CHATS), "/thread": (200, THREAD), "/send-reply": (200, {"status": "sent"})},
    )

    async def fake_post(path, payload, timeout):
        fake.calls.append({"path": path, "payload": payload})
        code, body = fake.replies[path]
        return httpx.Response(code, json=body)

    dashboard._last_send.clear()
    monkeypatch.setattr(dashboard, "_bridge_post", fake_post)
    return fake


PROTECTED = [("get", "/api/wa/chats"), ("get", "/api/wa/thread?chat_id=1@c.us"),
             ("post", "/api/wa/reply"), ("get", "/api/wa/stream")]


@pytest.mark.parametrize("method,path", PROTECTED)
def test_reading_your_whatsapp_needs_the_password(client, method, path):
    assert getattr(client, method)(path).status_code == 401


def test_chats_come_back_as_the_bridge_shaped_them(signed_in, bridge):
    r = signed_in.get("/api/wa/chats")
    assert r.status_code == 200 and r.json() == CHATS
    assert bridge.calls[0] == {"path": "/chats", "payload": {"limit": 25}}


def test_a_thread_is_asked_for_by_chat_id(signed_in, bridge):
    r = signed_in.get("/api/wa/thread", params={"chat_id": "254712345678@c.us", "limit": 10})
    assert r.status_code == 200 and r.json() == THREAD
    assert bridge.calls[0]["payload"] == {"chat_id": "254712345678@c.us", "limit": 10}


@pytest.mark.parametrize("chat_id", ["", "not-an-id", "254712345678", "254712345678@c.us; rm -rf /",
                                     "status@broadcast", "../../etc/passwd"])
def test_a_chat_id_that_is_not_one_is_refused_before_the_bridge(signed_in, bridge, chat_id):
    assert signed_in.get("/api/wa/thread", params={"chat_id": chat_id}).status_code == 422
    assert bridge.calls == []


def test_a_group_can_be_read_but_not_answered(signed_in, bridge):
    assert signed_in.get("/api/wa/thread", params={"chat_id": "254700000000@g.us"}).status_code == 200
    r = signed_in.post("/api/wa/reply", json={"chat_id": "254700000000@g.us", "text": "hi"})
    assert r.status_code == 422                      # the pattern excludes groups
    assert [c["path"] for c in bridge.calls] == ["/thread"]


def test_a_reply_is_sent_and_recorded_in_the_message_log(signed_in, bridge, fresh_db):
    r = signed_in.post("/api/wa/reply", json={"chat_id": "254712345678@c.us", "text": "niaje, nakuja"})
    assert r.status_code == 200 and r.json() == {"status": "sent"}
    assert bridge.calls[0]["payload"] == {"chat_id": "254712345678@c.us", "text": "niaje, nakuja"}
    logged = db.query_messages(None, None, None, "out", 10)
    assert [(m["direction"], m["body"]) for m in logged] == [("out", "niaje, nakuja")]


def test_a_conversation_that_no_longer_exists_says_so_rather_than_failing_oddly(signed_in, bridge):
    bridge.replies["/send-reply"] = (404, {"error": "no such chat"})
    r = signed_in.post("/api/wa/reply", json={"chat_id": "254712345678@c.us", "text": "hi"})
    assert r.status_code == 404 and "not on WhatsApp" in r.json()["detail"]
    assert "reply" not in dashboard._last_send      # a failure does not start the cooldown


def test_two_replies_in_the_same_instant_are_refused(signed_in, bridge):
    assert signed_in.post("/api/wa/reply", json={"chat_id": "254712345678@c.us", "text": "a"}).status_code == 200
    assert signed_in.post("/api/wa/reply", json={"chat_id": "254712345678@c.us", "text": "b"}).status_code == 429


def test_an_empty_or_oversized_reply_never_reaches_the_bridge(signed_in, bridge):
    for text in ["", " ".join([]), "x" * 4001]:
        assert signed_in.post("/api/wa/reply", json={"chat_id": "254712345678@c.us", "text": text}).status_code == 422
    assert bridge.calls == []


def test_a_bridge_that_cannot_read_whatsapp_is_reported_as_such(signed_in, bridge):
    bridge.replies["/chats"] = (500, {"error": "request failed"})
    r = signed_in.get("/api/wa/chats")
    assert r.status_code == 502 and "could not read" in r.json()["detail"]


# ---- the live stream: the bridge says a conversation moved, dashboards hear ----

def test_only_the_bridge_can_say_a_conversation_moved(client):
    r = client.post("/wa-event", json={"chat_id": "254712345678@c.us"})
    assert r.status_code == 401
    r = client.post("/wa-event", json={"chat_id": "254712345678@c.us"},
                    headers={"x-bridge-token": "wrong"})
    assert r.status_code == 401


def test_an_activity_notice_reaches_every_open_dashboard(client):
    live._subscribers.clear()
    queue = live.subscribe()
    try:
        r = client.post("/wa-event", json={"chat_id": "254712345678@c.us"},
                        headers={"x-bridge-token": "bridge-secret"})
        assert r.status_code == 200
        assert queue.get_nowait() == ("activity", "254712345678@c.us")
    finally:
        live.unsubscribe(queue)


def test_a_notice_about_something_that_is_not_a_chat_is_refused(client):
    live._subscribers.clear()
    queue = live.subscribe()
    try:
        for bad in ["", "status@broadcast", "../etc", "254712345678"]:
            r = client.post("/wa-event", json={"chat_id": bad},
                            headers={"x-bridge-token": "bridge-secret"})
            assert r.status_code == 422, bad
        assert queue.empty()
    finally:
        live.unsubscribe(queue)


def test_a_signed_out_browser_cannot_open_the_stream_and_leaves_nothing_behind(client):
    live._subscribers.clear()
    assert client.get("/api/wa/stream").status_code == 401
    assert live.listeners() == 0
