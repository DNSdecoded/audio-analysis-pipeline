"""Secure, file-system backed session storage.

Original uploads are written once and never modified.  Analysis output lives in
a separate directory and is written atomically.  All identifiers are generated
server-side UUIDs and every path is resolved through those identifiers, which
prevents path traversal through user supplied names.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, Iterator

from .config import Settings, settings as default_settings

ID_RE = re.compile(r"^(ses|fil)_[0-9a-f]{32}$")


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def valid_id(value: str, prefix: str) -> bool:
    return bool(ID_RE.fullmatch(value or "")) and value.startswith(prefix + "_")


def safe_display_name(name: str) -> str:
    """Return a display-only filename without any path components."""
    name = (name or "audio").replace("\\", "/").split("/")[-1]
    name = "".join(ch for ch in name if ch.isprintable() and ch not in "\r\n\t")
    name = name.strip().strip(".") or "audio"
    return name[:180]


class StorageError(Exception):
    pass


class SessionStore:
    def __init__(self, config: Settings = default_settings):
        self.config = config
        self._lock = threading.RLock()
        self.config.ensure_dirs()

    # ------------------------------------------------------------------ paths
    def session_dir(self, session_id: str) -> Path:
        if not valid_id(session_id, "ses"):
            raise StorageError("Invalid session identifier")
        return self.config.sessions_dir / session_id

    def file_dir(self, session_id: str, file_id: str) -> Path:
        if not valid_id(file_id, "fil"):
            raise StorageError("Invalid file identifier")
        return self.session_dir(session_id) / "files" / file_id

    def original_path(self, session_id: str, file_id: str, ext: str) -> Path:
        return self.file_dir(session_id, file_id) / f"original{ext}"

    def analysis_path(self, session_id: str, file_id: str) -> Path:
        if not valid_id(file_id, "fil"):
            raise StorageError("Invalid file identifier")
        return self.session_dir(session_id) / "analysis" / f"{file_id}.json"

    # --------------------------------------------------------------- sessions
    def _session_file(self, session_id: str) -> Path:
        return self.session_dir(session_id) / "session.json"

    def _atomic_write_json(self, path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, path)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)

    def create_session(self, name: str | None = None) -> dict[str, Any]:
        session_id = new_id("ses")
        now = utcnow()
        data = {
            "id": session_id,
            "name": safe_display_name(name or "Analysis session")[:80],
            "created_at": now,
            "updated_at": now,
            "files": {},
            "settings": {
                "target_lufs": self.config.default_target_lufs,
                "true_peak_limit": self.config.default_true_peak_limit,
                "fft_size": self.config.default_fft_size,
                "hop_length": self.config.default_hop_length,
            },
        }
        with self._lock:
            self.session_dir(session_id).mkdir(parents=True, exist_ok=False)
            (self.session_dir(session_id) / "files").mkdir(exist_ok=True)
            (self.session_dir(session_id) / "analysis").mkdir(exist_ok=True)
            self._atomic_write_json(self._session_file(session_id), data)
        return data

    def get_session(self, session_id: str) -> dict[str, Any]:
        path = self._session_file(session_id)
        with self._lock:
            if not path.exists():
                raise StorageError("Session not found or expired")
            with path.open("r", encoding="utf-8") as handle:
                return json.load(handle)

    def session_exists(self, session_id: str) -> bool:
        try:
            return self._session_file(session_id).exists()
        except StorageError:
            return False

    def update_session(self, session_id: str, **fields: Any) -> dict[str, Any]:
        with self._lock:
            data = self.get_session(session_id)
            data.update(fields)
            data["updated_at"] = utcnow()
            self._atomic_write_json(self._session_file(session_id), data)
            return data

    def delete_session(self, session_id: str) -> bool:
        directory = self.session_dir(session_id)
        with self._lock:
            if not directory.exists():
                return False
            shutil.rmtree(directory, ignore_errors=True)
            return True

    def list_sessions(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        if not self.config.sessions_dir.exists():
            return result
        for entry in self.config.sessions_dir.iterdir():
            if not entry.is_dir() or not valid_id(entry.name, "ses"):
                continue
            try:
                with (entry / "session.json").open("r", encoding="utf-8") as handle:
                    result.append(json.load(handle))
            except (OSError, json.JSONDecodeError):
                continue
        result.sort(key=lambda item: item.get("created_at", ""), reverse=True)
        return result

    # ------------------------------------------------------------------ files
    def add_file(
        self,
        session_id: str,
        display_name: str,
        ext: str,
        stream: BinaryIO,
        max_bytes: int,
    ) -> dict[str, Any]:
        """Stream an upload to a new file directory with a hard size limit."""
        ext = ext.lower()
        if not ext.startswith("."):
            ext = "." + ext
        if not re.fullmatch(r"\.[a-z0-9]{2,5}", ext):
            raise StorageError("Unsupported file extension")
        file_id = new_id("fil")
        directory = self.file_dir(session_id, file_id)
        directory.mkdir(parents=True, exist_ok=False)
        target = directory / f"original{ext}"
        size = 0
        try:
            with target.open("wb") as handle:
                while True:
                    chunk = stream.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > max_bytes:
                        raise StorageError(
                            f"File exceeds the {max_bytes // (1024 * 1024)} MB upload limit"
                        )
                    handle.write(chunk)
            if size == 0:
                raise StorageError("Uploaded file is empty")
        except Exception:
            shutil.rmtree(directory, ignore_errors=True)
            raise

        record = {
            "id": file_id,
            "original_name": safe_display_name(display_name),
            "ext": ext,
            "size_bytes": size,
            "uploaded_at": utcnow(),
            "status": "uploaded",
            "progress": 0,
            "stage": "Uploaded",
            "error": None,
            "metadata": {},
            "has_analysis": False,
            "analysis_summary": {},
            "job_id": None,
        }
        with self._lock:
            session = self.get_session(session_id)
            if len(session.get("files", {})) >= self.config.max_files_per_session:
                shutil.rmtree(directory, ignore_errors=True)
                raise StorageError(
                    f"A session can contain at most {self.config.max_files_per_session} files"
                )
            session.setdefault("files", {})[file_id] = record
            session["updated_at"] = utcnow()
            self._atomic_write_json(self._session_file(session_id), session)
        return record

    def get_file(self, session_id: str, file_id: str) -> dict[str, Any]:
        session = self.get_session(session_id)
        record = session.get("files", {}).get(file_id)
        if not record:
            raise StorageError("File not found")
        return record

    def update_file(self, session_id: str, file_id: str, **fields: Any) -> dict[str, Any]:
        with self._lock:
            session = self.get_session(session_id)
            record = session.get("files", {}).get(file_id)
            if not record:
                raise StorageError("File not found")
            record.update(fields)
            session["updated_at"] = utcnow()
            self._atomic_write_json(self._session_file(session_id), session)
            return record

    def delete_file(self, session_id: str, file_id: str) -> bool:
        with self._lock:
            session = self.get_session(session_id)
            if file_id not in session.get("files", {}):
                return False
            del session["files"][file_id]
            session["updated_at"] = utcnow()
            self._atomic_write_json(self._session_file(session_id), session)
            shutil.rmtree(self.file_dir(session_id, file_id), ignore_errors=True)
            try:
                self.analysis_path(session_id, file_id).unlink(missing_ok=True)
            except OSError:
                pass
            return True

    def save_analysis(self, session_id: str, file_id: str, payload: dict[str, Any]) -> Path:
        path = self.analysis_path(session_id, file_id)
        with self._lock:
            self._atomic_write_json(path, payload)
        return path

    def load_analysis(self, session_id: str, file_id: str) -> dict[str, Any] | None:
        path = self.analysis_path(session_id, file_id)
        with self._lock:
            if not path.exists():
                return None
            try:
                with path.open("r", encoding="utf-8") as handle:
                    return json.load(handle)
            except (OSError, json.JSONDecodeError):
                return None

    # ---------------------------------------------------------------- cleanup
    def cleanup_expired(self) -> int:
        cutoff = time.time() - self.config.session_ttl_hours * 3600
        removed = 0
        if not self.config.sessions_dir.exists():
            return 0
        for entry in list(self.config.sessions_dir.iterdir()):
            if not entry.is_dir() or not valid_id(entry.name, "ses"):
                continue
            session_file = entry / "session.json"
            try:
                mtime = session_file.stat().st_mtime
            except OSError:
                mtime = entry.stat().st_mtime
            if mtime >= cutoff:
                continue
            try:
                with session_file.open("r", encoding="utf-8") as handle:
                    data = json.load(handle)
                active = any(
                    f.get("status") in {"queued", "analyzing"}
                    for f in data.get("files", {}).values()
                )
                if active and (time.time() - mtime) < 6 * 3600:
                    continue
            except (OSError, json.JSONDecodeError):
                pass
            shutil.rmtree(entry, ignore_errors=True)
            removed += 1
        # stale temp files
        tmp = self.config.temp_dir
        if tmp.exists():
            for entry in tmp.iterdir():
                try:
                    if entry.is_file() and time.time() - entry.stat().st_mtime > 86400:
                        entry.unlink()
                    elif entry.is_dir() and time.time() - entry.stat().st_mtime > 86400:
                        shutil.rmtree(entry, ignore_errors=True)
                except OSError:
                    pass
        return removed


store = SessionStore()
