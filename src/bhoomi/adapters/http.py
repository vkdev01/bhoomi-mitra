"""Shared HTTP plumbing for the outbound adapters.

One place for timeouts, retries and error translation, so each provider adapter
stays a thin mapping from wire format to domain objects.

Two realities of Indian government geospatial services are handled here rather
than in every adapter:

* several endpoints answer HTTP 200 while returning a JSON *error* body;
* some endpoints wrap their JSON in an HTML page (the LULC 250k service does).
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Mapping
from typing import Any

import httpx

from bhoomi.domain.errors import UpstreamAuthError, UpstreamUnavailableError

_JSON_BLOCK = re.compile(r"(\[.*\]|\{.*\})", re.DOTALL)
_ERROR_KEYS = ("error", "errorCode", "error_code")


class HttpJsonClient:
    """A small retrying JSON client over ``httpx``."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout_s: float = 20.0,
        max_retries: int = 2,
        backoff_s: float = 0.6,
        default_headers: Mapping[str, str] | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._max_retries = max(0, max_retries)
        self._backoff_s = backoff_s
        self._headers = dict(default_headers or {})
        self._client = client or httpx.Client(timeout=timeout_s, follow_redirects=True)

    def __enter__(self) -> HttpJsonClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    # -- public -----------------------------------------------------------

    def get(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        return self._request("GET", path, params=params, headers=headers)

    def post(
        self,
        path: str,
        *,
        json_body: Any = None,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        return self._request(
            "POST", path, params=params, json_body=json_body, headers=headers
        )

    def post_multipart(
        self,
        path: str,
        *,
        body: bytes,
        content_type: str,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        """POST a pre-encoded multipart body and parse the JSON response."""
        response = self._send(
            "POST",
            path,
            headers={**dict(headers or {}), "Content-Type": content_type},
            content=body,
        )
        return parse_json_body(response.text)

    def post_bytes(
        self,
        path: str,
        *,
        content: bytes,
        headers: Mapping[str, str] | None = None,
    ) -> bytes:
        response = self._send(
            "POST", path, headers=headers, content=content, expect_json=False
        )
        return response.content

    # -- internals --------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Any = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        response = self._send(
            method, path, params=params, json_body=json_body, headers=headers
        )
        return parse_json_body(response.text)

    def _send(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Any = None,
        headers: Mapping[str, str] | None = None,
        content: bytes | None = None,
        expect_json: bool = True,
    ) -> httpx.Response:
        url = f"{self._base_url}/{path.lstrip('/')}"
        merged = {**self._headers, **(headers or {})}
        last_error: Exception | None = None

        for attempt in range(self._max_retries + 1):
            try:
                response = self._client.request(
                    method,
                    url,
                    params=_clean_params(params),
                    json=json_body,
                    content=content,
                    headers=merged,
                )
            except httpx.TimeoutException as exc:
                last_error = exc
            except httpx.HTTPError as exc:
                last_error = exc
            else:
                if response.status_code in (401, 403):
                    raise UpstreamAuthError(
                        f"{url} rejected the credentials "
                        f"(HTTP {response.status_code}): {_snippet(response.text)}"
                    )
                if response.status_code >= 500:
                    last_error = UpstreamUnavailableError(
                        f"{url} returned HTTP {response.status_code}"
                    )
                elif response.status_code >= 400:
                    raise UpstreamUnavailableError(
                        f"{url} returned HTTP {response.status_code}: "
                        f"{_snippet(response.text)}"
                    )
                else:
                    if expect_json:
                        _raise_on_error_body(response.text, url)
                    return response

            if attempt < self._max_retries:
                time.sleep(self._backoff_s * (2**attempt))

        raise UpstreamUnavailableError(
            f"{url} failed after {self._max_retries + 1} attempt(s): {last_error}"
        )


def _clean_params(params: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not params:
        return None
    return {k: v for k, v in params.items() if v is not None}


def _snippet(text: str, limit: int = 200) -> str:
    return " ".join((text or "").split())[:limit]


def _raise_on_error_body(text: str, url: str) -> None:
    """Bhuvan answers 200 with ``{"error": ...}`` for a bad token.

    Some endpoints wrap that body in an HTML page, so this must use the same
    tolerant extraction as a normal response - otherwise an auth failure looks
    like an empty success.
    """
    payload = _try_parse(text)
    if not isinstance(payload, dict):
        return
    for key in _ERROR_KEYS:
        if key in payload:
            message = payload.get("error_description") or payload.get(key)
            if key in ("error",) and str(payload.get("error")) in ("", "None"):
                continue
            raise UpstreamAuthError(f"{url} reported {key}={message}")


_MISSING = object()


def _try_parse(text: str) -> Any:
    """Best-effort JSON extraction. Returns ``_MISSING`` when nothing parses."""
    if not text:
        return _MISSING
    stripped = text.strip()
    if not stripped:
        return _MISSING

    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    match = _JSON_BLOCK.search(stripped)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    if stripped.lower() in ("false", "null"):
        return None
    return _MISSING


def parse_json_body(text: str) -> Any:
    """Parse a JSON body that may be embedded in an HTML wrapper."""
    parsed = _try_parse(text)
    if parsed is _MISSING:
        raise UpstreamUnavailableError(
            f"response was not JSON: {_snippet(text or '')}"
        )
    return parsed
