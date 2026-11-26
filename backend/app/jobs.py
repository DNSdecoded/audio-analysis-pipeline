"""Background analysis job manager with per-file progress reporting."""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any

from .analysis.pipeline import AnalysisError, run_full_analysis
from .config import settings as default_settings
from .storage import SessionStore, new_id, store as default_store

logger = logging.getLogger("audio_analysis.jobs")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class JobManager:
    def __init__(self, storage: SessionStore = default_store, max_workers: int | None = None):
        self.store = storage
        self.executor = ThreadPoolExecutor(
            max_workers=max_workers or default_settings.max_concurrent_jobs,
            thread_name_prefix="aap-analysis",
        )
        self._lock = threading.RLock()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._file_jobs: dict[tuple[str, str], str] = {}
        self._last_file_update: dict[str, float] = {}

    def submit(self, session_id: str, file_id: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
        key = (session_id, file_id)
        with self._lock:
            existing = self._file_jobs.get(key)
            if existing:
                job = self._jobs.get(existing)
                if job and job["status"] in {"queued", "running"}:
                    return job
            record = self.store.get_file(session_id, file_id)
            if not record.get("metadata"):
                raise AnalysisError("File has not been validated yet")
            job_id = new_id("job")
            job = {
                "id": job_id,
                "session_id": session_id,
                "file_id": file_id,
                "file_name": record.get("original_name"),
                "status": "queued",
                "progress": 0.0,
                "stage": "Queued",
                "error": None,
                "created_at": _now(),
                "started_at": None,
                "finished_at": None,
                "result": None,
                "options": options or {},
            }
            self._jobs[job_id] = job
            self._file_jobs[key] = job_id
        self.store.update_file(session_id, file_id, status="queued", progress=0, stage="Queued", error=None, job_id=job_id)
        self.executor.submit(self._run, job_id)
        return self.get(job_id)

    def _update_job(self, job_id: str, **fields: Any) -> None:
        with self._lock:
            if job_id in self._jobs:
                self._jobs[job_id].update(fields)

    def _run(self, job_id: str) -> None:
        with self._lock:
            job = dict(self._jobs.get(job_id) or {})
        if not job:
            return
        session_id = job["session_id"]
        file_id = job["file_id"]
        options = job.get("options") or {}
        self._update_job(job_id, status="running", started_at=_now(), stage="Starting")
        try:
            record = self.store.get_file(session_id, file_id)
            metadata = record.get("metadata") or {}
            validation = record.get("validation") or {"ok": True, "errors": [], "warnings": []}
            path = self.store.file_dir(session_id, file_id) / f"original{record.get('ext', '')}"
            if not path.exists():
                raise AnalysisError("Original file is missing from session storage")

            last_write = 0.0
            def progress(fraction: float, stage: str) -> None:
                nonlocal last_write
                percent = round(max(0.0, min(100.0, fraction * 100.0)), 1)
                self._update_job(job_id, progress=percent, stage=stage)
                now = time.time()
                if now - last_write >= 1.5 or percent >= 99.0:
                    last_write = now
                    try:
                        self.store.update_file(session_id, file_id, status="analyzing", progress=percent, stage=stage)
                    except Exception:
                        logger.exception("Could not persist progress for %s", file_id)

            analysis = run_full_analysis(
                path=path,
                ext=record.get("ext", ""),
                metadata=metadata,
                validation=validation,
                file_id=file_id,
                original_name=record.get("original_name", "audio"),
                target_lufs=float(options.get("target_lufs", self.store.get_session(session_id).get("settings", {}).get("target_lufs", -14.0))),
                true_peak_limit=float(options.get("true_peak_limit", self.store.get_session(session_id).get("settings", {}).get("true_peak_limit", -1.0))),
                n_fft=int(options.get("fft_size", 4096)),
                hop_length=int(options.get("hop_length", 1024)),
                qc_overrides=options.get("qc_thresholds") or self.store.get_session(session_id).get("settings", {}).get("qc_thresholds"),
                progress=progress,
            )
            self.store.save_analysis(session_id, file_id, analysis)
            summary = analysis.get("summary", {})
            self.store.update_file(
                session_id, file_id,
                status="complete", progress=100, stage="Complete", error=None,
                has_analysis=True, analysis_summary=summary,
                analyzed_at=analysis.get("analyzed_at"),
            )
            self._update_job(
                job_id, status="complete", progress=100, stage="Complete",
                finished_at=_now(), result=summary,
            )
        except Exception as exc:
            logger.exception("Analysis failed for %s", file_id)
            message = str(exc) if isinstance(exc, AnalysisError) else f"Analysis failed: {exc}"
            try:
                self.store.update_file(
                    session_id, file_id,
                    status="error", stage="Failed", error=message,
                )
            except Exception:
                logger.exception("Could not persist failure state")
            self._update_job(
                job_id, status="failed", stage="Failed", error=message,
                finished_at=_now(),
            )
        finally:
            with self._lock:
                self._file_jobs.pop((session_id, file_id), None)

    def get(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise KeyError(job_id)
            return dict(job)

    def list_for_session(self, session_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(job) for job in self._jobs.values() if job["session_id"] == session_id]

    def active_for_file(self, session_id: str, file_id: str) -> bool:
        with self._lock:
            job_id = self._file_jobs.get((session_id, file_id))
            if not job_id:
                return False
            job = self._jobs.get(job_id)
            return bool(job and job["status"] in {"queued", "running"})

    def recover_interrupted(self) -> int:
        """Repair file records left 'queued'/'analyzing' without a live job.

        Job state is held in memory, so a restart (or an executor shutdown
        that cancelled queued work) leaves persisted records claiming work
        that no longer exists.  Those files could otherwise never be
        re-analysed and the UI would poll forever.  A previously stored
        analysis is kept (it is only replaced atomically on success).
        """
        repaired = 0
        for session in self.store.list_sessions():
            session_id = session.get("id", "")
            for file_id, record in (session.get("files") or {}).items():
                if record.get("status") not in {"queued", "analyzing"}:
                    continue
                if self.active_for_file(session_id, file_id):
                    continue
                has_analysis = bool(record.get("has_analysis")) and self.store.load_analysis(session_id, file_id) is not None
                try:
                    self.store.update_file(
                        session_id, file_id,
                        status="complete" if has_analysis else "error",
                        stage="Interrupted" if not has_analysis else "Complete (previous result; re-analysis was interrupted)",
                        progress=100 if has_analysis else 0,
                        error="Analysis was interrupted before it finished (server restart). Run the analysis again.",
                        job_id=None,
                    )
                    repaired += 1
                except Exception:
                    logger.exception("Could not repair interrupted record %s/%s", session_id, file_id)
        return repaired

    def purge_old(self, max_age_seconds: float = 86400.0) -> None:
        cutoff = time.time() - max_age_seconds
        with self._lock:
            for job_id, job in list(self._jobs.items()):
                if job["status"] in {"complete", "failed"}:
                    try:
                        finished = datetime.fromisoformat(job.get("finished_at") or job.get("created_at")).timestamp()
                    except Exception:
                        finished = cutoff - 1
                    if finished < cutoff:
                        del self._jobs[job_id]


jobs = JobManager()
