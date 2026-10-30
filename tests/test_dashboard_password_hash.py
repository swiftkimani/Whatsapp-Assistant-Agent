"""Logging in against an argon2id hash instead of a plaintext password.

The hash is what makes the dashboard safe to expose beyond loopback, so the
plaintext variable must stop being consulted the moment a hash is configured.
"""
import pytest
from argon2 import PasswordHasher

from app import dashboard

GOOD = "a-long-enough-password"


@pytest.fixture()
def hashed(monkeypatch):
    monkeypatch.setenv("DASHBOARD_PASSWORD_HASH", PasswordHasher().hash(GOOD))
    return GOOD


def test_a_hash_is_accepted_and_a_wrong_password_is_not(hashed):
    assert dashboard._check_password(GOOD)
    assert not dashboard._check_password("not-it")


def test_the_hash_wins_over_a_plaintext_password(hashed, monkeypatch):
    monkeypatch.setenv("DASHBOARD_PASSWORD", "something-else")
    assert dashboard._check_password(GOOD)
    assert not dashboard._check_password("something-else"), "plaintext must be ignored once hashed"


def test_a_corrupt_hash_rejects_rather_than_raising(monkeypatch):
    monkeypatch.setenv("DASHBOARD_PASSWORD_HASH", "not-an-argon2-hash")
    assert not dashboard._check_password(GOOD)


def test_sessions_are_signed_with_the_hash_so_changing_it_signs_everyone_out(hashed, monkeypatch):
    before = dashboard._session_key()
    monkeypatch.setenv("DASHBOARD_PASSWORD_HASH", PasswordHasher().hash("a-different-password"))
    assert dashboard._session_key() != before


def test_login_over_http_works_against_a_hash(client, monkeypatch):
    monkeypatch.setenv("DASHBOARD_PASSWORD_HASH", PasswordHasher().hash(GOOD))
    assert client.post("/api/login", json={"password": "wrong-one"}).status_code == 401
    assert client.post("/api/login", json={"password": GOOD}).status_code == 200
    assert client.get("/api/session").status_code == 200
