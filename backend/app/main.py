"""FastAPI application: upload, analysis jobs, comparison, QC and reports."""

from __future__ import annotations

import logging
import mimetypes
import os
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

from fastapi import Body, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .analysis.alignment import align_files
from .analysis.comparison import compare_analyses
from .analysis.loudness import gain_preview
from .analysis.pipeline import AnalysisError, _recommendations
from .analysis.qc import DEFAULT_THRESHOLDS, THRESHOLD_SCHEMA, analyze_qc, merge_thresholds
from .analysis.segment import analyze_segment
from .analysis.spectral import compute_average_spectrum, compute_spectrogram_range
from .analysis.time_domain import compute_waveform_peaks
from .analysis.utils import round_sig
from .audio_io import DecodeError, decode_audio, decode_segment
from .config import SUPPORTED_FORMATS, settings
from .jobs import jobs
from .reporting import (
    PLOT_BUILDERS,
    build_comparison_csv,
    build_csv,
    build_json_report,
    build_pdf,
    build_qc_csv,
    plot_comparison_bands,
    plot_comparison_loudness,
    plot_comparison_spectrum,
    render_plot,
)
from .storage import SessionStore, StorageError, safe_display_name, store
from .validation import validate_upload

logger = logging.getLogger("audio_analysis.api")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

API_KEY = os.environ.get("AAP_API_KEY")
VERSION = "1.0.0"
MIME_BY_EXT = {
    ".wav": "audio/wav", ".wave": "audio/wav", ".mp3": "audio/mpeg",
    ".flac": "audio/flac", ".aac": "audio/aac", ".ogg": "audio/ogg",
    ".oga": "audio/ogg", ".aiff": "audio/aiff", ".aif": "audio/aiff",
    ".aifc": "audio/aiff", ".m4a": "audio/mp4", ".mp4": "audio/mp4",
}

_stop_cleanup = threading.Event()


def _cleanup_loop() -> None:
    while not _stop_cleanup.wait(settings.cleanup_interval_seconds):
        try:
            removed = store.cleanup_expired()
            jobs.purge_old()
            if removed:
                logger.info("Removed %s expired session(s)", removed)
        except Exception:
            logger.exception("Cleanup failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        repaired = jobs.recover_interrupted()
        if repaired:
            logger.info("Repaired %s file record(s) left in an interrupted analysis state", repaired)
    except Exception:
        logger.exception("Interrupted-job recovery failed")
    thread = threading.Thread(target=_cleanup_loop, daemon=True, name="aap-cleanup")
    thread.start()
    try:
        yield
    finally:
        _stop_cleanup.set()
        jobs.executor.shutdown(wait=False, cancel_futures=True)


app = FastAPI(
    title="Audio Analysis Pipeline API",
    version=VERSION,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)


# Upper bound for one upload request: a full batch plus multipart overhead.
MAX_UPLOAD_REQUEST_BYTES = settings.max_files_per_session * (settings.max_file_size_mb * 1024 * 1024 + 64 * 1024)


def _content_disposition(disposition: str, filename: str) -> str:
    """RFC 6266 header with an ASCII fallback and a UTF-8 filename*.

    Header values must be latin-1 encodable; raw non-ASCII names caused 500s.
    """
    fallback = "".join(ch if 32 <= ord(ch) < 127 and ch not in '"\\' else "_" for ch in filename) or "download"
    return f"{disposition}; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename)}"


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    path = request.url.path
    if API_KEY and path.startswith("/api") and path not in {"/api/health"}:
        if request.headers.get("x-api-key") != API_KEY:
            return JSONResponse({"detail": "Unauthorized: missing or invalid API key"}, status_code=401)
    if request.method == "POST" and path.endswith("/files"):
        # Reject oversized uploads before the multipart body is spooled.
        try:
            declared = int(request.headers.get("content-length") or 0)
        except ValueError:
            declared = 0
        if declared > MAX_UPLOAD_REQUEST_BYTES:
            return JSONResponse(
                {"detail": f"Upload request exceeds the {settings.max_files_per_session} x {settings.max_file_size_mb} MB limit"},
                status_code=413,
            )
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    if path.startswith("/api"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(StorageError)
async def storage_error_handler(request: Request, exc: StorageError):
    status = 404 if "not found" in str(exc).lower() or "expired" in str(exc).lower() else 400
    return JSONResponse({"detail": str(exc)}, status_code=status)


@app.exception_handler(AnalysisError)
async def analysis_error_handler(request: Request, exc: AnalysisError):
    return JSONResponse({"detail": str(exc)}, status_code=409)


@app.exception_handler(DecodeError)
async def decode_error_handler(request: Request, exc: DecodeError):
    return JSONResponse({"detail": str(exc)}, status_code=400)


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s", request.url.path)
    return JSONResponse({"detail": "An unexpected server error occurred. Check the server logs."}, status_code=500)


# --------------------------------------------------------------------- models
class SessionCreate(BaseModel):
    name: str | None = Field(default=None, max_length=120)


class SessionPatch(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    target_lufs: float | None = Field(default=None, ge=-60, le=0)
    true_peak_limit: float | None = Field(default=None, ge=-20, le=6)
    fft_size: int | None = Field(default=None, ge=256, le=32768)
    hop_length: int | None = Field(default=None, ge=32, le=16384)
    qc_thresholds: dict[str, Any] | None = None


class AnalyzeRequest(BaseModel):
    file_ids: list[str] | None = None
    force: bool = False
    target_lufs: float | None = Field(default=None, ge=-60, le=0)
    true_peak_limit: float | None = Field(default=None, ge=-20, le=6)
    fft_size: int | None = Field(default=None, ge=256, le=32768)
    hop_length: int | None = Field(default=None, ge=32, le=16384)
    qc_thresholds: dict[str, Any] | None = None


class SegmentRequest(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    target_lufs: float | None = Field(default=None, ge=-60, le=0)
    true_peak_limit: float | None = Field(default=None, ge=-20, le=6)


class CompareRequest(BaseModel):
    file_ids: list[str]
    parameters: list[str] | None = None
    target_lufs: float | None = Field(default=None, ge=-60, le=0)
    true_peak_limit: float | None = Field(default=None, ge=-20, le=6)
    reference_file_id: str | None = None
    mode: Literal["full", "segment"] = "full"
    ranges: dict[str, dict[str, float]] | None = None


class AlignRequest(BaseModel):
    file_a: str
    file_b: str
    method: Literal["auto", "envelope", "waveform"] = "auto"
    max_offset_seconds: float = Field(default=15.0, ge=0.5, le=120.0)
    manual_offset_seconds: float | None = Field(default=None, ge=-600, le=600)


class ReportRequest(BaseModel):
    format: Literal["pdf", "json", "csv", "qc-csv", "comparison-csv"] = "pdf"
    file_ids: list[str] | None = None
    include_comparison: bool = True
    parameters: list[str] | None = None
    target_lufs: float | None = Field(default=None, ge=-60, le=0)
    true_peak_limit: float | None = Field(default=None, ge=-20, le=6)
    reference_file_id: str | None = None


class QCRequest(BaseModel):
    thresholds: dict[str, Any] | None = None


# ------------------------------------------------------------------- helpers
def _session(session_id: str) -> dict[str, Any]:
    return store.get_session(session_id)


def _session_payload(session: dict[str, Any]) -> dict[str, Any]:
    files = sorted(session.get("files", {}).values(), key=lambda f: f.get("uploaded_at", ""))
    settings_out = dict(session.get("settings", {}))
    settings_out["qc_thresholds"] = merge_thresholds(settings_out.get("qc_thresholds"))
    return {
        "id": session.get("id"),
        "name": session.get("name"),
        "created_at": session.get("created_at"),
        "updated_at": session.get("updated_at"),
        "settings": settings_out,
        "files": files,
        "jobs": jobs.list_for_session(session.get("id", "")),
    }


def _file_record(session_id: str, file_id: str) -> dict[str, Any]:
    return store.get_file(session_id, file_id)


def _analysis_or_404(session_id: str, file_id: str) -> dict[str, Any]:
    _file_record(session_id, file_id)
    analysis = store.load_analysis(session_id, file_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="Analysis not available for this file yet")
    return analysis


def _path_for(session_id: str, record: dict[str, Any]) -> Path:
    return store.file_dir(session_id, record["id"]) / f"original{record.get('ext', '')}"


def _safe_range(start: float | None, end: float | None, duration: float) -> tuple[float | None, float | None]:
    if start is None and end is None:
        return None, None
    start = max(0.0, float(start or 0.0))
    end = min(float(duration), float(end if end is not None else duration))
    if end <= start + 1e-6:
        raise HTTPException(status_code=400, detail="Selected time range is empty")
    return start, end


def _effective_options(session: dict[str, Any], req: AnalyzeRequest | None = None) -> dict[str, Any]:
    sess_settings = session.get("settings", {})
    options = {
        "target_lufs": float(sess_settings.get("target_lufs", settings.default_target_lufs)),
        "true_peak_limit": float(sess_settings.get("true_peak_limit", settings.default_true_peak_limit)),
        "fft_size": int(sess_settings.get("fft_size", settings.default_fft_size)),
        "hop_length": int(sess_settings.get("hop_length", settings.default_hop_length)),
        "qc_thresholds": sess_settings.get("qc_thresholds"),
    }
    if req:
        for key in ("target_lufs", "true_peak_limit", "fft_size", "hop_length", "qc_thresholds"):
            value = getattr(req, key, None)
            if value is not None:
                options[key] = value
    options["qc_thresholds"] = merge_thresholds(options.get("qc_thresholds"))
    return options


def _report_analyses(session_id: str, session: dict[str, Any], file_ids: list[str] | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    records = sorted(session.get("files", {}).values(), key=lambda f: f.get("uploaded_at", ""))
    by_id = {r["id"]: r for r in records}
    # Keep the requested order but drop repeats (a repeated id produced
    # duplicate rows and duplicate comparison columns).
    ids = list(dict.fromkeys(file_ids)) if file_ids else [r["id"] for r in records if r.get("has_analysis")]
    analyses = []
    missing = []
    for fid in ids:
        if fid not in by_id:
            missing.append(fid)
            continue
        analysis = store.load_analysis(session_id, fid)
        if analysis is None:
            missing.append(fid)
        else:
            analyses.append(analysis)
    if missing:
        raise HTTPException(status_code=400, detail=f"Analysis not available for: {', '.join(missing)}")
    return analyses, records


def _build_comparison(session: dict[str, Any], analyses: list[dict[str, Any]], request: ReportRequest) -> dict[str, Any] | None:
    if not request.include_comparison or len(analyses) < 2:
        return None
    names = {a["file_id"]: a.get("original_name", a["file_id"]) for a in analyses}
    order = [a["file_id"] for a in analyses]
    options = _effective_options(session)
    if request.reference_file_id and request.reference_file_id not in order:
        raise HTTPException(status_code=400, detail="Reference file must be one of the files in the report")
    return compare_analyses(
        {a["file_id"]: a for a in analyses},
        order,
        names,
        selected_parameters=request.parameters,
        target_lufs=float(request.target_lufs if request.target_lufs is not None else options["target_lufs"]),
        true_peak_limit=float(request.true_peak_limit if request.true_peak_limit is not None else options["true_peak_limit"]),
        reference_file_id=request.reference_file_id,
    )


# --------------------------------------------------------------------- system
@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "version": VERSION,
        "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "supported_formats": sorted(set(SUPPORTED_FORMATS.values())),
        "limits": {
            "max_file_size_mb": settings.max_file_size_mb,
            "max_duration_seconds": settings.max_duration_seconds,
            "max_files_per_session": settings.max_files_per_session,
            "max_concurrent_jobs": settings.max_concurrent_jobs,
            "session_ttl_hours": settings.session_ttl_hours,
        },
        "analysis_engine": "NumPy/SciPy/librosa/soundfile/PyAV",
        "original_files_preserved": True,
    }


@app.get("/api/settings")
def app_settings() -> dict[str, Any]:
    return {
        "version": VERSION,
        "supported_formats": sorted(set(SUPPORTED_FORMATS.values())),
        "supported_extensions": list(settings.allowed_extensions),
        "limits": {
            "max_file_size_mb": settings.max_file_size_mb,
            "max_duration_seconds": settings.max_duration_seconds,
            "max_files_per_session": settings.max_files_per_session,
            "max_concurrent_jobs": settings.max_concurrent_jobs,
            "session_ttl_hours": settings.session_ttl_hours,
        },
        "defaults": {
            "target_lufs": settings.default_target_lufs,
            "true_peak_limit": settings.default_true_peak_limit,
            "fft_size": settings.default_fft_size,
            "hop_length": settings.default_hop_length,
        },
        "qc_threshold_schema": THRESHOLD_SCHEMA,
        "qc_thresholds": DEFAULT_THRESHOLDS,
        "methods": {
            "loudness": "ITU-R BS.1770-4 / EBU R128",
            "true_peak": "4x oversampling (BS.1770-4 Annex 2)",
            "spectrum": "STFT, Hann window, native sample rate",
            "key": "Krumhansl-Schmuckler chroma profiles (estimate)",
            "tempo": "librosa beat tracker + tempogram (estimate)",
            "pitch": "librosa.pyin probabilistic YIN (estimate)",
            "stereo": "Pearson correlation, mid/side RMS, mono fold-down",
        },
        "notes": [
            "Original files are never modified.",
            "Lossy files do not have a meaningful original PCM bit depth.",
            "Estimated measurements are labelled with confidence.",
        ],
    }


@app.get("/api/qc/thresholds")
def qc_thresholds() -> dict[str, Any]:
    return {"thresholds": DEFAULT_THRESHOLDS, "schema": THRESHOLD_SCHEMA}


# ------------------------------------------------------------------- sessions
@app.post("/api/sessions")
def create_session(body: SessionCreate | None = Body(default=None)) -> dict[str, Any]:
    session = store.create_session(body.name if body else None)
    return _session_payload(session)


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str) -> dict[str, Any]:
    return _session_payload(_session(session_id))


@app.get("/api/sessions/{session_id}/overview")
def session_overview(session_id: str) -> dict[str, Any]:
    """Lightweight dashboard payload built from stored analyses."""
    session = _session(session_id)
    files = []
    recommendations = []
    for record in sorted(session.get("files", {}).values(), key=lambda f: f.get("uploaded_at", "")):
        analysis = store.load_analysis(session_id, record["id"])
        item: dict[str, Any] = {
            "id": record["id"],
            "name": record.get("original_name"),
            "status": record.get("status"),
            "metadata": record.get("metadata", {}),
            "analysis_summary": record.get("analysis_summary", {}),
            "has_analysis": bool(analysis),
            "validation": record.get("validation", {}),
        }
        if analysis:
            td = analysis.get("time_domain", {})
            loud = analysis.get("loudness", {})
            env = td.get("envelopes", {})
            st = loud.get("short_term", {})
            bands = analysis.get("spectral", {}).get("bands", {}).get("bands", [])
            item["quick"] = {
                "rms_times": (env.get("times") or [])[:: max(1, len(env.get("times") or []) // 240)],
                "rms_db": (env.get("rms_db") or [])[:: max(1, len(env.get("rms_db") or []) // 240)],
                "short_term_times": (st.get("times") or [])[:: max(1, len(st.get("times") or []) // 240)],
                "short_term_lufs": (st.get("lufs") or [])[:: max(1, len(st.get("lufs") or []) // 240)],
                "bands": [{"label": b.get("label"), "share": b.get("relative_energy_pct")} for b in bands],
                "qc": analysis.get("qc", {}).get("summary"),
                "qc_overall": analysis.get("qc", {}).get("overall"),
                "key": analysis.get("musical", {}).get("key", {}).get("key"),
                "tempo_bpm": analysis.get("musical", {}).get("tempo", {}).get("bpm"),
                "recommendation_count": len(analysis.get("recommendations", [])),
            }
            for rec in analysis.get("recommendations", []):
                recommendations.append({
                    "file_id": record["id"],
                    "file_name": record.get("original_name"),
                    "id": rec.get("id"),
                    "title": rec.get("title"),
                    "priority": rec.get("priority"),
                    "category": rec.get("category"),
                    "supporting_measurement": rec.get("supporting_measurement"),
                    "recommendation": rec.get("recommendation"),
                })
        files.append(item)
    return {
        "session": _session_payload(session),
        "files": files,
        "recommendations": recommendations[:60],
        "totals": {
            "files": len(files),
            "analysed": sum(1 for f in files if f.get("has_analysis")),
            "duration_seconds": round_sig(sum(float(f.get("metadata", {}).get("duration", 0) or 0) for f in files), 2),
            "errors": sum(int((f.get("analysis_summary") or {}).get("qc_errors", 0) or 0) for f in files),
            "warnings": sum(int((f.get("analysis_summary") or {}).get("qc_warnings", 0) or 0) for f in files),
        },
    }




@app.patch("/api/sessions/{session_id}")
def patch_session(session_id: str, body: SessionPatch) -> dict[str, Any]:
    session = _session(session_id)
    settings_update = dict(session.get("settings", {}))
    if body.target_lufs is not None:
        settings_update["target_lufs"] = body.target_lufs
    if body.true_peak_limit is not None:
        settings_update["true_peak_limit"] = body.true_peak_limit
    if body.fft_size is not None:
        settings_update["fft_size"] = body.fft_size
    if body.hop_length is not None:
        settings_update["hop_length"] = body.hop_length
    if body.qc_thresholds is not None:
        settings_update["qc_thresholds"] = merge_thresholds(body.qc_thresholds)
    fields: dict[str, Any] = {"settings": settings_update}
    if body.name is not None:
        fields["name"] = safe_display_name(body.name)[:80]
    return _session_payload(store.update_session(session_id, **fields))


@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: str) -> dict[str, Any]:
    session = _session(session_id)
    active = [job for job in jobs.list_for_session(session_id) if job["status"] in {"queued", "running"}]
    if active:
        raise HTTPException(status_code=409, detail="Cannot delete a session while analysis jobs are running")
    removed = store.delete_session(session_id)
    return {"deleted": removed, "session_id": session_id}


# --------------------------------------------------------------------- upload
@app.post("/api/sessions/{session_id}/files")
async def upload_files(session_id: str, files: list[UploadFile] = File(...)) -> dict[str, Any]:
    session = _session(session_id)
    if not files:
        raise HTTPException(status_code=400, detail="No files supplied")
    if len(files) > settings.max_files_per_session:
        raise HTTPException(
            status_code=400,
            detail=f"At most {settings.max_files_per_session} files can be uploaded in one batch",
        )
    results = []
    errors = []
    for upload in files:
        original_name = safe_display_name(upload.filename or "audio")
        ext = Path(original_name).suffix.lower()
        if ext not in settings.allowed_extensions:
            errors.append({
                "file_name": original_name,
                "errors": [f"Unsupported extension '{ext or 'none'}'. Supported: WAV, MP3, FLAC, AAC, OGG, AIFF."],
                "warnings": [],
            })
            await upload.close()
            continue
        try:
            await upload.seek(0)
        except Exception:
            pass
        record = None
        try:
            record = store.add_file(
                session_id, original_name, ext, upload.file,
                settings.max_file_size_mb * 1024 * 1024,
            )
            path = _path_for(session_id, record)
            validation = validate_upload(path, original_name, ext, record["size_bytes"], settings)
            if not validation.get("ok"):
                store.delete_file(session_id, record["id"])
                errors.append({
                    "file_name": original_name,
                    "errors": validation.get("errors", ["Validation failed"]),
                    "warnings": validation.get("warnings", []),
                })
                continue
            updated = store.update_file(
                session_id, record["id"],
                status="validated",
                stage="Validated" if not validation.get("warnings") else "Validated with warnings",
                metadata=validation.get("metadata", {}),
                validation=validation,
                error=None,
                progress=0,
            )
            results.append(updated)
        except StorageError as exc:
            if record:
                try:
                    store.delete_file(session_id, record["id"])
                except Exception:
                    pass
            errors.append({"file_name": original_name, "errors": [str(exc)], "warnings": []})
        except Exception as exc:
            logger.exception("Upload validation failed for %s", original_name)
            if record:
                try:
                    store.delete_file(session_id, record["id"])
                except Exception:
                    pass
            errors.append({"file_name": original_name, "errors": [f"Validation failed: {exc}"], "warnings": []})
        finally:
            await upload.close()
    return {"files": results, "errors": errors, "session": _session_payload(_session(session_id))}


# ---------------------------------------------------------------------- files
@app.get("/api/sessions/{session_id}/files/{file_id}")
def get_file(session_id: str, file_id: str) -> dict[str, Any]:
    return _file_record(session_id, file_id)


@app.delete("/api/sessions/{session_id}/files/{file_id}")
def delete_file(session_id: str, file_id: str) -> dict[str, Any]:
    if jobs.active_for_file(session_id, file_id):
        raise HTTPException(status_code=409, detail="Cannot remove a file while it is being analysed")
    removed = store.delete_file(session_id, file_id)
    if not removed:
        raise HTTPException(status_code=404, detail="File not found")
    return {"deleted": True, "file_id": file_id, "session": _session_payload(_session(session_id))}


@app.get("/api/sessions/{session_id}/files/{file_id}/audio")
def get_audio(session_id: str, file_id: str):
    record = _file_record(session_id, file_id)
    path = _path_for(session_id, record)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Original audio file is missing")
    media_type = MIME_BY_EXT.get(record.get("ext", ""), "application/octet-stream")
    display = record.get("original_name", "audio")
    headers = {
        "Content-Disposition": _content_disposition("inline", display),
        "Cache-Control": "private, no-store",
    }
    return FileResponse(path, media_type=media_type, headers=headers)


@app.get("/api/sessions/{session_id}/files/{file_id}/analysis")
def get_analysis(session_id: str, file_id: str) -> dict[str, Any]:
    return _analysis_or_404(session_id, file_id)


@app.get("/api/sessions/{session_id}/files/{file_id}/waveform")
def get_waveform(
    session_id: str,
    file_id: str,
    start: float | None = Query(default=None, ge=0),
    end: float | None = Query(default=None, gt=0),
    buckets: int = Query(default=2000, ge=100, le=8000),
) -> dict[str, Any]:
    record = _file_record(session_id, file_id)
    duration = float(record.get("metadata", {}).get("duration", 0) or 0)
    analysis = store.load_analysis(session_id, file_id)
    if start is None and end is None and analysis:
        wf = analysis.get("time_domain", {}).get("waveform", {})
        if wf.get("times") and buckets <= int(wf.get("bucket_count", 0) or 0):
            return {
                **wf,
                "sample_rate": record.get("metadata", {}).get("sample_rate"),
                "duration": duration,
                "source": "stored analysis",
                "selection": None,
            }
    if start is not None or end is not None:
        start, end = _safe_range(start, end, duration or 1e9)
    path = _path_for(session_id, record)
    try:
        if start is None and end is None:
            data, sr, warnings = decode_audio(path, record.get("ext"))
            selection = None
        else:
            data, sr, warnings = decode_segment(path, record.get("ext"), start or 0.0, end or (duration or 0.0))
            selection = {"start": start, "end": end}
    except DecodeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    payload = compute_waveform_peaks(data, sr, buckets)
    if selection is not None:
        # Peak extraction works on the decoded slice (times start at 0); shift
        # them onto the file timeline so they match the requested selection.
        offset = float(start or 0.0)
        payload["times"] = [round_sig(t + offset, 4) for t in payload["times"]]
    return {
        **payload,
        "sample_rate": sr,
        "duration": data.shape[0] / sr,
        "source": "decoded original",
        "selection": selection,
        "warnings": warnings,
    }


@app.get("/api/sessions/{session_id}/files/{file_id}/spectrum")
def get_spectrum(
    session_id: str,
    file_id: str,
    start: float | None = Query(default=None, ge=0),
    end: float | None = Query(default=None, gt=0),
    n_fft: int | None = Query(default=None, ge=256, le=32768),
    hop_length: int | None = Query(default=None, ge=32, le=16384),
) -> dict[str, Any]:
    record = _file_record(session_id, file_id)
    analysis = store.load_analysis(session_id, file_id)
    duration = float(record.get("metadata", {}).get("duration", 0) or 0)
    if start is None and end is None and analysis:
        fft = analysis.get("spectral", {}).get("fft", {})
        if (n_fft is None or int(n_fft) == int(fft.get("n_fft", 0))) and (hop_length is None or int(hop_length) == int(analysis.get("analysis_settings", {}).get("hop_length", 0))):
            return {**fft, "selection": None, "source": "stored analysis"}
    start, end = _safe_range(start, end, duration or 1e9) if (start is not None or end is not None) else (None, None)
    n_fft = int(n_fft or (analysis or {}).get("analysis_settings", {}).get("fft_size", settings.default_fft_size))
    hop_length = int(hop_length or (analysis or {}).get("analysis_settings", {}).get("hop_length", settings.default_hop_length))
    path = _path_for(session_id, record)
    try:
        if start is None:
            data, sr, warnings = decode_audio(path, record.get("ext"))
            selection = None
        else:
            data, sr, warnings = decode_segment(path, record.get("ext"), start, end or duration)
            selection = {"start": start, "end": end}
    except DecodeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    mono = data.mean(axis=1) if data.ndim > 1 else data
    payload = compute_average_spectrum(mono, sr, n_fft, hop_length)
    return {**payload, "selection": selection, "source": "decoded original", "warnings": warnings}


@app.get("/api/sessions/{session_id}/files/{file_id}/spectrogram")
def get_spectrogram(
    session_id: str,
    file_id: str,
    start: float | None = Query(default=None, ge=0),
    end: float | None = Query(default=None, gt=0),
    n_fft: int | None = Query(default=None, ge=256, le=32768),
    hop_length: int | None = Query(default=None, ge=32, le=16384),
    max_frames: int = Query(default=400, ge=50, le=1200),
) -> dict[str, Any]:
    record = _file_record(session_id, file_id)
    analysis = store.load_analysis(session_id, file_id)
    duration = float(record.get("metadata", {}).get("duration", 0) or 0)
    if start is None and end is None and analysis:
        spec = analysis.get("spectral", {}).get("spectrogram", {})
        if (n_fft is None or int(n_fft) == int(spec.get("n_fft", 0))) and (hop_length is None or int(hop_length) == int(spec.get("hop_length", 0))):
            return {**spec, "selection": None, "source": "stored analysis"}
    start, end = _safe_range(start, end, duration or 1e9) if (start is not None or end is not None) else (None, None)
    n_fft = int(n_fft or (analysis or {}).get("analysis_settings", {}).get("fft_size", settings.default_fft_size))
    hop_length = int(hop_length or (analysis or {}).get("analysis_settings", {}).get("hop_length", settings.default_hop_length))
    path = _path_for(session_id, record)
    try:
        if start is None:
            data, sr, warnings = decode_audio(path, record.get("ext"))
            selection = None
        else:
            data, sr, warnings = decode_segment(path, record.get("ext"), start, end or duration)
            selection = {"start": start, "end": end}
    except DecodeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    mono = data.mean(axis=1) if data.ndim > 1 else data
    payload = compute_spectrogram_range(mono, sr, n_fft, hop_length, max_frames)
    if selection is not None:
        offset = float(start or 0.0)
        payload["times"] = [round_sig(t + offset, 4) for t in payload["times"]]
    return {**payload, "selection": selection, "source": "decoded original", "warnings": warnings}


@app.post("/api/sessions/{session_id}/files/{file_id}/segment-analysis")
def segment_analysis(session_id: str, file_id: str, body: SegmentRequest) -> dict[str, Any]:
    record = _file_record(session_id, file_id)
    duration = float(record.get("metadata", {}).get("duration", 0) or 0)
    if body.end > duration + 0.01:
        raise HTTPException(status_code=400, detail=f"Segment end exceeds file duration ({duration:.2f} s)")
    session = _session(session_id)
    options = _effective_options(session)
    path = _path_for(session_id, record)
    try:
        return analyze_segment(
            path, record.get("ext"), body.start, body.end,
            metadata=record.get("metadata"),
            target_lufs=float(body.target_lufs if body.target_lufs is not None else options["target_lufs"]),
            true_peak_limit=float(body.true_peak_limit if body.true_peak_limit is not None else options["true_peak_limit"]),
        )
    except Exception as exc:
        logger.exception("Segment analysis failed")
        raise HTTPException(status_code=400, detail=f"Segment analysis failed: {exc}")


# -------------------------------------------------------------------- analysis
@app.post("/api/sessions/{session_id}/analyze")
def analyze_session(session_id: str, body: AnalyzeRequest | None = Body(default=None)) -> dict[str, Any]:
    session = _session(session_id)
    body = body or AnalyzeRequest()
    records = sorted(session.get("files", {}).values(), key=lambda f: f.get("uploaded_at", ""))
    if body.file_ids is not None:
        by_id = {r["id"]: r for r in records}
        missing = [fid for fid in body.file_ids if fid not in by_id]
        if missing:
            raise HTTPException(status_code=404, detail=f"File(s) not found: {', '.join(missing)}")
        records = [by_id[fid] for fid in body.file_ids]
    if not records:
        raise HTTPException(status_code=400, detail="No files to analyse")
    options = _effective_options(session, body)
    submitted = []
    skipped = []
    errors = []
    for record in records:
        if jobs.active_for_file(session_id, record["id"]):
            existing = next((j for j in jobs.list_for_session(session_id) if j["file_id"] == record["id"] and j["status"] in {"queued", "running"}), None)
            if existing:
                submitted.append(existing)
            continue
        # A 'queued'/'analyzing' record without a live job was interrupted
        # (e.g. by a restart); it must be re-submittable, not skipped forever.
        interrupted = record.get("status") in {"queued", "analyzing"}
        if record.get("has_analysis") and not body.force and not interrupted:
            skipped.append({"file_id": record["id"], "file_name": record.get("original_name"), "reason": "Already analysed"})
            continue
        if not record.get("metadata"):
            errors.append({"file_id": record["id"], "file_name": record.get("original_name"), "error": "File has not passed validation"})
            continue
        try:
            job = jobs.submit(session_id, record["id"], options)
            submitted.append(job)
        except Exception as exc:
            errors.append({"file_id": record["id"], "file_name": record.get("original_name"), "error": str(exc)})
    return {"jobs": submitted, "skipped": skipped, "errors": errors, "session": _session_payload(_session(session_id))}


@app.post("/api/sessions/{session_id}/files/{file_id}/analyze")
def analyze_file(session_id: str, file_id: str) -> dict[str, Any]:
    _file_record(session_id, file_id)
    session = _session(session_id)
    options = _effective_options(session)
    job = jobs.submit(session_id, file_id, options)
    return {"job": job, "session": _session_payload(_session(session_id))}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    try:
        return jobs.get(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Job not found")


@app.get("/api/sessions/{session_id}/jobs")
def list_jobs(session_id: str) -> dict[str, Any]:
    _session(session_id)
    return {"jobs": jobs.list_for_session(session_id)}


# ------------------------------------------------------------------ comparison
@app.post("/api/sessions/{session_id}/compare")
def compare(session_id: str, body: CompareRequest) -> dict[str, Any]:
    session = _session(session_id)
    records = session.get("files", {})
    ids = list(dict.fromkeys(body.file_ids))
    if len(ids) < 2:
        raise HTTPException(status_code=400, detail="Select at least two files to compare")
    for fid in ids:
        if fid not in records:
            raise HTTPException(status_code=404, detail=f"File not found: {fid}")
    if body.reference_file_id and body.reference_file_id not in ids:
        raise HTTPException(status_code=400, detail="Reference file must be one of the compared files")
    options = _effective_options(session)
    target = float(body.target_lufs if body.target_lufs is not None else options["target_lufs"])
    limit = float(body.true_peak_limit if body.true_peak_limit is not None else options["true_peak_limit"])
    analyses: dict[str, dict[str, Any]] = {}
    if body.mode == "full":
        missing = []
        for fid in ids:
            analysis = store.load_analysis(session_id, fid)
            if analysis is None:
                missing.append(records[fid].get("original_name", fid))
            else:
                analyses[fid] = analysis
        if missing:
            raise HTTPException(status_code=400, detail=f"Analysis not available for: {', '.join(missing)}")
    else:
        ranges = body.ranges or {}
        for fid in ids:
            rng = ranges.get(fid)
            if not rng:
                raise HTTPException(status_code=400, detail=f"Segment range missing for file {fid}")
            record = records[fid]
            duration = float(record.get("metadata", {}).get("duration", 0) or 0)
            start = float(rng.get("start", 0.0))
            end = float(rng.get("end", duration))
            if start < 0 or end <= start or end > duration + 0.01:
                raise HTTPException(status_code=400, detail=f"Invalid segment range for {record.get('original_name')}")
            try:
                analyses[fid] = analyze_segment(
                    _path_for(session_id, record), record.get("ext"), start, end,
                    metadata=record.get("metadata"), target_lufs=target, true_peak_limit=limit,
                )
            except Exception as exc:
                raise HTTPException(status_code=400, detail=f"Segment analysis failed for {record.get('original_name')}: {exc}")
    names = {fid: records[fid].get("original_name", fid) for fid in ids}
    result = compare_analyses(
        analyses, ids, names,
        selected_parameters=body.parameters,
        target_lufs=target,
        true_peak_limit=limit,
        reference_file_id=body.reference_file_id,
        mode=body.mode,
        segment_ranges=body.ranges,
    )
    result["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    result["session_id"] = session_id
    return result


@app.post("/api/sessions/{session_id}/align")
def align(session_id: str, body: AlignRequest) -> dict[str, Any]:
    records = _session(session_id).get("files", {})
    if body.file_a not in records or body.file_b not in records:
        raise HTTPException(status_code=404, detail="Both files must belong to this session")
    if body.file_a == body.file_b:
        raise HTTPException(status_code=400, detail="Choose two different files")
    record_a = records[body.file_a]
    record_b = records[body.file_b]
    result = align_files(
        _path_for(session_id, record_a),
        _path_for(session_id, record_b),
        method=body.method,
        max_offset_seconds=body.max_offset_seconds,
        manual_offset_seconds=body.manual_offset_seconds,
    )
    result["file_a"] = {"id": body.file_a, "name": record_a.get("original_name")}
    result["file_b"] = {"id": body.file_b, "name": record_b.get("original_name")}
    return result


# ------------------------------------------------------------------------- QC
@app.post("/api/sessions/{session_id}/qc/recompute")
def recompute_qc(session_id: str, body: QCRequest | None = Body(default=None)) -> dict[str, Any]:
    session = _session(session_id)
    body = body or QCRequest()
    thresholds = merge_thresholds(body.thresholds if body.thresholds is not None else session.get("settings", {}).get("qc_thresholds"))
    settings_update = dict(session.get("settings", {}))
    settings_update["qc_thresholds"] = thresholds
    store.update_session(session_id, settings=settings_update)
    options = _effective_options(_session(session_id))
    updated = []
    for fid, record in session.get("files", {}).items():
        analysis = store.load_analysis(session_id, fid)
        if analysis is None:
            continue
        qc = analyze_qc(analysis, thresholds)
        analysis["qc"] = qc
        analysis["track_gain"] = gain_preview(
            analysis.get("loudness", {}).get("integrated_lufs"),
            analysis.get("loudness", {}).get("sample_peak_dbfs"),
            analysis.get("loudness", {}).get("true_peak_dbtp"),
            options["target_lufs"], options["true_peak_limit"],
        )
        analysis["recommendations"] = _recommendations(analysis, options["target_lufs"], options["true_peak_limit"])
        analysis["summary"]["qc_overall"] = qc.get("overall")
        analysis["summary"]["qc_errors"] = qc.get("error_count")
        analysis["summary"]["qc_warnings"] = qc.get("warning_count")
        store.save_analysis(session_id, fid, analysis)
        store.update_file(session_id, fid, analysis_summary=analysis.get("summary", {}))
        updated.append({"file_id": fid, "file_name": record.get("original_name"), "qc": {
            "overall": qc.get("overall"), "errors": qc.get("error_count"),
            "warnings": qc.get("warning_count"), "information": qc.get("information_count"),
        }})
    return {"updated": updated, "thresholds": thresholds, "session": _session_payload(_session(session_id))}


# --------------------------------------------------------------------- reports
@app.post("/api/sessions/{session_id}/reports")
def generate_report(session_id: str, body: ReportRequest) -> Response:
    session = _session(session_id)
    analyses, _records = _report_analyses(session_id, session, body.file_ids)
    if not analyses:
        raise HTTPException(status_code=400, detail="No analysed files selected")
    comparison = _build_comparison(session, analyses, body)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    base = f"audio-analysis-{session_id[:8]}-{stamp}"
    fmt = body.format
    try:
        if fmt == "pdf":
            content = build_pdf(session, analyses, comparison, session.get("settings", {}).get("qc_thresholds"))
            media = "application/pdf"
            filename = f"{base}.pdf"
        elif fmt == "json":
            content = build_json_report(session, analyses, comparison, session.get("settings", {}).get("qc_thresholds"))
            content = content.encode("utf-8")
            media = "application/json; charset=utf-8"
            filename = f"{base}.json"
        elif fmt == "csv":
            content = ("\ufeff" + build_csv(analyses)).encode("utf-8")
            media = "text/csv; charset=utf-8"
            filename = f"{base}-measurements.csv"
        elif fmt == "qc-csv":
            content = ("\ufeff" + build_qc_csv(analyses)).encode("utf-8")
            media = "text/csv; charset=utf-8"
            filename = f"{base}-qc-findings.csv"
        elif fmt == "comparison-csv":
            if comparison is None:
                raise HTTPException(status_code=400, detail="Comparison requires at least two analysed files and include_comparison=true")
            content = ("\ufeff" + build_comparison_csv(comparison)).encode("utf-8")
            media = "text/csv; charset=utf-8"
            filename = f"{base}-comparison.csv"
        else:
            raise HTTPException(status_code=400, detail="Unsupported report format")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Report generation failed")
        raise HTTPException(status_code=500, detail=f"Report generation failed: {exc}")
    return Response(
        content=content,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"},
    )


@app.get("/api/sessions/{session_id}/files/{file_id}/plots/{kind}.png")
def file_plot(
    session_id: str,
    file_id: str,
    kind: str,
    width: float = Query(default=12.0, ge=5.0, le=22.0),
    height: float = Query(default=4.0, ge=2.0, le=12.0),
    log: bool = Query(default=False),
    start: float | None = Query(default=None, ge=0),
    end: float | None = Query(default=None, gt=0),
) -> Response:
    if kind not in PLOT_BUILDERS:
        raise HTTPException(status_code=404, detail=f"Unknown plot type. Available: {', '.join(sorted(PLOT_BUILDERS))}")
    analysis = _analysis_or_404(session_id, file_id)
    kwargs: dict[str, Any] = {"width": width, "height": height}
    if kind == "waveform":
        kwargs["start"] = start
        kwargs["end"] = end
    elif kind == "spectrum":
        kwargs["log_scale"] = log
    elif kind == "spectrogram":
        kwargs["log_frequency"] = log
    try:
        content = render_plot(kind, analysis, **kwargs)
    except Exception as exc:
        logger.exception("Plot rendering failed")
        raise HTTPException(status_code=500, detail=f"Plot rendering failed: {exc}")
    filename = f"{safe_display_name(analysis.get('original_name', 'audio'))}-{kind}.png"
    return Response(
        content=content, media_type="image/png",
        headers={"Content-Disposition": _content_disposition("inline", filename), "Cache-Control": "no-store"},
    )


@app.get("/api/sessions/{session_id}/plots/comparison/{kind}.png")
def comparison_plot(
    session_id: str,
    kind: str,
    file_ids: str = Query(..., description="Comma-separated file IDs"),
    width: float = Query(default=12.0, ge=5.0, le=22.0),
    height: float = Query(default=4.2, ge=2.0, le=12.0),
) -> Response:
    session = _session(session_id)
    ids = [value for value in file_ids.split(",") if value]
    analyses = []
    for fid in ids:
        if fid not in session.get("files", {}):
            raise HTTPException(status_code=404, detail=f"File not found: {fid}")
        analysis = store.load_analysis(session_id, fid)
        if analysis is None:
            raise HTTPException(status_code=400, detail=f"Analysis not available for {fid}")
        analyses.append(analysis)
    builders = {
        "bands": plot_comparison_bands,
        "loudness": plot_comparison_loudness,
        "spectrum": plot_comparison_spectrum,
    }
    builder = builders.get(kind)
    if not builder:
        raise HTTPException(status_code=404, detail="Comparison plot must be bands, loudness or spectrum")
    try:
        content = builder(analyses, width=width, height=height)
    except Exception as exc:
        logger.exception("Comparison plot failed")
        raise HTTPException(status_code=500, detail=f"Comparison plot failed: {exc}")
    return Response(
        content=content, media_type="image/png",
        headers={"Content-Disposition": f'inline; filename="comparison-{kind}.png"', "Cache-Control": "no-store"},
    )


# ---------------------------------------------------------------------- static
frontend_dist = settings.frontend_dist
assets_dir = frontend_dist / "assets"
if assets_dir.exists():
    app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")


@app.get("/{full_path:path}", include_in_schema=False)
def serve_frontend(full_path: str):
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="API route not found")
    index = frontend_dist / "index.html"
    if not index.exists():
        return JSONResponse({
            "message": "Audio Analysis Pipeline API is running. Build the frontend (npm run build) or run the Vite dev server.",
            "docs": "/api/docs",
            "health": "/api/health",
        })
    candidate = (frontend_dist / full_path).resolve()
    try:
        candidate.relative_to(frontend_dist.resolve())
    except ValueError:
        raise HTTPException(status_code=404, detail="Not found")
    if full_path and candidate.is_file():
        return FileResponse(candidate)
    return FileResponse(index, media_type="text/html")
