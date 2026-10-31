"""The notes editor. These two files are the only thing the assistant knows
about its owner, and they live on a volume the image never writes to."""
import pytest

from app import dashboard, llm


@pytest.fixture()
def notes(tmp_path, monkeypatch):
    about, style = tmp_path / "kb" / "about_me.md", tmp_path / "style_examples.md"
    monkeypatch.setattr(dashboard, "NOTES", {"about_me": about, "style": style})
    monkeypatch.setattr(llm, "KB_PATH", about)
    monkeypatch.setattr(llm, "STYLE_EXAMPLES_PATH", style)
    llm._prompt_cache = None
    return about, style


@pytest.mark.parametrize("method,path", [("get", "/api/notes"), ("post", "/api/notes")])
def test_notes_need_the_password(client, method, path):
    assert getattr(client, method)(path).status_code == 401


def test_a_note_can_be_written_where_nothing_exists_yet(signed_in, notes):
    about, _ = notes
    assert not about.exists()
    r = signed_in.post("/api/notes", json={"name": "about_me", "text": "# About me\n\n## Schedule\nMon-Fri campus\n"})
    assert r.status_code == 200 and r.json()["status"] == "saved"
    assert "Mon-Fri campus" in about.read_text(encoding="utf-8")   # the folder was created too


def test_what_was_saved_comes_back(signed_in, notes):
    signed_in.post("/api/notes", json={"name": "style", "text": "- niaje\n- sawa\n"})
    assert signed_in.get("/api/notes").json()["notes"]["style"] == "- niaje\n- sawa\n"


def test_a_file_that_does_not_exist_reads_as_empty_rather_than_failing(signed_in, notes):
    assert signed_in.get("/api/notes").json()["notes"] == {"about_me": "", "style": ""}


def test_only_the_two_known_notes_can_be_written(signed_in, notes, tmp_path):
    for name in ["../../etc/passwd", "app/llm.py", "", "contacts"]:
        r = signed_in.post("/api/notes", json={"name": name, "text": "x"})
        assert r.status_code == 422, name


def test_an_absurdly_long_note_is_refused(signed_in, notes):
    r = signed_in.post("/api/notes", json={"name": "about_me", "text": "x" * 20001})
    assert r.status_code == 422


def test_saving_changes_the_prompt_without_a_restart(signed_in, notes):
    """The whole point: the prompt used to be frozen at import, so an edit only
    took effect on the next deploy."""
    before = llm.system_prompt()
    assert "sells roasted maize in Kawangware" not in before

    signed_in.post("/api/notes", json={
        "name": "about_me",
        "text": "# About me\n\n## About me\nI sell roasted maize in Kawangware.\n"})
    after = llm.system_prompt()
    assert "sells roasted maize in Kawangware" not in after      # not reworded
    assert "I sell roasted maize in Kawangware." in after        # used verbatim
    assert after != before


def test_the_prompt_is_not_rebuilt_when_nothing_changed(signed_in, notes):
    signed_in.post("/api/notes", json={"name": "about_me", "text": "## About me\nhi\n"})
    first = llm.system_prompt()
    assert llm.system_prompt() is first      # same object: the cache held, so caching still hits
