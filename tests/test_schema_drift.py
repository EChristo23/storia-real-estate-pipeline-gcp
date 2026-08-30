import json
from unittest.mock import MagicMock

import pytest

from src.ingestion.scraper import DetailScraper, Scrapper


def html_with_script(content: str) -> str:
    return f'<html><body><script id="__NEXT_DATA__">{content}</script></body></html>'


class FakeHtmlResponse:
    def __init__(self, text=""):
        self.text = text

    def raise_for_status(self):
        pass


class FakeBlob:
    def __init__(self, name, content):
        self.name = name
        self._content = content

    def download_as_text(self):
        return self._content


@pytest.fixture
def mock_sync_client(mocker):
    """Patch the httpx.Client used inside setup() with a controllable fake client."""
    fake_client = MagicMock()
    client_cm = MagicMock()
    client_cm.__enter__ = MagicMock(return_value=fake_client)
    client_cm.__exit__ = MagicMock(return_value=False)
    mocker.patch("src.ingestion.scraper.httpx.Client", return_value=client_cm)
    return fake_client


class TestScrapperSetupSchemaDrift:
    def test_renamed_tracking_key_logs_warning_but_keeps_build_id_and_n_pages(self, mock_sync_client, caplog):
        """__NEXT_DATA__ still parses, buildId is still there, but Storia renamed/moved
        props.pageProps.tracking.listing — page_count can't be read, yet setup() should
        not crash and should keep whatever build_id it did find."""
        drifted = {
            "buildId": "abc123",
            "props": {"pageProps": {"trackingRenamed": {"listing": {"page_count": 42}}}},
        }
        mock_sync_client.get = MagicMock(return_value=FakeHtmlResponse(text=html_with_script(json.dumps(drifted))))
        scrapper = Scrapper(n_pages=7, base_url="https://example.test")

        scrapper.setup()

        assert scrapper.build_id == "abc123"
        assert scrapper.n_pages == 7  # left untouched, not derived from page_count
        assert "Structure change" in caplog.text

    def test_renamed_build_id_key_silently_leaves_build_id_none(self, mock_sync_client, caplog):
        """Documents a real gap: buildId is read with full_data.get("buildId"), which
        raises nothing if the key is renamed/removed — setup() ends up with build_id=None
        and logs neither a warning nor a critical about it."""
        drifted = {
            "buildIdRenamed": "abc123",
            "props": {"pageProps": {"tracking": {"listing": {"page_count": 42}}}},
        }
        mock_sync_client.get = MagicMock(return_value=FakeHtmlResponse(text=html_with_script(json.dumps(drifted))))
        scrapper = Scrapper(base_url="https://example.test")

        scrapper.setup()

        assert scrapper.build_id is None
        assert caplog.text == ""


class TestReadSlugsSchemaDrift:
    def test_valid_blob_returns_all_slugs(self):
        content = json.dumps({
            "pageProps": {"data": {"searchAds": {"items": [
                {"id": 1, "slug": "slug-1", "pushedUpAt": "t1"},
                {"id": 2, "slug": "slug-2", "pushedUpAt": "t2"},
            ]}}}
        })
        bucket = MagicMock()
        bucket.list_blobs = MagicMock(return_value=[FakeBlob("casa/2026-01-01/2026-01-01_1.json", content)])
        scraper = DetailScraper(type="casa", date="2026-01-01")

        result = scraper._read_slugs(bucket)

        assert {r["id"] for r in result} == {1, 2}

    def test_item_missing_slug_key_drops_that_item_and_later_items_in_blob(self, caplog):
        """The per-item loop isn't individually try/excepted — a KeyError on one item
        (e.g. Storia renaming 'slug') is only caught around the whole blob, so items
        already collected before the bad one survive, but items after it in the same
        blob are silently lost."""
        content = json.dumps({
            "pageProps": {"data": {"searchAds": {"items": [
                {"id": 1, "slug": "slug-1", "pushedUpAt": "t1"},
                {"id": 2, "pushedUpAt": "t2"},  # missing "slug" — schema drift
                {"id": 3, "slug": "slug-3", "pushedUpAt": "t3"},
            ]}}}
        })
        bucket = MagicMock()
        bucket.list_blobs = MagicMock(return_value=[FakeBlob("casa/2026-01-01/2026-01-01_1.json", content)])
        scraper = DetailScraper(type="casa", date="2026-01-01")

        result = scraper._read_slugs(bucket)

        assert {r["id"] for r in result} == {1}
        assert "Could not parse" in caplog.text

    def test_malformed_blob_shape_skips_that_blob_but_others_still_processed(self, caplog):
        """One blob has an entirely different top-level shape (e.g. searchAds renamed) —
        that blob contributes nothing, but a good blob alongside it is unaffected."""
        drifted_content = json.dumps({"pageProps": {"data": {"searchAdsRenamed": {"items": []}}}})
        good_content = json.dumps({
            "pageProps": {"data": {"searchAds": {"items": [
                {"id": 1, "slug": "slug-1", "pushedUpAt": "t1"},
            ]}}}
        })
        bucket = MagicMock()
        bucket.list_blobs = MagicMock(return_value=[
            FakeBlob("casa/2026-01-01/2026-01-01_1.json", drifted_content),
            FakeBlob("casa/2026-01-01/2026-01-01_2.json", good_content),
        ])
        scraper = DetailScraper(type="casa", date="2026-01-01")

        result = scraper._read_slugs(bucket)

        assert {r["id"] for r in result} == {1}
        assert "Could not parse" in caplog.text
