import pytest

from app import main

HEADERS = {"x-bridge-token": "bridge-secret"}


def msg(**over):
    return {"from": "201000000000@c.us", "number": "201000000000", "body": "hi", "type": "text", **over}


@pytest.fixture()
def agent(monkeypatch, fresh_db):
    state = {"action": "send", "hold_reason": ""}

    def fake(contact_id, message_type, raw_text, media_base64):
        return {"resolved_text": raw_text, "reply_text": "اه ماشي", **state}

    monkeypatch.setattr(main, "run_agent", fake)
    # Someone you have not decided about is held by default, which is the point
    # of the setting. These tests are about the sending path, so opt in.
    fresh_db.set_default_mode("auto")
    return state


def test_a_contact_you_have_not_decided_about_is_held_not_answered(client, agent, fresh_db):
    """The opt-in rule: syncing an address book must not silently enrol
    everyone in it for automatic replies."""
    fresh_db.set_default_mode("hold")
    r = client.post("/webhook", json=msg(), headers=HEADERS).json()
    assert r["action"] == "hold" and r["reason"] == "contact_mode"


def test_choosing_one_person_lets_only_that_person_through(signed_in, agent, fresh_db):
    fresh_db.set_default_mode("hold")
    assert signed_in.post("/api/contact-modes", json={"name": "Mom", "mode": "auto"}).status_code == 200
    assert client_action(signed_in, msg()) == "send"
    other = msg(**{"from": "112257593794569@lid", "number": "112257593794569"})
    assert client_action(signed_in, other) == "hold"


def client_action(client, body):
    return client.post("/webhook", json=body, headers=HEADERS).json()["action"]


def test_webhook_needs_the_bridge_token(client, agent):
    assert client.post("/webhook", json=msg()).status_code == 401
    assert client.post("/webhook", json=msg(), headers={"x-bridge-token": "wrong"}).status_code == 401


def test_normal_message_is_sent(client, agent):
    r = client.post("/webhook", json=msg(), headers=HEADERS).json()
    assert r["action"] == "send" and r["reply_text"] == "اه ماشي"


def test_allowlist_uses_the_number_resolved_by_the_bridge(client, agent, monkeypatch):
    monkeypatch.setenv("ALLOWED_CONTACTS", "201000000000")
    lid = msg(**{"from": "112257593794569@lid"})
    assert client.post("/webhook", json=lid, headers=HEADERS).json()["action"] == "send"
    stranger = msg(**{"from": "5@lid", "number": "201999999999"})
    assert client.post("/webhook", json=stranger, headers=HEADERS).json()["action"] == "ignore"


def test_groups_are_ignored_by_default(client, agent):
    assert client.post("/webhook", json=msg(**{"from": "123@g.us"}), headers=HEADERS).json()["action"] == "ignore"


def test_agent_hold_is_queued_with_name_and_reason(signed_in, agent):
    agent.update(action="hold", hold_reason="needs_owner")
    assert signed_in.post("/webhook", json=msg(), headers=HEADERS).json()["action"] == "hold"
    item = signed_in.get("/api/held").json()["items"][0]
    assert item["name"] == "Mom" and item["reason"] == "needs_owner"


def test_kill_switch_holds_everything(signed_in, agent):
    assert signed_in.post("/api/auto-reply", json={"enabled": False}).json()["auto_reply"] is False
    r = signed_in.post("/webhook", json=msg(), headers=HEADERS).json()
    assert r["action"] == "hold" and r["reason"] == "paused"
    signed_in.post("/api/auto-reply", json={"enabled": True})
    assert signed_in.post("/webhook", json=msg(), headers=HEADERS).json()["action"] == "send"


def test_contact_modes(signed_in, agent):
    assert signed_in.post("/api/contact-modes", json={"name": "mom", "mode": "hold"}).json()["name"] == "Mom"
    r = signed_in.post("/webhook", json=msg(), headers=HEADERS).json()
    assert r["action"] == "hold" and r["reason"] == "contact_mode"
    signed_in.post("/api/contact-modes", json={"name": "Mom", "mode": "ignore"})
    assert signed_in.post("/webhook", json=msg(), headers=HEADERS).json()["action"] == "ignore"


def test_unknown_contact_cannot_get_a_mode(signed_in):
    assert signed_in.post("/api/contact-modes", json={"name": "Nobody", "mode": "hold"}).status_code == 400
    assert signed_in.post("/api/contact-modes", json={"name": "Mom", "mode": "bogus"}).status_code == 422


def test_activity_feed_resolves_names(signed_in, agent):
    signed_in.post("/webhook", json=msg(), headers=HEADERS)
    first = signed_in.get("/api/audit").json()["items"][0]
    assert first["kind"] == "auto_reply" and first["name"] == "Mom"


def test_messages_endpoint_lists_both_directions(signed_in, agent):
    signed_in.post("/webhook", json=msg(body="هتيجي؟"), headers=HEADERS)
    items = signed_in.get("/api/messages?range=today").json()["items"]
    assert [(m["direction"], m["name"]) for m in items] == [("out", "Mom"), ("in", "Mom")]
    assert signed_in.get("/api/messages?contact=mom&direction=received").json()["items"][0]["body"] == "هتيجي؟"
    assert signed_in.get("/api/messages?contact=Nobody").status_code == 400
    assert signed_in.get("/api/messages?range=forever").status_code == 422


def test_held_messages_are_logged_as_incoming_only(signed_in, agent):
    agent.update(action="hold", hold_reason="needs_owner")
    signed_in.post("/webhook", json=msg(), headers=HEADERS)
    items = signed_in.get("/api/messages").json()["items"]
    assert [m["direction"] for m in items] == ["in"] and items[0]["outcome"] == "held"


def test_direct_send_switch(signed_in):
    assert signed_in.get("/api/status").json()["direct_send"] is True
    assert signed_in.post("/api/direct-send", json={"enabled": False}).json()["direct_send"] is False
    assert signed_in.post("/api/direct-send", json={"enabled": True}).json()["direct_send"] is True


def test_the_bare_domain_goes_to_the_dashboard(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/dashboard"
    assert client.get("/", follow_redirects=True).status_code == 200


def test_the_default_mode_is_set_from_the_dashboard(signed_in, fresh_db, contacts_file):
    before = signed_in.get("/api/contact-modes").json()
    assert before["default"] == "hold" and before["auto_count"] == 0

    after = signed_in.post("/api/default-mode", json={"mode": "auto"}).json()
    assert after["default"] == "auto"
    assert after["auto_count"] == len(after["contacts"])     # everyone moved with it
    assert fresh_db.default_mode() == "auto"


def test_the_count_reflects_who_was_chosen(signed_in, fresh_db, contacts_file):
    signed_in.post("/api/contact-modes", json={"name": "Mom", "mode": "auto"})
    body = signed_in.get("/api/contact-modes").json()
    assert body["auto_count"] == 1
    assert {c["name"]: c["mode"] for c in body["contacts"]}["Mom"] == "auto"


def test_a_nonsense_default_is_refused(signed_in):
    assert signed_in.post("/api/default-mode", json={"mode": "whatever"}).status_code == 422


def test_setting_the_default_needs_the_password(client):
    assert client.post("/api/default-mode", json={"mode": "auto"}).status_code == 401
