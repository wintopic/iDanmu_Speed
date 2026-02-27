#!/usr/bin/env python3
"""Pure Python danmu batch downloader.

This module is used by both CLI and GUI. It can also auto-start local
danmu_api-main when the target API is localhost.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import socket
import threading
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from http import client as http_client
from pathlib import Path
from typing import Any, Callable
from urllib import error as url_error
from urllib import parse as url_parse

import local_danmu_api

DEFAULTS: dict[str, Any] = {
    "base_url": local_danmu_api.DEFAULT_LOCAL_BASE_URL,
    "token": "",
    "input": "",
    "output": "downloads",
    "format": "xml",
    "naming_rule": "{index:03d}_{base}",
    "concurrency": 6,
    "retries": 5,
    "retry_delay_ms": 1500,
    "throttle_ms": 120,
    "timeout_ms": 45000,
    "local_api": "auto",
}

RETRYABLE_WINERROR_CODES = {10053, 10054, 10060, 10061}
RETRYABLE_ERRNO_CODES = {54, 60, 104, 110, 111, 113}
MAX_RETRY_DELAY_MS = 120000
RETRY_JITTER_RATIO = 0.25
RETRY_AFTER_STATUSES = {429, 503}
FINAL_RATE_LIMIT_COOLDOWN_MS = 30000
FINAL_NETWORK_COOLDOWN_MS = 15000
RETRYABLE_ERROR_HINTS = (
    "connection reset",
    "connection aborted",
    "forcibly closed",
    "timed out",
    "temporary failure",
    "eof occurred in violation of protocol",
    "ssl: wrong version number",
    "getaddrinfo failed",
    "name or service not known",
    "no route to host",
    "network is unreachable",
    "winerror 10053",
    "winerror 10054",
    "winerror 10060",
    "winerror 10061",
    "强迫关闭了一个现有的连接",
)


_THREAD_LOCAL_STATE = threading.local()
_RATE_LIMIT_LOCK = threading.Lock()
_RATE_LIMIT_UNTIL_MONOTONIC = 0.0


class HttpError(RuntimeError):
    def __init__(self, message: str, status: int, body: str, headers: dict[str, str] | None = None):
        super().__init__(message)
        self.status = status
        self.body = body
        self.headers = headers or {}


def _iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _ensure_str(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _wait_for_shared_retry_gate() -> None:
    while True:
        with _RATE_LIMIT_LOCK:
            wait_sec = _RATE_LIMIT_UNTIL_MONOTONIC - time.monotonic()
        if wait_sec <= 0:
            return
        time.sleep(min(wait_sec, 1.0))


def _extend_shared_retry_gate(wait_ms: int) -> None:
    if wait_ms <= 0:
        return
    target = time.monotonic() + (wait_ms / 1000)
    with _RATE_LIMIT_LOCK:
        global _RATE_LIMIT_UNTIL_MONOTONIC
        if target > _RATE_LIMIT_UNTIL_MONOTONIC:
            _RATE_LIMIT_UNTIL_MONOTONIC = target


def _parse_maybe_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _parse_bool(value: Any) -> bool:
    text = _ensure_str(value).lower()
    return text in {"1", "true", "yes"}


def _sanitize_windows_filename(raw_name: str) -> str:
    name = _ensure_str(raw_name) or "danmu"
    invalid = '<>:"/\\|?*'
    cleaned = []
    for ch in name:
        if ch in invalid or ord(ch) < 32:
            cleaned.append("_")
        else:
            cleaned.append(ch)
    name = "".join(cleaned).rstrip(". ").strip()
    name = " ".join(name.split())

    reserved = {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        "COM1",
        "COM2",
        "COM3",
        "COM4",
        "COM5",
        "COM6",
        "COM7",
        "COM8",
        "COM9",
        "LPT1",
        "LPT2",
        "LPT3",
        "LPT4",
        "LPT5",
        "LPT6",
        "LPT7",
        "LPT8",
        "LPT9",
    }
    if name.upper() in reserved:
        name = f"_{name}"
    if not name:
        name = "danmu"
    if len(name) > 120:
        name = name[:120]
    return name


def _normalize_api_root(base_url: str, token: str) -> str:
    parsed = url_parse.urlsplit(base_url)
    if not parsed.scheme:
        parsed = url_parse.urlsplit("http://" + base_url)
    if not parsed.netloc:
        raise RuntimeError(f"Invalid base URL: {base_url}")

    pathname = parsed.path.rstrip("/")
    if token:
        pathname = f"{pathname}/{url_parse.quote(token)}"
    if not pathname:
        pathname = "/"

    rebuilt = parsed._replace(path=pathname, query="", fragment="")
    return url_parse.urlunsplit(rebuilt).rstrip("/")


def _parse_csv_line(line: str) -> list[str]:
    # csv.reader handles quoted commas correctly.
    return next(csv.reader([line]))


def load_tasks(input_path: str | Path) -> list[dict[str, Any]]:
    path = Path(input_path)
    text = path.read_text(encoding="utf-8-sig")
    ext = path.suffix.lower()

    if ext in {".jsonl", ".ndjson", ".txt"}:
        tasks: list[dict[str, Any]] = []
        for line in text.splitlines():
            trimmed = line.strip()
            if not trimmed or trimmed.startswith("#"):
                continue
            tasks.append(json.loads(trimmed))
        return tasks

    if ext == ".json":
        payload = json.loads(text)
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict) and isinstance(payload.get("tasks"), list):
            return payload["tasks"]
        raise RuntimeError("JSON file must be a list or an object with a 'tasks' list.")

    if ext == ".csv":
        lines = [line for line in text.splitlines() if line.strip()]
        if not lines:
            return []
        headers = _parse_csv_line(lines[0])
        tasks = []
        for line in lines[1:]:
            columns = _parse_csv_line(line)
            row: dict[str, Any] = {}
            for index, header in enumerate(headers):
                row[header] = columns[index] if index < len(columns) else ""
            tasks.append(row)
        return tasks

    raise RuntimeError(f"Unsupported input extension: {ext}")


def _normalize_task(raw_task: dict[str, Any], index: int) -> dict[str, Any]:
    task = {
        "index": index + 1,
        "name": _ensure_str(raw_task.get("name")),
        "url": _ensure_str(raw_task.get("url")),
        "fileName": _ensure_str(raw_task.get("fileName") or raw_task.get("filename")),
        "anime": _ensure_str(raw_task.get("anime")),
        "episode": _ensure_str(raw_task.get("episode")),
        "commentId": _parse_maybe_int(raw_task.get("commentId", raw_task.get("commentid"))),
        "format": _ensure_str(raw_task.get("format")).lower(),
        "disabled": _parse_bool(raw_task.get("disabled")),
    }
    if task["format"] not in {"", "json", "xml"}:
        raise RuntimeError(f"Task {task['index']} has invalid format: {task['format']}")
    return task


def _task_mode(task: dict[str, Any]) -> str:
    if task["url"]:
        return "url"
    if task["commentId"]:
        return "commentId"
    if task["fileName"]:
        return "fileName"
    if task["anime"]:
        return "anime"
    return ""


def _is_retryable_status(status: int) -> bool:
    return status in {408, 425, 429} or 500 <= status <= 599


def _iter_exception_chain(exc: BaseException):
    pending: list[BaseException] = [exc]
    seen: set[int] = set()
    while pending:
        current = pending.pop(0)
        marker = id(current)
        if marker in seen:
            continue
        seen.add(marker)
        yield current

        if isinstance(current, url_error.URLError) and isinstance(current.reason, BaseException):
            pending.append(current.reason)

        cause = getattr(current, "__cause__", None)
        if isinstance(cause, BaseException):
            pending.append(cause)

        context = getattr(current, "__context__", None)
        if isinstance(context, BaseException):
            pending.append(context)


def _is_retryable_network_error(exc: BaseException) -> bool:
    for error_item in _iter_exception_chain(exc):
        if isinstance(
            error_item,
            (
                TimeoutError,
                socket.timeout,
                ConnectionResetError,
                ConnectionAbortedError,
                ConnectionRefusedError,
                BrokenPipeError,
                http_client.HTTPException,
            ),
        ):
            return True

        if isinstance(error_item, OSError):
            winerror = getattr(error_item, "winerror", None)
            errno = getattr(error_item, "errno", None)
            if winerror in RETRYABLE_WINERROR_CODES or errno in RETRYABLE_ERRNO_CODES:
                return True

        message = str(error_item).lower()
        if any(hint in message for hint in RETRYABLE_ERROR_HINTS):
            return True

    return False


def _network_error_message(exc: BaseException) -> str:
    if isinstance(exc, url_error.URLError):
        return str(exc.reason)
    return str(exc)


def _thread_connection_cache() -> dict[tuple[str, str, float], http_client.HTTPConnection]:
    cache = getattr(_THREAD_LOCAL_STATE, "connection_cache", None)
    if cache is None:
        cache = {}
        _THREAD_LOCAL_STATE.connection_cache = cache
    return cache


def _close_thread_connection(conn_key: tuple[str, str, float]) -> None:
    conn = _thread_connection_cache().pop(conn_key, None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass


def _get_thread_connection(scheme: str, netloc: str, timeout_sec: float) -> tuple[tuple[str, str, float], http_client.HTTPConnection]:
    conn_key = (scheme, netloc, timeout_sec)
    cache = _thread_connection_cache()
    conn = cache.get(conn_key)
    if conn is None:
        if scheme == "https":
            conn = http_client.HTTPSConnection(netloc, timeout=timeout_sec)
        elif scheme == "http":
            conn = http_client.HTTPConnection(netloc, timeout=timeout_sec)
        else:
            raise RuntimeError(f"Unsupported URL scheme: {scheme}")
        cache[conn_key] = conn
    return conn_key, conn


def _request_once(
    *,
    url: str,
    method: str,
    headers: dict[str, str],
    payload: bytes | None,
    timeout_sec: float,
) -> tuple[int, str, dict[str, str]]:
    parsed = url_parse.urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError(f"Invalid request URL: {url}")

    target = parsed.path or "/"
    if parsed.query:
        target = f"{target}?{parsed.query}"

    conn_key, conn = _get_thread_connection(parsed.scheme, parsed.netloc, timeout_sec)
    try:
        conn.request(method.upper(), target, body=payload, headers=headers)
        response = conn.getresponse()
        text = response.read().decode("utf-8", errors="replace")
        response_headers = {key.lower(): value for key, value in response.getheaders()}
    except Exception:
        _close_thread_connection(conn_key)
        raise

    if response.will_close:
        _close_thread_connection(conn_key)

    return response.status, text, response_headers


def _parse_retry_after_ms(raw_value: str | None) -> int | None:
    text = _ensure_str(raw_value)
    if not text:
        return None

    try:
        seconds = int(text)
        return max(0, seconds * 1000)
    except ValueError:
        pass

    try:
        parsed_dt = parsedate_to_datetime(text)
        if parsed_dt is None:
            return None
        if parsed_dt.tzinfo is None:
            parsed_dt = parsed_dt.replace(tzinfo=timezone.utc)
        seconds_left = (parsed_dt - datetime.now(timezone.utc)).total_seconds()
        return max(0, int(seconds_left * 1000))
    except (TypeError, ValueError, OverflowError):
        return None


def _compute_retry_delay_ms(
    *,
    attempt: int,
    retry_delay_ms: int,
    status: int | None = None,
    retry_after_ms: int | None = None,
) -> int:
    base_delay_ms = max(100, retry_delay_ms)
    exponential_ms = min(MAX_RETRY_DELAY_MS, base_delay_ms * (2**attempt))
    jitter_span = max(1, int(exponential_ms * RETRY_JITTER_RATIO))
    wait_ms = exponential_ms + random.randint(-jitter_span, jitter_span)
    wait_ms = max(100, wait_ms)

    if status == 429:
        wait_ms = max(wait_ms, 5000)
    elif status in {408, 425, 503}:
        wait_ms = max(wait_ms, 1200)

    if retry_after_ms is not None:
        wait_ms = max(wait_ms, min(MAX_RETRY_DELAY_MS, retry_after_ms))

    return min(MAX_RETRY_DELAY_MS, wait_ms)


def _request_with_retry(
    *,
    api_root: str,
    path_name: str,
    method: str = "GET",
    query: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
    expect: str = "json",
    timeout_ms: int,
    retries: int,
    retry_delay_ms: int,
    user_agent: str = "iDanmuDownloaderPy/1.0",
) -> Any:
    query = query or {}
    filtered_query = {k: v for k, v in query.items() if v not in (None, "")}
    query_string = f"?{url_parse.urlencode(filtered_query)}" if filtered_query else ""
    url = f"{api_root}{path_name}{query_string}"

    headers = {"User-Agent": user_agent}
    if expect == "json":
        headers["Accept"] = "application/json, text/plain, */*"
    payload: bytes | None = None
    if body is not None:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"

    timeout_sec = max(0.1, timeout_ms / 1000)

    for attempt in range(retries + 1):
        _wait_for_shared_retry_gate()
        try:
            status, text, response_headers = _request_once(
                url=url,
                method=method,
                headers=headers,
                payload=payload,
                timeout_sec=timeout_sec,
            )
            if status >= 400:
                http_error = HttpError(f"HTTP {status}", status, text, response_headers)
                if attempt >= retries or not _is_retryable_status(status):
                    if attempt >= retries and status in RETRY_AFTER_STATUSES:
                        final_wait_ms = _compute_retry_delay_ms(
                            attempt=attempt,
                            retry_delay_ms=retry_delay_ms,
                            status=status,
                        )
                        _extend_shared_retry_gate(max(FINAL_RATE_LIMIT_COOLDOWN_MS, final_wait_ms))
                    raise http_error

                retry_after_ms = None
                if status in RETRY_AFTER_STATUSES:
                    retry_after_ms = _parse_retry_after_ms(response_headers.get("retry-after"))
                wait_ms = _compute_retry_delay_ms(
                    attempt=attempt,
                    retry_delay_ms=retry_delay_ms,
                    status=status,
                    retry_after_ms=retry_after_ms,
                )
                _extend_shared_retry_gate(wait_ms)
                time.sleep(wait_ms / 1000)
                continue

            if expect == "text":
                return text
            if not text.strip():
                return {}
            decoded = json.loads(text)
            if isinstance(decoded, dict):
                body_status = _parse_maybe_int(decoded.get("errorCode"))
                if body_status in RETRY_AFTER_STATUSES and decoded.get("success") is not True:
                    if attempt >= retries:
                        final_wait_ms = _compute_retry_delay_ms(
                            attempt=attempt,
                            retry_delay_ms=retry_delay_ms,
                            status=body_status,
                        )
                        _extend_shared_retry_gate(max(FINAL_RATE_LIMIT_COOLDOWN_MS, final_wait_ms))
                        raise HttpError(f"HTTP {body_status}", body_status, text, response_headers)
                    retry_after_ms = _parse_retry_after_ms(response_headers.get("retry-after"))
                    wait_ms = _compute_retry_delay_ms(
                        attempt=attempt,
                        retry_delay_ms=retry_delay_ms,
                        status=body_status,
                        retry_after_ms=retry_after_ms,
                    )
                    _extend_shared_retry_gate(wait_ms)
                    time.sleep(wait_ms / 1000)
                    continue
            return decoded
        except HttpError:
            raise
        except json.JSONDecodeError as exc:
            if attempt >= retries:
                raise RuntimeError(f"Invalid JSON response: {exc}") from exc
            wait_ms = _compute_retry_delay_ms(attempt=attempt, retry_delay_ms=retry_delay_ms)
            _extend_shared_retry_gate(wait_ms)
            time.sleep(wait_ms / 1000)
        except url_error.URLError as exc:
            retryable_network_error = _is_retryable_network_error(exc)
            if attempt >= retries or not retryable_network_error:
                if retryable_network_error:
                    final_wait_ms = _compute_retry_delay_ms(attempt=attempt, retry_delay_ms=retry_delay_ms)
                    _extend_shared_retry_gate(max(FINAL_NETWORK_COOLDOWN_MS, final_wait_ms))
                raise RuntimeError(_network_error_message(exc)) from exc
            wait_ms = _compute_retry_delay_ms(attempt=attempt, retry_delay_ms=retry_delay_ms)
            _extend_shared_retry_gate(wait_ms)
            time.sleep(wait_ms / 1000)
        except Exception as exc:
            retryable_network_error = _is_retryable_network_error(exc)
            if attempt >= retries or not retryable_network_error:
                if retryable_network_error:
                    final_wait_ms = _compute_retry_delay_ms(attempt=attempt, retry_delay_ms=retry_delay_ms)
                    _extend_shared_retry_gate(max(FINAL_NETWORK_COOLDOWN_MS, final_wait_ms))
                raise RuntimeError(str(exc)) from exc
            wait_ms = _compute_retry_delay_ms(attempt=attempt, retry_delay_ms=retry_delay_ms)
            _extend_shared_retry_gate(wait_ms)
            time.sleep(wait_ms / 1000)

    raise RuntimeError("Request failed.")


def request_json_with_retry(
    *,
    api_root: str,
    path_name: str,
    method: str = "GET",
    query: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
    timeout_ms: int = 35000,
    retries: int = 2,
    retry_delay_ms: int = 1200,
    user_agent: str = "iDanmuDownloaderPy/1.0",
) -> dict[str, Any]:
    data = _request_with_retry(
        api_root=api_root,
        path_name=path_name,
        method=method,
        query=query,
        body=body,
        expect="json",
        timeout_ms=timeout_ms,
        retries=retries,
        retry_delay_ms=retry_delay_ms,
        user_agent=user_agent,
    )
    if isinstance(data, dict):
        return data
    raise RuntimeError("JSON response is not an object.")


def _resolve_comment_id_by_match(ctx: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "fileName": task["fileName"],
        "fileHash": "",
        "fileSize": 0,
        "videoDuration": 0,
        "matchMode": "fileNameOnly",
    }
    data = _request_with_retry(
        api_root=ctx["api_root"],
        path_name="/api/v2/match",
        method="POST",
        body=payload,
        expect="json",
        timeout_ms=ctx["timeout_ms"],
        retries=ctx["retries"],
        retry_delay_ms=ctx["retry_delay_ms"],
    )

    match = data.get("matches", [None])[0] if isinstance(data.get("matches"), list) else None
    if not data.get("success") or not data.get("isMatched") or not match or not match.get("episodeId"):
        raise RuntimeError(f"match not found: {task['fileName']}")
    return {
        "commentId": match["episodeId"],
        "animeTitle": match.get("animeTitle"),
        "episodeTitle": match.get("episodeTitle"),
    }


def _resolve_comment_id_by_search_episodes(ctx: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
    data = _request_with_retry(
        api_root=ctx["api_root"],
        path_name="/api/v2/search/episodes",
        method="GET",
        query={"anime": task["anime"], "episode": task["episode"] or None},
        expect="json",
        timeout_ms=ctx["timeout_ms"],
        retries=ctx["retries"],
        retry_delay_ms=ctx["retry_delay_ms"],
    )
    anime_item = data.get("animes", [None])[0] if isinstance(data.get("animes"), list) else None
    episode_item = anime_item.get("episodes", [None])[0] if isinstance(anime_item, dict) and isinstance(anime_item.get("episodes"), list) else None
    if not data.get("success") or not anime_item or not episode_item or not episode_item.get("episodeId"):
        episode_hint = f" {task['episode']}" if task["episode"] else ""
        raise RuntimeError(f"search/episodes not found: {task['anime']}{episode_hint}")
    return {
        "commentId": episode_item["episodeId"],
        "animeTitle": anime_item.get("animeTitle"),
        "episodeTitle": episode_item.get("episodeTitle"),
    }


def _fetch_danmu_by_comment_id(ctx: dict[str, Any], comment_id: int, fmt: str) -> Any:
    return _request_with_retry(
        api_root=ctx["api_root"],
        path_name=f"/api/v2/comment/{comment_id}",
        method="GET",
        query={"format": fmt},
        expect="text" if fmt == "xml" else "json",
        timeout_ms=ctx["timeout_ms"],
        retries=ctx["retries"],
        retry_delay_ms=ctx["retry_delay_ms"],
    )


def _fetch_danmu_by_url(ctx: dict[str, Any], url: str, fmt: str) -> Any:
    return _request_with_retry(
        api_root=ctx["api_root"],
        path_name="/api/v2/comment",
        method="GET",
        query={"url": url, "format": fmt},
        expect="text" if fmt == "xml" else "json",
        timeout_ms=ctx["timeout_ms"],
        retries=ctx["retries"],
        retry_delay_ms=ctx["retry_delay_ms"],
    )


def _derive_base_name(task: dict[str, Any], mode: str, resolved: dict[str, Any]) -> str:
    if task["name"]:
        return task["name"]
    if resolved.get("animeTitle") or resolved.get("episodeTitle"):
        return f"{resolved.get('animeTitle') or 'unknown'}-{resolved.get('episodeTitle') or 'episode'}"
    if mode == "url" and task["url"]:
        return task["url"]
    if mode == "commentId" and task["commentId"]:
        return f"comment-{task['commentId']}"
    if mode == "fileName" and task["fileName"]:
        return task["fileName"]
    if mode == "anime" and task["anime"]:
        return f"{task['anime']}-{task['episode'] or 'all'}"
    return f"task-{task['index']}"


def _render_output_stem(task: dict[str, Any], mode: str, resolved: dict[str, Any], ext: str, naming_rule: str) -> str:
    base_name = _derive_base_name(task, mode, resolved)
    rule = _ensure_str(naming_rule) or DEFAULTS["naming_rule"]
    values: dict[str, Any] = {
        "index": task["index"],
        "base": base_name,
        "name": task.get("name") or "",
        "mode": mode,
        "ext": ext,
        "url": task.get("url") or "",
        "anime": task.get("anime") or "",
        "episode": task.get("episode") or "",
        "commentId": resolved.get("commentId") or task.get("commentId") or "",
        "animeTitle": resolved.get("animeTitle") or "",
        "episodeTitle": resolved.get("episodeTitle") or "",
    }
    try:
        rendered = rule.format_map(values)
    except KeyError as exc:
        raise RuntimeError(f"Invalid naming rule field: {exc.args[0]}") from exc
    except ValueError as exc:
        raise RuntimeError(f"Invalid naming rule: {exc}") from exc

    stem = _ensure_str(rendered) or base_name
    stem = Path(stem).name
    lowered = stem.lower()
    if lowered.endswith(".xml") or lowered.endswith(".json"):
        stem = stem.rsplit(".", 1)[0]
    return _sanitize_windows_filename(stem or base_name)


def _process_task(ctx: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
    mode = _task_mode(task)
    if not mode:
        raise RuntimeError("Task missing supported fields: url/commentId/fileName/anime")

    fmt = task["format"] or ctx["default_format"]
    resolved: dict[str, Any] = {}

    if mode == "url":
        result = _fetch_danmu_by_url(ctx, task["url"], fmt)
    elif mode == "commentId":
        resolved["commentId"] = task["commentId"]
        result = _fetch_danmu_by_comment_id(ctx, task["commentId"], fmt)
    elif mode == "fileName":
        resolved.update(_resolve_comment_id_by_match(ctx, task))
        result = _fetch_danmu_by_comment_id(ctx, resolved["commentId"], fmt)
    elif mode == "anime":
        resolved.update(_resolve_comment_id_by_search_episodes(ctx, task))
        result = _fetch_danmu_by_comment_id(ctx, resolved["commentId"], fmt)
    else:
        raise RuntimeError(f"Unsupported task mode: {mode}")

    ext = "xml" if fmt == "xml" else "json"
    output_stem = _render_output_stem(task, mode, resolved, ext, ctx["naming_rule"])
    output_name = f"{output_stem}.{ext}"
    output_path = Path(ctx["output_dir"]) / output_name
    content = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, indent=2)
    output_path.write_text(content, encoding="utf-8")

    count = None if isinstance(result, str) else result.get("count")
    return {
        "index": task["index"],
        "status": "success",
        "mode": mode,
        "output": str(output_path),
        "count": count,
        "format": fmt,
        "commentId": resolved.get("commentId") or task["commentId"] or None,
        "animeTitle": resolved.get("animeTitle"),
        "episodeTitle": resolved.get("episodeTitle"),
    }


def _normalize_options(raw: dict[str, Any]) -> dict[str, Any]:
    opts = dict(DEFAULTS)
    opts.update(raw or {})

    opts["base_url"] = _ensure_str(opts.get("base_url"))
    opts["token"] = _ensure_str(opts.get("token"))
    opts["input"] = _ensure_str(opts.get("input"))
    opts["output"] = _ensure_str(opts.get("output")) or DEFAULTS["output"]
    opts["format"] = _ensure_str(opts.get("format")).lower() or DEFAULTS["format"]
    opts["naming_rule"] = _ensure_str(opts.get("naming_rule")) or DEFAULTS["naming_rule"]
    opts["concurrency"] = int(opts.get("concurrency", DEFAULTS["concurrency"]))
    opts["retries"] = int(opts.get("retries", DEFAULTS["retries"]))
    opts["retry_delay_ms"] = int(opts.get("retry_delay_ms", DEFAULTS["retry_delay_ms"]))
    opts["throttle_ms"] = int(opts.get("throttle_ms", DEFAULTS["throttle_ms"]))
    opts["timeout_ms"] = int(opts.get("timeout_ms", DEFAULTS["timeout_ms"]))
    opts["local_api"] = _ensure_str(opts.get("local_api")).lower() or DEFAULTS["local_api"]

    if opts["format"] not in {"json", "xml"}:
        raise RuntimeError("--format must be json or xml")
    if opts["local_api"] not in {"auto", "on", "off"}:
        raise RuntimeError("--local-api must be auto, on or off")
    for key in ("concurrency", "retries", "retry_delay_ms", "throttle_ms", "timeout_ms"):
        if opts[key] < 0:
            raise RuntimeError(f"{key} must be >= 0")
    if opts["concurrency"] < 1:
        raise RuntimeError("concurrency must be >= 1")
    return opts


def _ensure_local_api_if_needed(opts: dict[str, Any], emit: Callable[[str], None]) -> local_danmu_api.LocalApiHandle | None:
    mode = opts.get("local_api", "auto")
    is_local_target = local_danmu_api.is_local_base_url(opts["base_url"])

    if mode == "off":
        return None
    if mode == "on" and not is_local_target:
        raise RuntimeError("--local-api=on requires --base-url to point to localhost/127.0.0.1")
    if mode == "auto" and not is_local_target:
        return None

    return local_danmu_api.ensure_local_api(
        base_url=opts["base_url"],
        token=opts["token"],
        log_fn=emit,
    )


def run_download(
    options: dict[str, Any],
    *,
    tasks_override: list[dict[str, Any]] | None = None,
    log_fn: Callable[[str], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> int:
    opts = _normalize_options(options)
    emit = log_fn or print
    is_cancelled = is_cancelled or (lambda: False)
    local_api_handle: local_danmu_api.LocalApiHandle | None = None

    try:
        output_dir = Path(opts["output"]).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        raw_tasks = tasks_override if tasks_override is not None else load_tasks(opts["input"])
        tasks = [_normalize_task(task, index) for index, task in enumerate(raw_tasks)]
        tasks = [task for task in tasks if not task["disabled"]]
        if not tasks:
            emit("No tasks to run.\n")
            return 0

        local_api_handle = _ensure_local_api_if_needed(opts, emit)
        api_root = _normalize_api_root(opts["base_url"], opts["token"])
        emit(f"API: {api_root}\n")
        if opts["input"]:
            emit(f"Input: {Path(opts['input']).resolve()}\n")
        emit(f"Output: {output_dir}\n")
        emit(f"Naming rule: {opts['naming_rule']}\n")
        emit(f"Total tasks: {len(tasks)}\n")
        emit(f"Concurrency: {opts['concurrency']}\n")

        ctx = {
            "api_root": api_root,
            "output_dir": output_dir,
            "default_format": opts["format"],
            "naming_rule": opts["naming_rule"],
            "retries": opts["retries"],
            "retry_delay_ms": opts["retry_delay_ms"],
            "timeout_ms": opts["timeout_ms"],
        }

        report: dict[str, Any] = {
            "startedAt": _iso_now(),
            "apiRoot": api_root,
            "inputPath": str(Path(opts["input"]).resolve()) if opts["input"] else None,
            "outputDir": str(output_dir),
            "namingRule": opts["naming_rule"],
            "total": len(tasks),
            "success": 0,
            "failed": 0,
            "items": [],
        }

        pointer_lock = threading.Lock()
        schedule_lock = threading.Lock()
        report_lock = threading.Lock()

        next_pointer = 0
        next_schedule_time = time.monotonic()
        throttle_sec = opts["throttle_ms"] / 1000

        def schedule_start() -> None:
            nonlocal next_schedule_time
            if throttle_sec <= 0:
                return
            with schedule_lock:
                now = time.monotonic()
                wait = max(0.0, next_schedule_time - now)
                next_schedule_time = max(now, next_schedule_time) + throttle_sec
            if wait > 0:
                time.sleep(wait)

        def next_task() -> dict[str, Any] | None:
            nonlocal next_pointer
            with pointer_lock:
                if next_pointer >= len(tasks):
                    return None
                task = tasks[next_pointer]
                next_pointer += 1
                return task

        def run_task(task: dict[str, Any]) -> None:
            if is_cancelled():
                return
            schedule_start()
            if is_cancelled():
                return

            emit(f"\n[{task['index']}/{len(tasks)}] Start... ")
            try:
                item = _process_task(ctx, task)
                with report_lock:
                    report["items"].append(item)
                    report["success"] += 1
                emit(f"OK -> {Path(item['output']).name}\n")
            except Exception as exc:
                err_msg = str(exc)
                if isinstance(exc, HttpError):
                    err_msg = f"{exc}; body={str(exc.body)[:200]}"
                with report_lock:
                    report["items"].append({"index": task["index"], "status": "failed", "error": err_msg})
                    report["failed"] += 1
                emit(f"FAILED -> {err_msg}\n")

        def worker() -> None:
            while True:
                if is_cancelled():
                    return
                task = next_task()
                if task is None:
                    return
                run_task(task)

        threads = [threading.Thread(target=worker, daemon=True) for _ in range(opts["concurrency"])]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        report["items"].sort(key=lambda item: item.get("index", 0))
        report["cancelled"] = bool(is_cancelled())
        report["endedAt"] = _iso_now()

        report_path = output_dir / "download-report.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

        emit("\nDone.\n")
        emit(f"Success: {report['success']}\n")
        emit(f"Failed: {report['failed']}\n")
        emit(f"Report: {report_path}\n")

        if report["cancelled"]:
            return 130
        if report["failed"] > 0:
            return 2
        return 0
    finally:
        if local_api_handle is not None and local_api_handle.started_by_tool:
            local_api_handle.stop()


def parse_cli_args(argv: list[str] | None = None) -> dict[str, Any]:
    parser = argparse.ArgumentParser(description="iDanmu_Speed batch downloader (Python)")
    parser.add_argument("--input", required=True, help="Path to tasks file (.json/.jsonl/.csv)")
    parser.add_argument("--base-url", default=DEFAULTS["base_url"], help="API base URL")
    parser.add_argument("--token", default=DEFAULTS["token"], help="Optional token")
    parser.add_argument("--output", default=DEFAULTS["output"], help="Output directory")
    parser.add_argument("--format", default=DEFAULTS["format"], choices=["json", "xml"], help="Output format")
    parser.add_argument("--naming-rule", default=DEFAULTS["naming_rule"], help="Output naming rule template")
    parser.add_argument("--concurrency", type=int, default=DEFAULTS["concurrency"], help="Concurrency")
    parser.add_argument("--retries", type=int, default=DEFAULTS["retries"], help="Retry count")
    parser.add_argument("--retry-delay-ms", type=int, default=DEFAULTS["retry_delay_ms"], help="Retry base delay in ms")
    parser.add_argument("--throttle-ms", type=int, default=DEFAULTS["throttle_ms"], help="Task start throttle in ms")
    parser.add_argument("--timeout-ms", type=int, default=DEFAULTS["timeout_ms"], help="Request timeout in ms")
    parser.add_argument(
        "--local-api",
        default=DEFAULTS["local_api"],
        choices=["auto", "on", "off"],
        help="Auto-start local danmu_api-main when using localhost (default: auto)",
    )
    args = parser.parse_args(argv)
    return {
        "input": args.input,
        "base_url": args.base_url,
        "token": args.token,
        "output": args.output,
        "format": args.format,
        "naming_rule": args.naming_rule,
        "concurrency": args.concurrency,
        "retries": args.retries,
        "retry_delay_ms": args.retry_delay_ms,
        "throttle_ms": args.throttle_ms,
        "timeout_ms": args.timeout_ms,
        "local_api": args.local_api,
    }


def main(argv: list[str] | None = None) -> int:
    try:
        options = parse_cli_args(argv)
        return run_download(options)
    except Exception as exc:
        print(f"Run failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
