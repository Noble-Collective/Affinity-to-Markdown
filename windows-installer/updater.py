"""
updater.py — Over-the-air update system for pipeline files.

Checks a version manifest on GitHub and downloads updated files
(run.py, template configs) without requiring a full reinstall.
"""

import json
import os
import threading
from pathlib import Path
from typing import Callable, Optional
from urllib.request import urlopen, Request
from urllib.error import URLError

GITHUB_OWNER = "Noble-Collective"
GITHUB_REPO = "Affinity-to-Markdown"
GITHUB_BRANCH = "main"

_RAW_BASE = f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/{GITHUB_BRANCH}"
_MANIFEST_URL = f"{_RAW_BASE}/update-manifest.json"

UPDATES_DIR = Path.home() / ".affinity-converter" / "updates"
_STATE_FILE = Path.home() / ".affinity-converter" / "installed-version.json"
_TIMEOUT = 10


def _read_local_state() -> dict:
    if _STATE_FILE.exists():
        try:
            return json.loads(_STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"version": 0}

def _write_local_state(state: dict):
    _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")

def get_installed_version() -> int:
    return _read_local_state().get("version", 0)


class UpdateInfo:
    def __init__(self, available, remote_version=0, local_version=0, notes="", files=None, error=None):
        self.available = available
        self.remote_version = remote_version
        self.local_version = local_version
        self.notes = notes
        self.files = files or []
        self.error = error


def check_for_updates() -> UpdateInfo:
    local_state = _read_local_state()
    local_version = local_state.get("version", 0)
    try:
        req = Request(_MANIFEST_URL, headers={"User-Agent": "Affinity-Converter/0.1"})
        with urlopen(req, timeout=_TIMEOUT) as resp:
            manifest = json.loads(resp.read().decode("utf-8"))
    except (URLError, OSError, json.JSONDecodeError) as e:
        return UpdateInfo(available=False, local_version=local_version, error=str(e))
    remote_version = manifest.get("version", 0)
    notes = manifest.get("notes", "")
    files = manifest.get("files", [])
    if remote_version > local_version:
        return UpdateInfo(available=True, remote_version=remote_version, local_version=local_version, notes=notes, files=files)
    return UpdateInfo(available=False, remote_version=remote_version, local_version=local_version)


def check_for_updates_async(callback):
    def _worker():
        callback(check_for_updates())
    threading.Thread(target=_worker, daemon=True).start()


def download_updates(files, version, notes="", progress_callback=None):
    UPDATES_DIR.mkdir(parents=True, exist_ok=True)
    total = len(files)
    downloaded = 0
    errors = []
    for i, rel_path in enumerate(files):
        url = f"{_RAW_BASE}/{rel_path}"
        local_path = UPDATES_DIR / rel_path
        if progress_callback:
            progress_callback(i, total, rel_path.split("/")[-1])
        try:
            req = Request(url, headers={"User-Agent": "Affinity-Converter/0.1"})
            with urlopen(req, timeout=30) as resp:
                content = resp.read()
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_bytes(content)
            downloaded += 1
        except (URLError, OSError) as e:
            errors.append(f"{rel_path}: {e}")
    if progress_callback:
        progress_callback(total, total, "done")
    _write_local_state({"version": version, "notes": notes, "files": files, "downloaded": downloaded})
    if errors:
        return False, f"Downloaded {downloaded}/{total} files. Errors:\n" + "\n".join(errors)
    return True, f"Updated to version {version} ({downloaded} files)"


def has_local_updates() -> bool:
    return _STATE_FILE.exists() and get_installed_version() > 0

def get_update_notes() -> str:
    return _read_local_state().get("notes", "")

def clear_updates():
    import shutil
    if UPDATES_DIR.exists(): shutil.rmtree(UPDATES_DIR)
    if _STATE_FILE.exists(): _STATE_FILE.unlink()
