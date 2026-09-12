"""Slack reads and bounded private-file downloads. Never log URLs or tokens."""

from urllib.parse import urlsplit

import httpx
from slack_sdk.errors import SlackApiError
from slack_sdk.web.async_client import AsyncWebClient

from app.core.errors import BankReconError, ErrorCode


def slack_client(token: str) -> AsyncWebClient:
    if not token:
        raise BankReconError(ErrorCode.E_SLACK_UNAVAILABLE)
    return AsyncWebClient(token=token, timeout=20, retry_handlers=[])


def validate_file_url(url: str) -> None:
    try:
        parsed = urlsplit(url)
        valid = (parsed.scheme == "https" and parsed.hostname == "files.slack.com"
                 and parsed.port in (None, 443) and not parsed.username and not parsed.password)
    except ValueError:
        valid = False
    if not valid:
        raise BankReconError(ErrorCode.E_VALIDATION, detail="The attachment is not hosted on Slack's permitted file host.")


async def file_info(client, file_id: str) -> dict:
    try:
        response = await client.files_info(file=file_id)
    except SlackApiError as exc:
        if exc.response.get("error") in {"file_not_found", "file_not_visible", "access_denied"}:
            raise BankReconError(ErrorCode.E_FILE_NOT_VISIBLE) from exc
        if exc.response.get("error") == "missing_scope":
            raise BankReconError(ErrorCode.E_VALIDATION, detail="The Slack app needs files:read. Add that bot scope, reinstall the app, then reply retry.") from exc
        raise
    return response["file"]


async def download_file(info: dict, token: str, max_bytes: int, *, transport=None) -> bytes:
    if info.get("is_external") or info.get("mode") == "external":
        raise BankReconError(ErrorCode.E_VALIDATION, detail="Upload the actual file to Slack; external file links are not supported.")
    try:
        declared_size = int(info.get("size") or 0)
    except (ValueError, TypeError) as exc:
        raise BankReconError(ErrorCode.E_VALIDATION, detail="The attachment has invalid size metadata.") from exc
    if declared_size < 0 or declared_size > max_bytes:
        raise BankReconError(ErrorCode.E_VALIDATION, detail="The attachment exceeds the permitted size.")
    url = info.get("url_private_download") or info.get("url_private") or ""
    async with httpx.AsyncClient(timeout=30, follow_redirects=False, transport=transport) as http:
        for _ in range(4):
            validate_file_url(url)
            async with http.stream("GET", url, headers={"Authorization": f"Bearer {token}"}) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    url = str(response.url.join(response.headers.get("location", "")))
                    continue
                if response.status_code in {401, 403, 404}:
                    raise BankReconError(ErrorCode.E_FILE_NOT_VISIBLE)
                response.raise_for_status()
                chunks, size = [], 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > max_bytes:
                        raise BankReconError(ErrorCode.E_VALIDATION, detail="The attachment exceeds the permitted size.")
                    chunks.append(chunk)
                return b"".join(chunks)
    raise BankReconError(ErrorCode.E_VALIDATION, detail="The attachment has too many redirects.")
