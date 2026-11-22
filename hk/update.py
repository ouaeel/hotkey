"""Optional, non-blocking GitHub release checker.

Standard library only.  The caller decides when to run it; this module never
starts a thread or touches the GUI.  Private repositories need a token, which
can be supplied directly or named by an environment variable.
"""
from __future__ import annotations

import http.client
import json
import os
import re
import urllib.parse
from dataclasses import dataclass

from . import __version__

DEFAULT_URL = "https://api.github.com/repos/ouaeel/hotkey/releases/latest"
DEFAULT_TOKEN_ENV = "GITHUB_TOKEN"


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    url: str
    notes: str = ""


def _parts(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", str(text))[:3])


def is_newer(candidate: str, current: str = __version__) -> bool:
    """Compare dotted version numbers without importing packaging."""
    new, old = _parts(candidate), _parts(current)
    if not new or not old:
        return False
    size = max(len(new), len(old))
    return new + (0,) * (size - len(new)) > old + (0,) * (size - len(old))


def releases_page(url: str = DEFAULT_URL) -> str:
    """Human-readable releases page for a configured API endpoint.

    Update checks use the GitHub *API* URL, but opening that URL in a browser
    shows raw JSON.  Convert it to the normal releases page instead.
    """
    parsed = urllib.parse.urlsplit(url)
    host = (parsed.hostname or "").lower()
    parts = [part for part in parsed.path.split("/") if part]
    owner = repo = ""
    if "repos" in parts:
        index = parts.index("repos")
        if len(parts) > index + 2:
            owner, repo = parts[index + 1], parts[index + 2]
    elif host.endswith("github.com") and len(parts) >= 2:
        owner, repo = parts[0], parts[1]
    if not owner or not repo:
        return "https://github.com/ouaeel/hotkey/releases"
    if host == "api.github.com":
        host = "github.com"
    return f"https://{host}/{owner}/{repo}/releases"


def token_from(settings: dict | None = None) -> str:
    """Read an optional token from settings or from the configured env var."""
    settings = settings or {}
    token = str(settings.get("update_token") or "").strip()
    if token:
        return token
    env_name = str(settings.get("update_token_env") or DEFAULT_TOKEN_ENV).strip()
    return str(os.environ.get(env_name) or "").strip() if env_name else ""


def check(url: str = DEFAULT_URL, token: str = "", timeout: float = 8.0) -> UpdateInfo | None:
    """Return release info only when a newer stable release is published.

    Network errors and private-repo 404s are raised; the caller should log and
    ignore them.  A quiet skip is intentional: update checking must never
    interfere with the hotkeys themselves.
    """
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError(f"unsupported update URL: {url}")
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"Hotkey/{__version__}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    connection = (http.client.HTTPSConnection(parsed.hostname, parsed.port or 443,
                                              timeout=timeout)
                  if parsed.scheme == "https" else
                  http.client.HTTPConnection(parsed.hostname,
                                             parsed.port or 80, timeout=timeout))
    try:
        connection.request("GET", path, headers=headers)
        response = connection.getresponse()
        if response.status != 200:
            raise OSError(f"update check HTTP {response.status}")
        data = json.load(response)
    finally:
        connection.close()
    if not isinstance(data, dict) or data.get("prerelease"):
        return None
    tag = str(data.get("tag_name") or "").strip()
    if not tag or not is_newer(tag):
        return None
    assets = data.get("assets") or []
    download = ""
    for asset in assets:
        if isinstance(asset, dict) and str(asset.get("name") or "").lower().endswith(".zip"):
            download = str(asset.get("browser_download_url") or "")
            break
    page = str(data.get("html_url") or url)
    notes = str(data.get("body") or "").strip()[:500]
    return UpdateInfo(version=tag.lstrip("vV"), url=download or page, notes=notes)
