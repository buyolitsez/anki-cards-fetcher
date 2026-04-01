from __future__ import annotations

from cambridge_fetch.core.types import NoteDraft
from cambridge_fetch.server.repository import Repository


def test_repository_pair_manifest_and_queue(tmp_path):
    repo = Repository(tmp_path / "app.db")
    paired = repo.pair_device("desktop")

    repo.save_manifest(
        paired["device_token"],
        {
            "active_preset_id": "default",
            "presets": [{"id": "default", "name": "Default", "sources": ["cambridge"]}],
            "language_default_presets": {"en": "default"},
            "decks": ["Words"],
            "note_types": ["Basic"],
        },
    )
    repo.save_duplicate_index(paired["device_token"], {"items": {"default": ["fence"]}})
    manifest = repo.latest_manifest()
    assert manifest["active_preset_id"] == "default"
    assert repo.duplicate_index_for_client(manifest["client_id"])["items"]["default"] == ["fence"]

    draft = NoteDraft(
        schema_version=1,
        source_id="cambridge",
        query_word="fence",
        resolved_preset_id="default",
        resolved_preset_name="Default",
        deck_name="Words",
        note_type_name="Basic",
        field_values={"Word": "fence"},
        word_field_names=["Word"],
        audio_field_names=[],
        picture_field_names=[],
        duplicate_key="fence",
        definition="a barrier",
        pos="noun",
        examples=[],
        synonyms=[],
        ipa=None,
        audio_url=None,
        audio_region=None,
        picture_url=None,
        picture_referer=None,
        picture_thumb_url=None,
    )
    queued = repo.enqueue_draft(client_id=manifest["client_id"], telegram_user_id=123, draft=draft)
    pending = repo.list_pending(paired["device_token"], limit=10)
    assert pending[0]["id"] == queued["id"]

    repo.mark_complete(paired["device_token"], queued["id"], 99)
    assert repo.list_pending(paired["device_token"], limit=10) == []
