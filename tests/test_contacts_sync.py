"""The dashboard's end of the contact sync. The merge rules themselves live in
whatsapp-bridge/contacts_sync.js and are tested there (npm test)."""
import httpx
import pytest

from app import dashboard

BRIDGE_REPLY = {
    "status": "ok",
    "added": 2,
    "names": ["Jane Doe", "Otieno"],
    "total": 3,
    "skipped": {"not_saved": 4, "no_number": 0, "no_name": 1, "already_known": 1, "over_limit": 0},
}


@pytest.fixture()
def bridge(monkeypatch):
    """Stands in for the bridge, and records what it was asked for."""
    calls = []

    async def fake_post(path, payload, timeout):
        calls.append({"path": path, "payload": payload, "timeout": timeout})
        return httpx.Response(200, json=BRIDGE_REPLY)

    dashboard._last_send.clear()
    monkeypatch.setattr(dashboard, "_bridge_post", fake_post)
    return calls


def test_sync_asks_the_bridge_and_reports_what_it_added(signed_in, bridge):
    r = signed_in.post("/api/contacts/sync")
    assert r.status_code == 200 and r.json() == BRIDGE_REPLY
    assert bridge[0]["path"] == "/sync-contacts"
    # Reading the address book drives the browser session; a send timeout is too short.
    assert bridge[0]["timeout"] > 30


def test_syncing_twice_in_a_row_is_refused(signed_in, bridge):
    assert signed_in.post("/api/contacts/sync").status_code == 200
    assert signed_in.post("/api/contacts/sync").status_code == 429
    assert len(bridge) == 1


def test_a_bridge_that_fails_is_reported_and_does_not_start_the_cooldown(signed_in, monkeypatch):
    async def failing(path, payload, timeout):
        return httpx.Response(500, text="request failed")

    dashboard._last_send.clear()
    monkeypatch.setattr(dashboard, "_bridge_post", failing)
    assert signed_in.post("/api/contacts/sync").status_code == 502
    assert "sync" not in dashboard._last_send


def test_an_unreachable_bridge_says_so(signed_in, monkeypatch):
    async def unreachable(*args, **kwargs):
        raise httpx.ConnectError("no route")

    dashboard._last_send.clear()
    monkeypatch.setattr(httpx.AsyncClient, "post", unreachable)
    r = signed_in.post("/api/contacts/sync")
    assert r.status_code == 502 and "bridge" in r.json()["detail"].lower()
