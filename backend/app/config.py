"""Application configuration.

All limits are configurable through environment variables so deployments can
tighten or relax resource usage without code changes.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_list(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    """Comma-separated environment list; unset/blank falls back to ``default``."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    items = tuple(item.strip() for item in raw.split(",") if item.strip())
    return items or default


@dataclass(frozen=True)
class Settings:
    data_dir: Path = field(
        default_factory=lambda: Path(os.environ.get("AAP_DATA_DIR", str(BASE_DIR / "data")))
    )
    frontend_dist: Path = field(
        default_factory=lambda: Path(
            os.environ.get("AAP_FRONTEND_DIST", str(BASE_DIR / "frontend" / "dist"))
        )
    )

    max_file_size_mb: int = field(default_factory=lambda: _env_int("AAP_MAX_FILE_MB", 300))
    max_duration_seconds: float = field(
        default_factory=lambda: _env_float("AAP_MAX_DURATION_SECONDS", 1200.0)
    )
    max_files_per_session: int = field(
        default_factory=lambda: _env_int("AAP_MAX_FILES_PER_SESSION", 12)
    )
    max_concurrent_jobs: int = field(
        default_factory=lambda: max(1, _env_int("AAP_MAX_CONCURRENT_JOBS", 2))
    )
    session_ttl_hours: float = field(
        default_factory=lambda: _env_float("AAP_SESSION_TTL_HOURS", 12.0)
    )
    cleanup_interval_seconds: int = field(
        default_factory=lambda: _env_int("AAP_CLEANUP_INTERVAL_SECONDS", 600)
    )

    default_target_lufs: float = -14.0
    default_true_peak_limit: float = -1.0
    default_fft_size: int = 4096
    default_hop_length: int = 1024

    # Analysis work limits.  These protect memory on long files.
    max_spectrogram_frames: int = 320
    max_feature_points: int = 1200
    max_waveform_buckets: int = 4000
    pitch_analysis_seconds: float = 30.0
    hpss_analysis_seconds: float = 120.0

    allowed_extensions: tuple[str, ...] = (
        ".wav", ".wave", ".mp3", ".flac", ".aac", ".ogg", ".oga",
        ".aiff", ".aif", ".aifc", ".m4a", ".mp4",
    )

    # Dev-server origins allowed to call the API. Override with
    # AAP_CORS_ORIGINS="https://one.example,https://two.example" when the
    # frontend is served from a different host or port.
    cors_origins: tuple[str, ...] = field(
        default_factory=lambda: _env_list(
            "AAP_CORS_ORIGINS",
            (
                "http://localhost:5173",
                "http://127.0.0.1:5173",
                "http://localhost:4173",
                "http://127.0.0.1:4173",
            ),
        )
    )

    @property
    def sessions_dir(self) -> Path:
        return self.data_dir / "sessions"

    @property
    def temp_dir(self) -> Path:
        return self.data_dir / "tmp"

    def ensure_dirs(self) -> None:
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_dirs()

SUPPORTED_FORMATS = {
    ".wav": "WAV",
    ".wave": "WAV",
    ".mp3": "MP3",
    ".flac": "FLAC",
    ".aac": "AAC",
    ".ogg": "OGG",
    ".oga": "OGG",
    ".aiff": "AIFF",
    ".aif": "AIFF",
    ".aifc": "AIFF-C",
    ".m4a": "MP4/AAC",
    ".mp4": "MP4/AAC",
}
