"""Shared DSP helpers used by the analysis modules."""

from __future__ import annotations

import math
from typing import Any, Iterable

import numpy as np

EPS = 1e-12


def db(value: float, floor: float = -160.0, amplitude: bool = True) -> float:
    """Convert linear amplitude (or power when amplitude=False) to dB."""
    if value is None:
        return floor
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        return floor
    factor = 20.0 if amplitude else 10.0
    return max(floor, factor * math.log10(value))


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def round_sig(value: Any, digits: int = 4) -> Any:
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return value
    if not math.isfinite(value):
        return None
    if value == 0:
        return 0.0
    return round(value, digits)


def downsample_envelope(values: np.ndarray, max_points: int) -> np.ndarray:
    """Aggregate a 1-D series into at most max_points buckets using the mean."""
    values = np.asarray(values, dtype=np.float64)
    if values.size <= max_points:
        return values
    edges = np.linspace(0, values.size, max_points + 1).astype(int)
    out = np.empty(max_points, dtype=np.float64)
    for i in range(max_points):
        a, b = edges[i], max(edges[i + 1], edges[i] + 1)
        out[i] = float(np.nanmean(values[a:b])) if b > a else 0.0
    return out


def downsample_minmax(values: np.ndarray, max_points: int) -> tuple[np.ndarray, np.ndarray]:
    values = np.asarray(values, dtype=np.float64)
    if values.size <= max_points:
        return values.copy(), values.copy()
    edges = np.linspace(0, values.size, max_points + 1).astype(int)
    mins = np.empty(max_points)
    maxs = np.empty(max_points)
    for i in range(max_points):
        a, b = edges[i], max(edges[i + 1], edges[i] + 1)
        segment = values[a:b]
        mins[i] = float(np.min(segment))
        maxs[i] = float(np.max(segment))
    return mins, maxs


def downsample_2d(matrix: np.ndarray, max_cols: int, max_rows: int | None = None) -> np.ndarray:
    """Downsample a (rows, cols) matrix by block averaging."""
    matrix = np.asarray(matrix)
    if matrix.ndim != 2:
        raise ValueError("Expected a 2-D matrix")
    rows, cols = matrix.shape
    if cols > max_cols:
        edges = np.linspace(0, cols, max_cols + 1).astype(int)
        reduced = np.empty((rows, max_cols), dtype=np.float64)
        for i in range(max_cols):
            a, b = edges[i], max(edges[i + 1], edges[i] + 1)
            reduced[:, i] = np.mean(matrix[:, a:b], axis=1)
        matrix = reduced
        cols = max_cols
    if max_rows and rows > max_rows:
        edges = np.linspace(0, rows, max_rows + 1).astype(int)
        reduced = np.empty((max_rows, cols), dtype=np.float64)
        for i in range(max_rows):
            a, b = edges[i], max(edges[i + 1], edges[i] + 1)
            reduced[i, :] = np.mean(matrix[a:b, :], axis=0)
        matrix = reduced
    return np.asarray(matrix, dtype=np.float64)


def downsample_series_minmax(values: np.ndarray, max_points: int) -> tuple[np.ndarray, np.ndarray]:
    return downsample_minmax(values, max_points)


def merge_regions(regions: Iterable[tuple[float, float]], gap: float = 0.05) -> list[dict[str, float]]:
    """Merge overlapping/adjacent (start, end) regions."""
    ordered = sorted((max(0.0, float(a)), max(0.0, float(b))) for a, b in regions if b > a)
    if not ordered:
        return []
    merged: list[list[float]] = [[ordered[0][0], ordered[0][1]]]
    for start, end in ordered[1:]:
        if start <= merged[-1][1] + gap:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [{"start": round(a, 4), "end": round(b, 4), "duration": round(b - a, 4)} for a, b in merged]


def regions_from_mask(times: np.ndarray, mask: np.ndarray, gap: float = 0.05) -> list[dict[str, float]]:
    if len(times) == 0:
        return []
    regions = []
    in_region = False
    start = 0.0
    for i, flag in enumerate(mask):
        if flag and not in_region:
            start = float(times[i])
            in_region = True
        elif not flag and in_region:
            end = float(times[i])
            regions.append((start, end))
            in_region = False
    if in_region:
        dt = float(times[-1] - times[-2]) if len(times) > 1 else 0.0
        regions.append((start, float(times[-1]) + dt))
    return merge_regions(regions, gap)


def percentile(values: np.ndarray, q: float, default: float = 0.0) -> float:
    values = np.asarray(values, dtype=np.float64)
    values = values[np.isfinite(values)]
    if values.size == 0:
        return default
    return float(np.percentile(values, q))


def linspace_times(n: int, duration: float) -> list[float]:
    if n <= 0:
        return []
    if n == 1:
        return [0.0]
    return [round(float(x), 4) for x in np.linspace(0, duration, n)]


def human_duration(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(int(minutes), 60)
    if hours:
        return f"{hours}:{minutes:02d}:{sec:05.2f}"
    return f"{int(minutes)}:{sec:05.2f}"


def to_jsonable(value: Any) -> Any:
    """Recursively convert NumPy scalars/arrays and non-finite floats."""
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    if isinstance(value, np.ndarray):
        return to_jsonable(value.tolist())
    if isinstance(value, np.generic):
        return to_jsonable(value.item())
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return value

