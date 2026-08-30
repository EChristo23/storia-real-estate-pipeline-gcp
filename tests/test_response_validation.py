import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from src.ingestion.scraper import DetailScraper, Scrapper

VALID_NEXT_DATA = {
    "buildId": "abc123",
    "props": {"pageProps": {"tracking": {"listing": {"page_count": 42}}}},
}


def html_with_script(content: str) -> str:
    return f'<html><body><script id="__NEXT_DATA__">{content}</script></body></html>'


class FakeHtmlResponse:
    def __init__(self, text="", raise_error=False, status_code=200):
        self.text = text
        self.status_code = status_code
        self._raise_error = raise_error

    def raise_for_status(self):
        if self._raise_error:
            request = httpx.Request("GET", "https://example.test")
            raise httpx.HTTPStatusError(
                f"status {self.status_code}",
                request=request,
                response=httpx.Response(self.status_code, request=request),
            )


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, json_error=False):
        self.status_code = status_code
        self._json_data = json_data if json_data is not None else {}
        self._json_error = json_error

    def raise_for_status(self):
        pass

    def json(self):
        if self._json_error:
            raise json.JSONDecodeError("Expecting value", "doc", 0)
        return self._json_data


@pytest.fixture(autouse=True)
def no_sleep(mocker):
    """Patch asyncio.sleep in the scraper module so jitter delays don't slow down async tests."""
    return mocker.patch("src.ingestion.scraper.asyncio.sleep", new=AsyncMock())


@pytest.fixture
def mock_sync_client(mocker):
    """Patch the httpx.Client used inside setup() with a controllable fake client."""
    fake_client = MagicMock()
    client_cm = MagicMock()
    client_cm.__enter__ = MagicMock(return_value=fake_client)
    client_cm.__exit__ = MagicMock(return_value=False)
    mocker.patch("src.ingestion.scraper.httpx.Client", return_value=client_cm)
    return fake_client


class TestScrapperSetupResponseValidation:
    def test_missing_next_data_script_leaves_build_id_none(self, mock_sync_client):
        mock_sync_client.get = MagicMock(return_value=FakeHtmlResponse(text="<html><body>no script here</body></html>"))
        scrapper = Scrapper(base_url="https://example.test")

        scrapper.setup()

        assert scrapper.build_id is None

    def test_invalid_json_in_script_leaves_build_id_none(self, mock_sync_client, caplog):
        mock_sync_client.get = MagicMock(return_value=FakeHtmlResponse(text=html_with_script("{not valid json}")))
        scrapper = Scrapper(base_url="https://example.test")

        scrapper.setup()

        assert scrapper.build_id is None
        assert "Setup failed" in caplog.text

    def test_http_error_leaves_build_id_none(self, mock_sync_client):
        mock_sync_client.get = MagicMock(return_value=FakeHtmlResponse(raise_error=True, status_code=500))
        scrapper = Scrapper(base_url="https://example.test")

        scrapper.setup()

        assert scrapper.build_id is None

    def test_valid_response_sets_build_id_and_page_count(self, mock_sync_client):
        mock_sync_client.get = MagicMock(return_value=FakeHtmlResponse(text=html_with_script(json.dumps(VALID_NEXT_DATA))))
        scrapper = Scrapper(base_url="https://example.test")

        scrapper.setup()

        assert scrapper.build_id == "abc123"
        assert scrapper.n_pages == 42

    def test_valid_response_caps_page_count_at_requested_n_pages(self, mock_sync_client):
        mock_sync_client.get = MagicMock(return_value=FakeHtmlResponse(text=html_with_script(json.dumps(VALID_NEXT_DATA))))
        scrapper = Scrapper(n_pages=5, base_url="https://example.test")

        scrapper.setup()

        assert scrapper.n_pages == 5


class TestDetailScraperSetupResponseValidation:
    def test_missing_next_data_script_leaves_build_id_none(self, mock_sync_client):
        mock_sync_client.get = MagicMock(return_value=FakeHtmlResponse(text="<html><body>no script here</body></html>"))
        scraper = DetailScraper(base_url="https://example.test")

        scraper.setup()

        assert scraper.build_id is None

    def test_invalid_json_in_script_leaves_build_id_none(self, mock_sync_client, caplog):
        mock_sync_client.get = MagicMock(return_value=FakeHtmlResponse(text=html_with_script("{not valid json}")))
        scraper = DetailScraper(base_url="https://example.test")

        scraper.setup()

        assert scraper.build_id is None
        assert "DetailScraper setup failed" in caplog.text

    def test_http_error_leaves_build_id_none(self, mock_sync_client):
        mock_sync_client.get = MagicMock(return_value=FakeHtmlResponse(raise_error=True, status_code=500))
        scraper = DetailScraper(base_url="https://example.test")

        scraper.setup()

        assert scraper.build_id is None

    def test_valid_response_sets_build_id(self, mock_sync_client):
        mock_sync_client.get = MagicMock(return_value=FakeHtmlResponse(text=html_with_script(json.dumps(VALID_NEXT_DATA))))
        scraper = DetailScraper(base_url="https://example.test")

        scraper.setup()

        assert scraper.build_id == "abc123"


@pytest.fixture
def detail_scraper():
    d = DetailScraper(type="casa", date="2026-01-01", base_url="https://example.test")
    d.build_id = "test-build-id"
    return d


class TestFetchDetailRedirectValidation:
    async def test_single_redirect_returns_final_data(self, detail_scraper, mocker):
        client = MagicMock()
        client.get = AsyncMock(
            side_effect=[
                FakeResponse(200, {"pageProps": {"__N_REDIRECT": "/ro/oferta/new-slug"}}),
                FakeResponse(200, {"pageProps": {"ad": {"id": 101}}}),
            ]
        )
        write_detail = mocker.patch.object(detail_scraper, "_write_detail")

        result = await detail_scraper._fetch_detail(client, listing_id=101, slug="old-slug")

        assert result == {"pageProps": {"ad": {"id": 101}}}
        assert client.get.call_count == 2
        write_detail.assert_called_once_with(101, {"pageProps": {"ad": {"id": 101}}}, None)

    async def test_double_redirect_returns_none(self, detail_scraper, mocker):
        client = MagicMock()
        client.get = AsyncMock(
            side_effect=[
                FakeResponse(200, {"pageProps": {"__N_REDIRECT": "/ro/oferta/slug-a"}}),
                FakeResponse(200, {"pageProps": {"__N_REDIRECT": "/ro/oferta/slug-b"}}),
            ]
        )
        write_detail = mocker.patch.object(detail_scraper, "_write_detail")

        result = await detail_scraper._fetch_detail(client, listing_id=101, slug="old-slug")

        assert result is None
        assert client.get.call_count == 2
        write_detail.assert_not_called()

    async def test_redirect_target_non_json_returns_none(self, detail_scraper, mocker):
        client = MagicMock()
        client.get = AsyncMock(
            side_effect=[
                FakeResponse(200, {"pageProps": {"__N_REDIRECT": "/ro/oferta/new-slug"}}),
                FakeResponse(200, json_error=True),
            ]
        )
        write_detail = mocker.patch.object(detail_scraper, "_write_detail")

        result = await detail_scraper._fetch_detail(client, listing_id=101, slug="old-slug")

        assert result is None
        assert client.get.call_count == 2
        write_detail.assert_not_called()
