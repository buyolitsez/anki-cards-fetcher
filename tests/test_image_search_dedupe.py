from __future__ import annotations

from cambridge_fetch.image_search import (
    ImageResult,
    collect_unique_image_batch,
    dedupe_image_results,
    normalize_image_url_key,
)


def test_normalize_image_url_key_lowercases_host_and_removes_fragment():
    assert normalize_image_url_key("HTTPS://Example.COM/path/img.jpg?x=1#frag") == "https://example.com/path/img.jpg?x=1"


def test_dedupe_image_results_deduplicates_and_preserves_order():
    results = [
        ImageResult(image_url="https://example.com/a.jpg"),
        ImageResult(image_url="https://example.com/b.jpg"),
        ImageResult(image_url="https://EXAMPLE.com/a.jpg#dup"),
        ImageResult(image_url=""),
    ]
    unique, seen = dedupe_image_results(results)
    assert [item.image_url for item in unique] == [
        "https://example.com/a.jpg",
        "https://example.com/b.jpg",
    ]
    assert seen == {"https://example.com/a.jpg", "https://example.com/b.jpg"}


def test_dedupe_image_results_respects_seen_keys_across_batches():
    first_batch = [
        ImageResult(image_url="https://example.com/a.jpg"),
        ImageResult(image_url="https://example.com/b.jpg"),
    ]
    _, seen = dedupe_image_results(first_batch)
    second_batch = [
        ImageResult(image_url="https://example.com/b.jpg"),
        ImageResult(image_url="https://example.com/c.jpg"),
    ]
    unique, seen = dedupe_image_results(second_batch, seen)
    assert [item.image_url for item in unique] == ["https://example.com/c.jpg"]
    assert seen == {
        "https://example.com/a.jpg",
        "https://example.com/b.jpg",
        "https://example.com/c.jpg",
    }


def test_collect_unique_image_batch_collects_until_target_unique():
    pages = {
        0: [
            ImageResult(image_url="https://example.com/a.jpg"),
            ImageResult(image_url="https://example.com/b.jpg"),
        ],
        2: [
            ImageResult(image_url="https://example.com/b.jpg"),
            ImageResult(image_url="https://example.com/c.jpg"),
        ],
    }

    def fetch_page(offset: int, _limit: int):
        return list(pages.get(offset, []))

    result = collect_unique_image_batch(
        fetch_page,
        start_offset=0,
        batch_size=3,
        page_size=2,
    )
    assert [item.image_url for item in result.results] == [
        "https://example.com/a.jpg",
        "https://example.com/b.jpg",
        "https://example.com/c.jpg",
    ]
    assert result.next_offset == 4
    assert result.exhausted is False
    assert result.reached_page_limit is False


def test_collect_unique_image_batch_marks_exhausted_when_provider_has_no_more():
    pages = {
        0: [ImageResult(image_url="https://example.com/a.jpg")],
    }

    def fetch_page(offset: int, _limit: int):
        return list(pages.get(offset, []))

    result = collect_unique_image_batch(
        fetch_page,
        start_offset=0,
        batch_size=3,
        page_size=3,
    )
    assert [item.image_url for item in result.results] == ["https://example.com/a.jpg"]
    assert result.next_offset == 1
    assert result.exhausted is True
    assert result.reached_page_limit is False


def test_collect_unique_image_batch_stops_on_page_limit_for_duplicate_only_pages():
    duplicate_page = [
        ImageResult(image_url="https://example.com/a.jpg"),
        ImageResult(image_url="https://example.com/b.jpg"),
    ]

    def fetch_page(_offset: int, _limit: int):
        return list(duplicate_page)

    result = collect_unique_image_batch(
        fetch_page,
        start_offset=0,
        batch_size=2,
        page_size=2,
        seen_keys={"https://example.com/a.jpg", "https://example.com/b.jpg"},
        max_page_requests=2,
    )
    assert result.results == []
    assert result.next_offset == 4
    assert result.exhausted is False
    assert result.reached_page_limit is True
