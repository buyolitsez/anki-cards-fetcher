from __future__ import annotations

import json

import pytest

pytest.importorskip("mcp")
pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from cambridge_fetch.core.types import CandidateMatch, SearchResult
from cambridge_fetch.models import Sense
from cambridge_fetch.server import mcp_server
from cambridge_fetch.server.app import create_app
from cambridge_fetch.server.config import ServerSettings
from cambridge_fetch.server.repository import Repository

MANIFEST = {
    "active_preset_id": "default",
    "presets": [
        {
            "id": "default",
            "name": "Default",
            "deck": "english",
            "note_type": "english my",
            "sources": ["cambridge"],
            "field_map": {
                "word": ["Word"],
                "definition": ["Definition"],
                "examples": ["Examples"],
                "audio": ["Audio"],
            },
        }
    ],
    "language_default_presets": {"en": "default"},
}

SENSES = [
    Sense(definition="a structure that divides two areas of land", examples=["a garden fence"], pos="noun"),
    Sense(definition="to sell stolen goods to someone", examples=["he fenced the jewels"], pos="verb"),
]


@pytest.fixture
def repo(tmp_path):
    repository = Repository(tmp_path / "app.db")
    paired = repository.pair_device("desktop")
    repository.save_manifest(paired["device_token"], MANIFEST)
    repository.save_duplicate_index(paired["device_token"], {"items": {"default": ["gate"]}})
    repository.device_token = paired["device_token"]
    return repository


@pytest.fixture(autouse=True)
def fake_search(monkeypatch):
    def _search(request):
        senses = SENSES if request.word == "fence" else []
        candidates = [CandidateMatch(source_id="cambridge", sense=s, summary="", preview="") for s in senses]
        return SearchResult(word=request.word, source_ids=request.source_ids, candidates=candidates)

    monkeypatch.setattr(mcp_server, "search_word", _search)


def _pending_draft(repo):
    items = repo.list_pending(repo.device_token, limit=10)
    assert len(items) == 1
    return items[0]["draft"]


def test_add_picks_sense_by_meaning_and_adds_context(repo):
    tools = mcp_server.AnkiQueueTools(repo)
    result = tools.add_to_anki("fence", context="The thief fenced the stolen jewels", meaning="sell stolen goods")

    assert result["status"] == "queued"
    assert result["chosen_sense"] == SENSES[1].definition
    draft = _pending_draft(repo)
    assert draft["deck_name"] == "english"
    assert draft["note_type_name"] == "english my"
    assert draft["field_values"]["Definition"] == SENSES[1].definition
    assert draft["field_values"]["Examples"].startswith("<i>Seen: The thief fenced the stolen jewels</i><br>1. ")


def test_add_uses_explicit_sense_index(repo):
    result = mcp_server.AnkiQueueTools(repo).add_to_anki("fence", sense_index=0, meaning="sell stolen goods")
    assert result["chosen_sense"] == SENSES[0].definition


def test_duplicates_are_refused_unless_allowed(repo):
    tools = mcp_server.AnkiQueueTools(repo)
    assert tools.add_to_anki("gate", meaning="a door in a fence")["status"] == "duplicate"

    assert tools.add_to_anki("fence")["status"] == "queued"
    assert tools.add_to_anki("Fence")["status"] == "duplicate"
    assert tools.add_to_anki("fence", allow_duplicate=True)["status"] == "queued"


def test_unknown_word_needs_meaning(repo):
    tools = mcp_server.AnkiQueueTools(repo)
    assert tools.add_to_anki("skibidi")["status"] == "not_found"

    result = tools.add_to_anki("skibidi", meaning="nonsense word from internet memes", context="TikTok")
    assert result["status"] == "queued"
    draft = _pending_draft(repo)
    assert draft["source_id"] == "claude"
    assert draft["field_values"] == {
        "Word": "skibidi",
        "Definition": "nonsense word from internet memes",
        "Examples": "<i>Seen: TikTok</i>",
    }


def test_recent_and_cancel(repo):
    tools = mcp_server.AnkiQueueTools(repo)
    queue_id = tools.add_to_anki("fence")["queue_id"]

    assert tools.recent_cards()["items"][0]["status"] == "pending"
    assert tools.cancel_card(queue_id)["status"] == "cancelled"
    assert tools.cancel_card(queue_id)["status"] == "not_cancelled"
    assert repo.list_pending(repo.device_token, limit=10) == []


def _settings(tmp_path, token):
    return ServerSettings(
        database_url=f"sqlite:///{tmp_path / 'app.db'}",
        pair_bootstrap_token="boot",
        public_base_url="",
        telegram_bot_token="",
        telegram_allowed_user_ids=(),
        mcp_path_token=token,
    )


def _rpc(client, path, method, params, request_id=1):
    response = client.post(
        path,
        json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
        headers={"Accept": "application/json, text/event-stream"},
    )
    assert response.status_code == 200, response.text
    for line in response.text.splitlines():
        if line.startswith("data:"):
            return json.loads(line.removeprefix("data:"))
    return response.json()


def test_mcp_endpoint_over_http(repo, tmp_path):
    app = create_app(settings=_settings(tmp_path, "s3cret"), repository=repo)
    with TestClient(app) as client:
        assert client.post("/mcp/wrong", json={}).status_code == 404
        assert client.get("/api/v1/queue/pending").status_code == 401

        init = _rpc(
            client,
            "/mcp/s3cret",
            "initialize",
            {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}},
        )
        assert init["result"]["serverInfo"]["name"] == "Anki cards"

        tools = _rpc(client, "/mcp/s3cret", "tools/list", {}, request_id=2)
        names = {tool["name"] for tool in tools["result"]["tools"]}
        assert names == {"add_to_anki", "lookup_word", "recent_cards", "cancel_card"}

        called = _rpc(
            client,
            "/mcp/s3cret",
            "tools/call",
            {"name": "add_to_anki", "arguments": {"word": "fence", "context": "a garden"}},
            request_id=3,
        )
        assert '"queued"' in called["result"]["content"][0]["text"]
    assert _pending_draft(repo)["query_word"] == "fence"


def test_mcp_disabled_without_token(repo, tmp_path):
    app = create_app(settings=_settings(tmp_path, ""), repository=repo)
    with TestClient(app) as client:
        assert client.post("/mcp/anything", json={}).status_code == 404


def test_access_log_hides_secret_path(repo, tmp_path):
    import logging

    create_app(settings=_settings(tmp_path, "s3cret"), repository=repo)
    record = logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 0, '%s - "%s %s HTTP/%s" %d',
        ("1.2.3.4", "POST", "/mcp/s3cret", "1.1", 200), None,
    )
    for log_filter in logging.getLogger("uvicorn.access").filters:
        log_filter.filter(record)
    assert "s3cret" not in record.getMessage()
