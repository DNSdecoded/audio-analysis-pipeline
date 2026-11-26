"""Dynamic-range and compression analysis."""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from .utils import merge_regions, round_sig


def _window_lra(times: np.ndarray, lufs: np.ndarray, duration: float, window: float = 15.0, step: float = 5.0) -> list[dict[str, Any]]:
    if lufs.size < 4 or duration < window:
        return []
    result = []
    start = 0.0
    while start + window <= duration + 1e-9:
        mask = (times >= start) & (times < start + window)
        values = lufs[mask]
        values = values[np.isfinite(values) & (values > -70.0)]
        if values.size >= 4:
            local = float(np.percentile(values, 95) - np.percentile(values, 10))
            result.append({
                "start": round_sig(start, 2),
                "end": round_sig(start + window, 2),
                "local_lra_lu": round_sig(local, 2),
                "median_lufs": round_sig(float(np.median(values)), 2),
            })
        start += step
    return result


def analyze_dynamics(
    loudness: dict[str, Any],
    time_domain: dict[str, Any],
    duration: float,
    rhythm: dict[str, Any] | None = None,
) -> dict[str, Any]:
    lra = loudness.get("loudness_range_lu")
    crest = loudness.get("crest_factor_db")
    plr = loudness.get("peak_to_loudness_ratio_db")
    short_term = loudness.get("short_term", {})
    st_lufs = np.asarray(short_term.get("lufs", []), dtype=np.float64)
    st_times = np.asarray(short_term.get("times", []), dtype=np.float64)
    momentary = loudness.get("momentary", {})
    mo_lufs = np.asarray(momentary.get("lufs", []), dtype=np.float64)
    mo_times = np.asarray(momentary.get("times", []), dtype=np.float64)

    # Only blocks above the BS.1770 absolute gate (-70 LUFS) describe programme
    # dynamics; digital-silence blocks are null and are excluded.
    st_valid = st_lufs[np.isfinite(st_lufs) & (st_lufs > -70.0)]
    st_std = float(np.std(st_valid)) if st_valid.size else 0.0
    st_p5 = float(np.percentile(st_valid, 5)) if st_valid.size else None
    st_p95 = float(np.percentile(st_valid, 95)) if st_valid.size else None
    st_range = (st_p95 - st_p5) if st_p5 is not None and st_p95 is not None else None

    rms_series = np.asarray(time_domain.get("envelopes", {}).get("rms_db", []), dtype=np.float64)
    peak_series = np.asarray(time_domain.get("envelopes", {}).get("peak_db", []), dtype=np.float64)
    env_times = np.asarray(time_domain.get("envelopes", {}).get("times", []), dtype=np.float64)
    crest_series = peak_series - rms_series if rms_series.size == peak_series.size else np.array([])
    crest_median = float(np.median(crest_series[np.isfinite(crest_series)])) if crest_series.size else crest

    transient = {}
    if rhythm:
        strengths = np.asarray(rhythm.get("onset_strengths", []), dtype=np.float64)
        strengths = strengths[np.isfinite(strengths)]
        if strengths.size:
            positive = strengths[strengths > 0]
            transient = {
                "supported": True,
                "onset_count": int(rhythm.get("onset_count", strengths.size)),
                "strength_mean": round_sig(float(np.mean(strengths)), 4),
                "strength_p95": round_sig(float(np.percentile(strengths, 95)), 4),
                "strength_max": round_sig(float(np.max(strengths)), 4),
                "strength_median": round_sig(float(np.median(strengths)), 4),
                "peak_to_median_ratio": round_sig(float(np.percentile(strengths, 95)) / max(float(np.median(positive)) if positive.size else 1e-9, 1e-9), 3),
                "transient_density_per_second": rhythm.get("onset_density_per_second"),
                "method": "Onset-strength envelope (positive spectral flux) at detected onset frames; values are normalised to the maximum of the envelope.",
            }
        else:
            transient = {"supported": False, "reason": "No onsets detected"}
    else:
        transient = {"supported": False, "reason": "Rhythm analysis not available"}

    indicators = []
    if lra is not None and lra < 4.0:
        indicators.append({
            "type": "low_loudness_range",
            "severity": "info",
            "message": f"Loudness range is {lra:.2f} LU, indicating a narrow loudness envelope.",
            "measurement": {"lra_lu": lra},
            "threshold": 4.0,
            "recommendation": "If the material is intended to be dynamic, review limiting and compression. Low LRA can also be appropriate for dense, consistently loud genres.",
        })
    if plr is not None and plr < 8.0:
        indicators.append({
            "type": "low_peak_to_loudness_ratio",
            "severity": "info",
            "message": f"Peak-to-loudness ratio is {plr:.2f} dB.",
            "measurement": {"plr_db": plr},
            "threshold": 8.0,
            "recommendation": "The peaks sit close to the integrated loudness; check limiter gain reduction and transient preservation.",
        })
    if crest is not None and crest < 6.0:
        indicators.append({
            "type": "low_crest_factor",
            "severity": "info",
            "message": f"Crest factor is {crest:.2f} dB.",
            "measurement": {"crest_factor_db": crest},
            "threshold": 6.0,
            "recommendation": "Low crest factor suggests heavy limiting or compression; audition transient attack and compare with the uncompressed source if available.",
        })
    if st_std < 1.5 and st_valid.size > 10:
        indicators.append({
            "type": "consistent_loudness",
            "severity": "info",
            "message": f"Short-term loudness standard deviation is {st_std:.2f} LU.",
            "measurement": {"short_term_std_lu": round_sig(st_std, 2)},
            "threshold": 1.5,
            "recommendation": "Consistent loudness is often intentional in modern masters; verify that musical dynamics remain expressive.",
        })
    if lra is not None and lra > 20.0:
        indicators.append({
            "type": "wide_loudness_range",
            "severity": "info",
            "message": f"Loudness range is {lra:.2f} LU.",
            "measurement": {"lra_lu": lra},
            "threshold": 20.0,
            "recommendation": "Check whether the loudness variation matches the arrangement and delivery target; very wide ranges may need level automation.",
        })

    reduced_sections = []
    if st_lufs.size and lra is not None and lra > 4.0:
        windows = _window_lra(st_times, st_lufs, duration, window=15.0, step=5.0)
        low = [w for w in windows if w["local_lra_lu"] < 2.5]
        if low:
            merged = merge_regions([(w["start"], w["end"]) for w in low], gap=2.0)
            for region in merged:
                vals = [
                    w["local_lra_lu"] for w in low
                    if w["start"] >= region["start"] - 1e-6 and w["end"] <= region["end"] + 1e-6
                ]
                if vals:
                    reduced_sections.append({
                        "start": region["start"],
                        "end": region["end"],
                        "local_lra_lu": round_sig(min(vals), 2),
                        "note": "Short-term loudness range inside this section is low relative to the full-file range.",
                    })
    if crest_series.size and env_times.size == crest_series.size and crest is not None and crest > 8.0:
        window_seconds = 10.0
        step = 5.0
        low_windows = []
        start = 0.0
        while start + window_seconds <= duration + 1e-9:
            mask = (env_times >= start) & (env_times < start + window_seconds)
            values = crest_series[mask]
            values = values[np.isfinite(values)]
            if values.size >= 4:
                local_crest = float(np.percentile(values, 95) - np.percentile(values, 25))
                if local_crest < 5.0:
                    low_windows.append((start, start + window_seconds, local_crest))
            start += step
        if low_windows:
            merged = merge_regions([(a, b) for a, b, _ in low_windows], gap=2.0)
            for region in merged:
                vals = [c for a, b, c in low_windows if a >= region["start"] - 1e-6 and b <= region["end"] + 1e-6]
                if vals:
                    reduced_sections.append({
                        "start": region["start"],
                        "end": region["end"],
                        "local_crest_db": round_sig(min(vals), 2),
                        "note": "Peak-to-RMS range inside this section is low; dynamics may be compressed.",
                    })
    reduced_sections = reduced_sections[:50]

    return {
        "dynamic_range_db": round_sig(crest, 2),
        "dynamic_range_definition": "Reported as peak-to-RMS crest factor in dB; loudness range (LRA) is reported separately in LU.",
        "crest_factor_db": round_sig(crest, 2),
        "peak_to_loudness_ratio_db": round_sig(plr, 2),
        "loudness_range_lu": round_sig(lra, 2),
        "rms_variation_db": time_domain.get("signal_variation", {}).get("rms_std_db"),
        "rms_range_db": time_domain.get("signal_variation", {}).get("rms_range_db"),
        "short_term_dynamic_variation_lu": round_sig(st_std, 2),
        "short_term_range_lu": round_sig(st_range, 2) if st_range is not None else None,
        "short_term_p5_lufs": round_sig(st_p5, 2) if st_p5 is not None else None,
        "short_term_p95_lufs": round_sig(st_p95, 2) if st_p95 is not None else None,
        "crest_factor_median_db": round_sig(crest_median, 2),
        "transient_strength": transient,
        "compression_indicators": indicators,
        "reduced_dynamic_sections": reduced_sections,
        "timeline": {
            "times": [round_sig(v, 3) for v in env_times.tolist()],
            "rms_db": [round_sig(v, 2) for v in rms_series.tolist()],
            "peak_db": [round_sig(v, 2) for v in peak_series.tolist()],
            "crest_db": [round_sig(v, 2) for v in crest_series.tolist()],
            "short_term_lufs": {
                "times": [round_sig(v, 3) for v in st_times.tolist()],
                "values": [round_sig(v, 2) for v in st_lufs.tolist()],
            },
        },
        "method": "Crest factor = sample peak minus RMS. LRA from EBU Tech 3342. Short-term variation uses 3 s K-weighted blocks. Reduced-dynamics sections are identified by a local 15 s loudness range below 2.5 LU or a local crest range below 5 dB; these are observations, not defects.",
        "confidence": loudness.get("confidence", "medium"),
    }
