from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from src.ingestion.scraper import _BACKOFF_BASE, _MAX_RETRIES, Scrapper


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, raise_http_error=False):
        self.status_code = status_code
        self._json_data = json_data if json_data is not None else {}
        self._raise_http_error = raise_http_error

    def raise_for_status(self):
        if self._raise_http_error:
            request = httpx.Request("GET", "https://example.test")
            raise httpx.HTTPStatusError(
                f"status {self.status_code}",
                request=request,
                response=httpx.Response(self.status_code, request=request),
            )

    def json(self):
        return self._json_data


@pytest.fixture(autouse=True)
def no_sleep(mocker):
    """Patch asyncio.sleep in the scraper module so retry/jitter delays don't slow down tests."""
    return mocker.patch("src.ingestion.scraper.asyncio.sleep", new=AsyncMock())


@pytest.fixture
def bucket():
    return MagicMock(name="bucket")


@pytest.fixture
def scrapper():
    s = Scrapper(type="casa", n_pages=1, base_url="https://example.test")
    s.build_id = "test-build-id"
    return s


class TestFetchPageRetry:
    async def test_success_first_attempt_no_retry(self, scrapper, bucket, mocker):
        client = MagicMock()
        client.get = AsyncMock(return_value=FakeResponse(200, {"ok": True}))
        write_page = mocker.patch.object(scrapper, "_write_page")

        result = await scrapper._fetch_page(client, bucket, page=1)

        assert result == {"ok": True}
        assert client.get.call_count == 1
        write_page.assert_called_once_with(bucket, 1, {"ok": True})

    @pytest.mark.parametrize("status", [429, 403, 500, 503])
    async def test_retryable_status_then_success(self, scrapper, bucket, mocker, no_sleep, status):
        client = MagicMock()
        client.get = AsyncMock(side_effect=[FakeResponse(status), FakeResponse(200, {"ok": True})])
        mocker.patch.object(scrapper, "_write_page")

        result = await scrapper._fetch_page(client, bucket, page=1)

        assert result == {"ok": True}
        assert client.get.call_count == 2
        no_sleep.assert_any_call(_BACKOFF_BASE * (2**0))

    async def test_retryable_status_exhausts_retries_returns_none(self, scrapper, bucket, mocker, no_sleep):
        client = MagicMock()
        client.get = AsyncMock(return_value=FakeResponse(503))
        write_page = mocker.patch.object(scrapper, "_write_page")

        result = await scrapper._fetch_page(client, bucket, page=1)

        assert result is None
        assert client.get.call_count == _MAX_RETRIES
        write_page.assert_not_called()
        expected_backoffs = [((_BACKOFF_BASE * (2**i),), {}) for i in range(_MAX_RETRIES)]
        assert no_sleep.call_args_list[-_MAX_RETRIES:] == expected_backoffs

    async def test_request_error_retries_then_succeeds(self, scrapper, bucket, mocker, no_sleep):
        client = MagicMock()
        client.get = AsyncMock(side_effect=[httpx.ConnectError("boom"), FakeResponse(200, {"ok": True})])
        mocker.patch.object(scrapper, "_write_page")

        result = await scrapper._fetch_page(client, bucket, page=1)

        assert result == {"ok": True}
        assert client.get.call_count == 2

    async def test_request_error_exhausts_retries_returns_none(self, scrapper, bucket, mocker, no_sleep):
        client = MagicMock()
        client.get = AsyncMock(side_effect=httpx.ConnectError("boom"))
        write_page = mocker.patch.object(scrapper, "_write_page")

        result = await scrapper._fetch_page(client, bucket, page=1)

        assert result is None
        assert client.get.call_count == _MAX_RETRIES
        write_page.assert_not_called()

    async def test_non_retryable_http_error_propagates(self, scrapper, bucket, mocker, no_sleep):
        """Documents current behavior: only httpx.RequestError is caught for retry, so a
        non-retryable HTTP status (e.g. 404) raising HTTPStatusError propagates out of
        _fetch_page on the first attempt instead of being treated as a soft failure."""
        client = MagicMock()
        client.get = AsyncMock(return_value=FakeResponse(404, raise_http_error=True))

        with pytest.raises(httpx.HTTPStatusError):
            await scrapper._fetch_page(client, bucket, page=1)

        assert client.get.call_count == 1
