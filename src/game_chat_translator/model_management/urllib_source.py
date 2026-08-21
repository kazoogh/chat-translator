from __future__ import annotations

from collections.abc import Iterator
from http.client import HTTPMessage, HTTPResponse
from typing import IO
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> None:
        return None


class _TrustedModelRedirects(HTTPRedirectHandler):
    def __init__(self, requested_url: str) -> None:
        self._origin = urlparse(requested_url).hostname

    def redirect_request(
        self,
        req: Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> Request | None:
        target = urlparse(newurl)
        if (
            self._origin != "huggingface.co"
            or target.scheme != "https"
            or not target.hostname
            or not (
                target.hostname == "huggingface.co"
                or target.hostname.endswith(".hf.co")
                or target.hostname.endswith(".huggingface.co")
            )
        ):
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class UrllibDownloadResponse:
    def __init__(
        self,
        response: HTTPResponse,
        requested_url: str,
        offset: int,
        *,
        trusted_redirect: bool,
    ) -> None:
        self._response = response
        actual_url = response.geturl()
        self.final_url = requested_url if trusted_redirect else actual_url
        self.supports_resume = response.status == 206
        self.total_size = _total_size(response.headers, offset)
        if self.final_url != requested_url:
            self.close()
            raise OSError("model endpoint redirected")
        if offset and not self.supports_resume:
            # The lifecycle manager will restart from zero using this explicit signal.
            self.total_size = _content_length(response.headers)

    def chunks(self, size: int) -> Iterator[bytes]:
        while chunk := self._response.read(size):
            yield chunk

    def close(self) -> None:
        self._response.close()


class UrllibModelSource:
    """Production HTTPS source used only for an explicit model-download command."""

    def __init__(self, *, timeout_seconds: float = 30.0) -> None:
        if timeout_seconds <= 0:
            raise ValueError("download timeout must be positive")
        self._timeout = timeout_seconds

    def open(self, url: str, *, offset: int) -> UrllibDownloadResponse:
        if not url.startswith("https://") or offset < 0:
            raise OSError("unsafe model download request")
        headers = {"Accept-Encoding": "identity", "User-Agent": "GameChatTranslator/0.1"}
        if offset:
            headers["Range"] = f"bytes={offset}-"
        trusted_redirect = urlparse(url).hostname == "huggingface.co"
        redirect_handler: HTTPRedirectHandler = (
            _TrustedModelRedirects(url) if trusted_redirect else _RejectRedirects()
        )
        opener = build_opener(redirect_handler)
        try:
            response = opener.open(Request(url, headers=headers), timeout=self._timeout)
        except (HTTPError, URLError, TimeoutError, ValueError) as exc:
            raise OSError("model endpoint was unavailable") from exc
        return UrllibDownloadResponse(response, url, offset, trusted_redirect=trusted_redirect)


def _content_length(headers: HTTPMessage) -> int | None:
    raw = headers.get("Content-Length")
    try:
        return int(raw) if raw is not None else None
    except ValueError:
        return None


def _total_size(headers: HTTPMessage, offset: int) -> int | None:
    content_range = headers.get("Content-Range")
    if content_range and "/" in content_range:
        raw_total = content_range.rsplit("/", 1)[-1]
        try:
            return int(raw_total)
        except ValueError:
            return None
    length = _content_length(headers)
    return None if length is None else length + (offset if offset else 0)
