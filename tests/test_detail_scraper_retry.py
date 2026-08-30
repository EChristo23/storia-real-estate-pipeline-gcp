from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from src.ingestion.scraper import _BACKOFF_BASE, _MAX_RETRIES, DetailScraper


class FakeResponse:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json_data = json_data if json_data is not None else {"pageProps": {}}

    def raise_for_status(self):
        pass

    def json(self):
        return self._json_data


@pytest.fixture(autouse=True)
def no_sleep(mocker):
    """Patch asyncio.sleep in the scraper module so retry/jitter delays don't slow down tests."""
    return mocker.patch("src.ingestion.scraper.asyncio.sleep", new=AsyncMock())


@pytest.fixture
def detail_scraper():
    d = DetailScraper(type="casa", date="2026-01-01", base_url="https://example.test")
    d.build_id = "test-build-id"
    return d


class TestFetchDetailRetry:
    async def test_success_first_attempt_no_retry(self, detail_scraper, mocker):
        client = MagicMock()
        client.get = AsyncMock(return_value=FakeResponse(200, {"pageProps": {"ad": {"id": 101}}}))
        write_detail = mocker.patch.object(detail_scraper, "_write_detail")

        result = await detail_scraper._fetch_detail(client, listing_id=101, slug="some-slug")

        assert result == {"pageProps": {"ad": {"id": 101}}}
        assert client.get.call_count == 1
        write_detail.assert_called_once_with(101, {"pageProps": {"ad": {"id": 101}}}, None)

    @pytest.mark.parametrize("status", [404, 410, 500])
    async def test_gone_status_refreshes_build_id_then_succeeds(self, detail_scraper, mocker, status):
        client = MagicMock()
        client.get = AsyncMock(side_effect=[FakeResponse(status), FakeResponse(200, {"pageProps": {"ad": {}}})])
        setup = mocker.patch.object(detail_scraper, "setup")
        mocker.patch.object(detail_scraper, "_write_detail")

        result = await detail_scraper._fetch_detail(client, listing_id=101, slug="some-slug")

        assert result == {"pageProps": {"ad": {}}}
        assert client.get.call_count == 2
        setup.assert_called_once()

    @pytest.mark.parametrize("status", [404, 410, 500])
    async def test_gone_status_persists_after_refresh_returns_none(self, detail_scraper, mocker, status):
        client = MagicMock()
        client.get = AsyncMock(return_value=FakeResponse(status))
        setup = mocker.patch.object(detail_scraper, "setup")
        write_detail = mocker.patch.object(detail_scraper, "_write_detail")

        result = await detail_scraper._fetch_detail(client, listing_id=101, slug="some-slug")

        assert result is None
        assert client.get.call_count == 2
        setup.assert_called_once()
        write_detail.assert_not_called()

    @pytest.mark.parametrize("status", [429, 403, 503])
    async def test_rate_limited_status_backs_off_then_succeeds(self, detail_scraper, mocker, no_sleep, status):
        client = MagicMock()
        client.get = AsyncMock(side_effect=[FakeResponse(status), FakeResponse(200, {"pageProps": {"ad": {}}})])
        mocker.patch.object(detail_scraper, "_write_detail")

        result = await detail_scraper._fetch_detail(client, listing_id=101, slug="some-slug")

        assert result == {"pageProps": {"ad": {}}}
        assert client.get.call_count == 2
        no_sleep.assert_any_call(_BACKOFF_BASE * (2**0))

    async def test_rate_limited_status_exhausts_retries_returns_none(self, detail_scraper, mocker, no_sleep):
        client = MagicMock()
        client.get = AsyncMock(return_value=FakeResponse(503))
        write_detail = mocker.patch.object(detail_scraper, "_write_detail")

        result = await detail_scraper._fetch_detail(client, listing_id=101, slug="some-slug")

        assert result is None
        assert client.get.call_count == _MAX_RETRIES
        write_detail.assert_not_called()
        expected_backoffs = [((_BACKOFF_BASE * (2**i),), {}) for i in range(_MAX_RETRIES)]
        assert no_sleep.call_args_list[-_MAX_RETRIES:] == expected_backoffs

    async def test_request_error_retries_then_succeeds(self, detail_scraper, mocker, no_sleep):
        client = MagicMock()
        client.get = AsyncMock(side_effect=[httpx.ConnectError("boom"), FakeResponse(200, {"pageProps": {"ad": {}}})])
        mocker.patch.object(detail_scraper, "_write_detail")

        result = await detail_scraper._fetch_detail(client, listing_id=101, slug="some-slug")

        assert result == {"pageProps": {"ad": {}}}
        assert client.get.call_count == 2

    async def test_request_error_exhausts_retries_returns_none(self, detail_scraper, mocker, no_sleep):
        client = MagicMock()
        client.get = AsyncMock(side_effect=httpx.ConnectError("boom"))
        write_detail = mocker.patch.object(detail_scraper, "_write_detail")

        result = await detail_scraper._fetch_detail(client, listing_id=101, slug="some-slug")

        assert result is None
        assert client.get.call_count == _MAX_RETRIES
        write_detail.assert_not_called()

    async def test_unchanged_pushed_up_at_skips_fetch_entirely(self, detail_scraper, mocker, no_sleep):
        client = MagicMock()
        client.get = AsyncMock()

        result = await detail_scraper._fetch_detail(
            client,
            listing_id=101,
            slug="some-slug",
            pushed_up_at="2026-01-01T00:00:00",
            existing={101: "2026-01-01T00:00:00"},
        )

        assert result is None
        client.get.assert_not_called()
        no_sleep.assert_not_called()
