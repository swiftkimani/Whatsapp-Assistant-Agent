"""The fail-closed rule: anything malformed must end up held, never sent."""
import json

import pytest

from app.llm import _parse_answer


def test_valid_answer():
    out = _parse_answer(json.dumps({"reply": " اه ماشي ", "grounded": True,
                                    "needs_owner": False, "why": "just a greeting"}))
    assert out == {"reply": "اه ماشي", "grounded": True, "needs_owner": False,
                   "why": "just a greeting"}


def test_the_reason_is_optional_and_bounded():
    """An older or truncated answer without it must still parse, and a model
    that ignores the 20-word instruction must not fill the Held tab."""
    out = _parse_answer(json.dumps({"reply": "sawa", "grounded": True, "needs_owner": False}))
    assert out["why"] == "" and out["reply"] == "sawa"
    long = _parse_answer(json.dumps({"reply": "sawa", "grounded": True,
                                     "needs_owner": False, "why": "x" * 500}))
    assert len(long["why"]) == 200


@pytest.mark.parametrize("raw", ["", "not json", "[]", "null", '{"grounded": true}', '{"reply": null}'])
def test_malformed_output_fails_closed(raw):
    out = _parse_answer(raw)
    assert out["reply"] == "" and out["grounded"] is False and out["needs_owner"] is True


def test_flags_must_be_real_booleans():
    out = _parse_answer(json.dumps({"reply": "hi", "grounded": "true", "needs_owner": "false"}))
    assert out["grounded"] is False      # the string "true" is not trusted
    assert out["needs_owner"] is True    # only a literal false clears it


def test_missing_needs_owner_defaults_to_holding():
    assert _parse_answer('{"reply": "hi", "grounded": true}')["needs_owner"] is True
