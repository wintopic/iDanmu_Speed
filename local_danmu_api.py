#!/usr/bin/env python3
"""Helpers for bootstrapping the local danmu_api-main service."""

from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib import error as url_error
from urllib import parse as url_parse
from urllib import request as url_request

DEFAULT_LOCAL_BASE_URL = "http://127.0.0.1:9321"
DEFAULT_LOCAL_TOKEN = "87654321"
_DEFAULT_SOURCE_ORDER = "360,vod,renren,hanjutv"
_RICH_SOURCE_ORDER = "360,vod,tencent,youku,iqiyi,imgo,bilibili,migu,renren,hanjutv,sohu,leshi,xigua,maiduidui"
_DEFAULT_RATE_LIMIT = "3"
_LOCAL_RATE_LIMIT = "0"
_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "0.0.0.0"}


def _emit(log_fn: Callable[[str], None] | None, text: str) -> None:
    if log_fn is None:
        return
    try:
        log_fn(text)
    except Exception:
        pass


def _creationflags_no_window(*, new_process_group: bool = False) -> int:
    if os.name != "nt":
        return 0
    flags = 0
    flags |= int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if new_process_group:
        flags |= int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    return flags


def _looks_like_local_host(raw_url: str) -> bool:
    candidate = raw_url.strip()
    if not candidate:
        return False
    if candidate.startswith("[::1]"):
        return True
    host = candidate.split("/", 1)[0]
    host = host.split(":", 1)[0].strip().lower()
    if host in _LOCAL_HOSTS:
        return True
    if re.match(r"^127(?:\.\d{1,3}){3}$", host):
        return True
    return False


def with_default_scheme(raw_url: str) -> str:
    text = raw_url.strip()
    if not text:
        return text
    if re.match(r"^https?://", text, flags=re.I):
        return text
    if _looks_like_local_host(text):
        return "http://" + text
    return "https://" + text


def is_local_base_url(base_url: str) -> bool:
    parsed = url_parse.urlsplit(with_default_scheme(base_url))
    host = (parsed.hostname or "").lower()
    if host in _LOCAL_HOSTS:
        return True
    if re.match(r"^127(?:\.\d{1,3}){3}$", host):
        return True
    return False


def normalize_api_root(base_url: str, token: str = "") -> str:
    parsed = url_parse.urlsplit(with_default_scheme(base_url))
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError(f"Invalid base URL: {base_url}")

    pathname = parsed.path.rstrip("/")
    clean_token = (token or "").strip()
    if clean_token:
        pathname = f"{pathname}/{url_parse.quote(clean_token)}"
    if not pathname:
        pathname = "/"

    rebuilt = parsed._replace(path=pathname, query="", fragment="")
    return url_parse.urlunsplit(rebuilt).rstrip("/")


def _parse_host_port(base_url: str) -> tuple[str, int]:
    parsed = url_parse.urlsplit(with_default_scheme(base_url))
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port
    if port is None:
        port = 443 if parsed.scheme == "https" else 80
    return host, port


def _is_tcp_open(host: str, port: int, timeout_sec: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout_sec):
            return True
    except OSError:
        return False


def _is_api_healthy(api_root: str, timeout_sec: float = 1.2) -> bool:
    probe_urls = [api_root + "/api/config", api_root + "/"]
    headers = {"User-Agent": "iDanmuLocalApi/1.0", "Accept": "application/json, text/plain, */*"}

    for url in probe_urls:
        req = url_request.Request(url=url, headers=headers)
        try:
            with url_request.urlopen(req, timeout=timeout_sec) as resp:  # nosec B310
                status = int(resp.status)
                body = resp.read().decode("utf-8", errors="replace")
                if _looks_like_danmu_response(status, body):
                    return True
        except url_error.HTTPError as exc:
            status = int(exc.code)
            try:
                body = exc.read().decode("utf-8", errors="replace")
            except Exception:
                body = ""
            if _looks_like_danmu_response(status, body):
                return True
        except Exception:
            continue
    return False


def _looks_like_danmu_response(status: int, body: str) -> bool:
    lowered = (body or "").strip().lower()
    if not lowered:
        return False

    if '"errorcode"' in lowered and '"success"' in lowered:
        return True
    if '"sourceorderarr"' in lowered or '"envvarconfig"' in lowered:
        return True
    if "logvar" in lowered and "<html" in lowered:
        return True
    if status in {401, 403} and "unauthorized" in lowered and '"errorcode"' in lowered:
        return True
    return False


def _runtime_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _materialize_embedded_repo(log_fn: Callable[[str], None] | None = None) -> Path | None:
    if not getattr(sys, "frozen", False):
        return None

    runtime_dir = _runtime_base_dir()
    persistent_repo = runtime_dir / "danmu_api-main"
    if persistent_repo.is_dir():
        return persistent_repo

    meipass = getattr(sys, "_MEIPASS", None)
    if not meipass:
        return None

    embedded_repo = Path(str(meipass)) / "danmu_api-main"
    if not embedded_repo.is_dir():
        return None

    try:
        _emit(log_fn, f"[local-api] Extracting embedded danmu_api-main to: {persistent_repo}\n")
        shutil.copytree(embedded_repo, persistent_repo, dirs_exist_ok=True)
        return persistent_repo
    except Exception as exc:
        _emit(log_fn, f"[local-api] Warning: failed to persist embedded danmu_api-main ({exc}).\n")
        return embedded_repo


def resolve_api_repo_dir(log_fn: Callable[[str], None] | None = None) -> Path:
    env_dir = os.environ.get("DANMUPRO_DANMU_API_DIR", "").strip()
    if env_dir:
        candidate = Path(env_dir).expanduser().resolve()
        if candidate.is_dir():
            return candidate

    materialized = _materialize_embedded_repo(log_fn=log_fn)
    if materialized and materialized.is_dir():
        return materialized

    roots: list[Path] = []
    seen: set[str] = set()

    def add_root(path_value: Path | None) -> None:
        if path_value is None:
            return
        try:
            resolved = path_value.resolve()
        except Exception:
            return
        key = str(resolved).lower()
        if key in seen:
            return
        seen.add(key)
        roots.append(resolved)

    base = _runtime_base_dir()
    add_root(base)
    add_root(base / "_internal")
    add_root(base.parent)
    add_root(Path.cwd())
    add_root(Path(sys.argv[0]).resolve().parent if sys.argv and sys.argv[0] else None)
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        add_root(Path(str(meipass)))

    for root in roots:
        candidate = root / "danmu_api-main"
        if candidate.is_dir():
            return candidate
    raise RuntimeError("Cannot find danmu_api-main directory.")


def _stream_command_output(
    process: subprocess.Popen[str],
    *,
    prefix: str,
    log_fn: Callable[[str], None] | None = None,
) -> None:
    if process.stdout is None:
        return
    for raw in iter(process.stdout.readline, ""):
        line = raw.rstrip("\r\n")
        if line:
            _emit(log_fn, f"{prefix}{line}\n")
    process.stdout.close()


def _install_node_dependencies(api_repo_dir: Path, log_fn: Callable[[str], None] | None = None) -> None:
    if (api_repo_dir / "node_modules").exists():
        return
    npm_bin = shutil.which("npm")
    if not npm_bin:
        raise RuntimeError("npm not found. Install Node.js and npm first.")

    _emit(log_fn, "[local-api] Installing npm dependencies...\n")
    proc = subprocess.Popen(
        [npm_bin, "install", "--no-audit", "--no-fund"],
        cwd=str(api_repo_dir),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        creationflags=_creationflags_no_window(),
    )
    _stream_command_output(proc, prefix="[local-api] ", log_fn=log_fn)
    code = proc.wait()
    if code != 0:
        raise RuntimeError(f"npm install failed with exit code {code}.")
    _emit(log_fn, "[local-api] Dependencies are ready.\n")


def _prepare_env_for_local_mode(api_repo_dir: Path, log_fn: Callable[[str], None] | None = None) -> None:
    config_dir = api_repo_dir / "config"
    env_path = config_dir / ".env"
    example_path = config_dir / ".env.example"

    if not env_path.exists() and example_path.exists():
        try:
            env_path.write_bytes(example_path.read_bytes())
            _emit(log_fn, "[local-api] Created config/.env from .env.example.\n")
        except Exception as exc:
            _emit(log_fn, f"[local-api] Warning: failed to create config/.env ({exc}).\n")
            return

    if not env_path.exists():
        return

    try:
        original = env_path.read_text(encoding="utf-8-sig")
    except Exception:
        try:
            original = env_path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            _emit(log_fn, f"[local-api] Warning: failed to read config/.env ({exc}).\n")
            return

    lines = original.splitlines()
    changed = False
    key_map = {
        "SOURCE_ORDER": (_DEFAULT_SOURCE_ORDER, _RICH_SOURCE_ORDER),
        "RATE_LIMIT_MAX_REQUESTS": (_DEFAULT_RATE_LIMIT, _LOCAL_RATE_LIMIT),
    }
    found: dict[str, bool] = {key: False for key in key_map}

    for index, line in enumerate(lines):
        for key, (default_value, local_value) in key_map.items():
            match = re.match(rf"^\s*{re.escape(key)}\s*=\s*(.*)\s*$", line)
            if not match:
                continue
            found[key] = True
            current = match.group(1).strip()
            if current == default_value:
                lines[index] = f"{key}={local_value}"
                changed = True
            break

    for key, (_default_value, local_value) in key_map.items():
        if found[key]:
            continue
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(f"{key}={local_value}")
        changed = True

    if not changed:
        return

    new_text = "\n".join(lines)
    if original.endswith("\n"):
        new_text += "\n"
    try:
        env_path.write_text(new_text, encoding="utf-8")
        _emit(log_fn, "[local-api] Applied local tuning: broader SOURCE_ORDER + disabled local rate limit.\n")
    except Exception as exc:
        _emit(log_fn, f"[local-api] Warning: failed to update local config tuning ({exc}).\n")


@dataclass
class LocalApiHandle:
    process: subprocess.Popen[str] | None
    api_root: str
    started_by_tool: bool

    def is_alive(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def stop(self, timeout_sec: float = 6.0) -> None:
        if self.process is None:
            return
        if self.process.poll() is not None:
            return
        try:
            self.process.terminate()
            self.process.wait(timeout=max(0.2, timeout_sec))
        except subprocess.TimeoutExpired:
            self.process.kill()
            try:
                self.process.wait(timeout=2.0)
            except Exception:
                pass
        except Exception:
            pass


def ensure_local_api(
    *,
    base_url: str = DEFAULT_LOCAL_BASE_URL,
    token: str = DEFAULT_LOCAL_TOKEN,
    log_fn: Callable[[str], None] | None = None,
    startup_timeout_sec: float = 45.0,
    auto_install_deps: bool = True,
) -> LocalApiHandle | None:
    if not is_local_base_url(base_url):
        return None

    host, port = _parse_host_port(base_url)
    api_root = normalize_api_root(base_url, token)
    if _is_api_healthy(api_root):
        return LocalApiHandle(process=None, api_root=api_root, started_by_tool=False)

    if _is_tcp_open(host, port) and not _is_api_healthy(api_root):
        raise RuntimeError(f"Port {port} is already in use by a non-danmu API service.")

    api_repo_dir = resolve_api_repo_dir(log_fn=log_fn)
    _prepare_env_for_local_mode(api_repo_dir, log_fn=log_fn)
    if auto_install_deps:
        _install_node_dependencies(api_repo_dir, log_fn=log_fn)
    elif not (api_repo_dir / "node_modules").exists():
        raise RuntimeError("Missing danmu_api-main/node_modules. Run npm install first.")

    node_bin = shutil.which("node")
    if not node_bin:
        raise RuntimeError("node not found. Install Node.js first.")

    cmd = [node_bin, "danmu_api/server.js"]
    creationflags = _creationflags_no_window(new_process_group=True)
    child_env = os.environ.copy()
    child_env["DANMU_API_PORT"] = str(port)
    child_env["RATE_LIMIT_MAX_REQUESTS"] = _LOCAL_RATE_LIMIT
    child_env.setdefault("SOURCE_ORDER", _RICH_SOURCE_ORDER)

    _emit(log_fn, "[local-api] Starting local danmu_api service...\n")
    process = subprocess.Popen(
        cmd,
        cwd=str(api_repo_dir),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        creationflags=creationflags,
        env=child_env,
    )

    pump_thread = threading.Thread(
        target=_stream_command_output,
        kwargs={"process": process, "prefix": "[local-api] ", "log_fn": log_fn},
        daemon=True,
    )
    pump_thread.start()

    handle = LocalApiHandle(process=process, api_root=api_root, started_by_tool=True)
    deadline = time.monotonic() + max(3.0, startup_timeout_sec)
    while time.monotonic() < deadline:
        if process.poll() is not None:
            code = process.returncode
            raise RuntimeError(f"local danmu_api exited unexpectedly (code={code}).")
        if _is_api_healthy(api_root):
            _emit(log_fn, f"[local-api] Local API is ready: {api_root}\n")
            return handle
        time.sleep(0.25)

    handle.stop(timeout_sec=2.0)
    raise RuntimeError(f"Timed out waiting for local API startup: {api_root}")
