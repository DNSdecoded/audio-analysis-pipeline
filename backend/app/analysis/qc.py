"""Automated quality control with configurable, explicit thresholds."""

from __future__ import annotations

import math
from typing import Any

from .utils import round_sig

SEVERITY_ORDER = {"normal": 0, "information": 1, "warning": 2, "error": 3}

DEFAULT_THRESHOLDS: dict[str, float | list[int]] = {
    "clipping_percent_warning": 0.005,
    "clipping_percent_error": 0.05,
    "true_peak_warning_dbtp": -1.0,
    "true_peak_error_dbtp": 0.0,
    "loudness_min_lufs": -30.0,
    "loudness_max_lufs": -6.0,
    "lra_min_lu": 2.0,
    "lra_max_lu": 25.0,
    "noise_floor_warning_dbfs": -55.0,
    "noise_floor_error_dbfs": -40.0,
    "snr_warning_db": 30.0,
    "dc_offset_warning": 0.005,
    "silence_percent_warning": 30.0,
    "silence_percent_error": 95.0,
    "correlation_warning": -0.1,
    "correlation_error": -0.5,
    "channel_imbalance_warning_db": 1.5,
    "channel_imbalance_error_db": 6.0,
    "dropout_warning_count": 1.0,
    "crest_factor_warning_db": 6.0,
    "bit_depth_warning_bits": 16.0,
    "common_sample_rates": [8000, 11025, 16000, 22050, 32000, 44100, 48000, 88200, 96000, 176400, 192000],
}

THRESHOLD_SCHEMA = [
    {"key": "clipping_percent_warning", "label": "Clipping warning (%)", "unit": "%", "min": 0.0, "max": 10.0, "step": 0.001},
    {"key": "clipping_percent_error", "label": "Clipping error (%)", "unit": "%", "min": 0.0, "max": 20.0, "step": 0.01},
    {"key": "true_peak_warning_dbtp", "label": "True peak warning", "unit": "dBTP", "min": -12.0, "max": 6.0, "step": 0.1},
    {"key": "true_peak_error_dbtp", "label": "True peak error", "unit": "dBTP", "min": -6.0, "max": 6.0, "step": 0.1},
    {"key": "loudness_min_lufs", "label": "Minimum integrated loudness", "unit": "LUFS", "min": -60.0, "max": -3.0, "step": 0.5},
    {"key": "loudness_max_lufs", "label": "Maximum integrated loudness", "unit": "LUFS", "min": -40.0, "max": 0.0, "step": 0.5},
    {"key": "lra_min_lu", "label": "Minimum loudness range", "unit": "LU", "min": 0.0, "max": 20.0, "step": 0.1},
    {"key": "lra_max_lu", "label": "Maximum loudness range", "unit": "LU", "min": 1.0, "max": 60.0, "step": 0.5},
    {"key": "noise_floor_warning_dbfs", "label": "Noise floor warning", "unit": "dBFS", "min": -120.0, "max": -20.0, "step": 1.0},
    {"key": "noise_floor_error_dbfs", "label": "Noise floor error", "unit": "dBFS", "min": -100.0, "max": -10.0, "step": 1.0},
    {"key": "snr_warning_db", "label": "SNR warning", "unit": "dB", "min": 0.0, "max": 100.0, "step": 1.0},
    {"key": "dc_offset_warning", "label": "DC offset warning", "unit": "linear", "min": 0.0, "max": 0.2, "step": 0.0005},
    {"key": "silence_percent_warning", "label": "Silence warning", "unit": "%", "min": 0.0, "max": 100.0, "step": 1.0},
    {"key": "silence_percent_error", "label": "Silence error", "unit": "%", "min": 0.0, "max": 100.0, "step": 1.0},
    {"key": "correlation_warning", "label": "Correlation warning", "unit": "r", "min": -1.0, "max": 1.0, "step": 0.05},
    {"key": "correlation_error", "label": "Correlation error", "unit": "r", "min": -1.0, "max": 1.0, "step": 0.05},
    {"key": "channel_imbalance_warning_db", "label": "Channel imbalance warning", "unit": "dB", "min": 0.0, "max": 20.0, "step": 0.1},
    {"key": "channel_imbalance_error_db", "label": "Channel imbalance error", "unit": "dB", "min": 0.0, "max": 30.0, "step": 0.5},
    {"key": "dropout_warning_count", "label": "Dropout warning count", "unit": "regions", "min": 0.0, "max": 100.0, "step": 1.0},
    {"key": "crest_factor_warning_db", "label": "Crest factor warning", "unit": "dB", "min": 0.0, "max": 30.0, "step": 0.5},
    {"key": "bit_depth_warning_bits", "label": "Minimum bit depth warning", "unit": "bits", "min": 8.0, "max": 32.0, "step": 1.0},
]


def merge_thresholds(overrides: dict[str, Any] | None) -> dict[str, Any]:
    thresholds = dict(DEFAULT_THRESHOLDS)
    if overrides:
        for key, value in overrides.items():
            if key not in DEFAULT_THRESHOLDS:
                continue
            if key == "common_sample_rates":
                if isinstance(value, (list, tuple)):
                    parsed = set()
                    for item in value:
                        try:
                            rate = int(float(item))
                        except (TypeError, ValueError, OverflowError):
                            continue
                        if 8000 <= rate <= 384000:
                            parsed.add(rate)
                    rates = sorted(parsed)
                    if rates:
                        thresholds[key] = rates
                continue
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(number):
                thresholds[key] = number
    if thresholds["clipping_percent_error"] < thresholds["clipping_percent_warning"]:
        thresholds["clipping_percent_error"] = thresholds["clipping_percent_warning"]
    if thresholds["noise_floor_error_dbfs"] < thresholds["noise_floor_warning_dbfs"]:
        thresholds["noise_floor_error_dbfs"] = thresholds["noise_floor_warning_dbfs"]
    if thresholds["silence_percent_error"] < thresholds["silence_percent_warning"]:
        thresholds["silence_percent_error"] = thresholds["silence_percent_warning"]
    if thresholds["channel_imbalance_error_db"] < thresholds["channel_imbalance_warning_db"]:
        thresholds["channel_imbalance_error_db"] = thresholds["channel_imbalance_warning_db"]
    if thresholds["true_peak_error_dbtp"] < thresholds["true_peak_warning_dbtp"]:
        thresholds["true_peak_error_dbtp"] = thresholds["true_peak_warning_dbtp"]
    return thresholds


def _check(
    check_id: str,
    category: str,
    title: str,
    severity: str,
    message: str,
    explanation: str,
    recommendation: str,
    measured: Any = None,
    unit: str | None = None,
    threshold: Any = None,
    threshold_unit: str | None = None,
    time_positions: list[dict[str, Any]] | None = None,
    confidence: str = "high",
    standard: str | None = None,
) -> dict[str, Any]:
    severity = severity if severity in SEVERITY_ORDER else "information"
    return {
        "id": check_id,
        "category": category,
        "title": title,
        "severity": severity,
        "status_label": severity.capitalize(),
        "message": message,
        "explanation": explanation,
        "recommendation": recommendation,
        "measured_value": measured,
        "measured_unit": unit,
        "threshold_value": threshold,
        "threshold_unit": threshold_unit,
        "time_positions": time_positions or [],
        "confidence": confidence,
        "standard": standard,
    }


# Checks whose severity can come from an *error* threshold.  `threshold_value`
# on a check holds the warning limit (kept for API compatibility); reports must
# show the error limit when that is the one that was crossed.
ERROR_LIMITS: dict[str, tuple[str, str, str]] = {
    # check id: (error threshold key, unit, comparison)
    "clipping": ("clipping_percent_error", "%", ">="),
    "true_peak": ("true_peak_error_dbtp", "dBTP", ">="),
    "noise": ("noise_floor_error_dbfs", "dBFS", ">="),
    "silence": ("silence_percent_error", "%", ">="),
    "correlation": ("correlation_error", "r", "<="),
    "channel_imbalance": ("channel_imbalance_error_db", "dB", ">="),
}


def _num_text(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return str(value)
    return f"{value:g}"


def describe_limit(check: dict[str, Any], thresholds: dict[str, Any] | None = None) -> str:
    """Human-readable limit for one check, naming the limit that was crossed.

    For an error-severity check with a separate error threshold the result is
    e.g. ``critical >= 0.05 % (warning >= 0.005 %)``.
    """
    value = check.get("threshold_value")
    unit = (check.get("threshold_unit") or "").strip()
    error = ERROR_LIMITS.get(str(check.get("id")))
    error_value = check.get("error_threshold_value")
    if error_value is None and error and thresholds:
        error_value = thresholds.get(error[0])
    if check.get("severity") == "error" and error and isinstance(error_value, (int, float)):
        _key, err_unit, op = error
        warn = f" (warning {op} {_num_text(value)} {err_unit})" if isinstance(value, (int, float)) else ""
        return f"critical {op} {_num_text(error_value)} {err_unit}{warn}"
    if value is None:
        return ""
    if isinstance(value, list):
        if len(value) == 2 and all(isinstance(v, (int, float)) for v in value):
            return f"{_num_text(value[0])} to {_num_text(value[1])} {unit.replace(' range', '')}".strip()
        shown = ", ".join(_num_text(v) for v in value[:8])
        return f"{shown}{'…' if len(value) > 8 else ''} {unit}".strip()
    return f"{_num_text(value)} {unit}".strip()


def analyze_qc(analysis: dict[str, Any], overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    thresholds = merge_thresholds(overrides)
    td = analysis.get("time_domain", {})
    loud = analysis.get("loudness", {})
    stereo = analysis.get("stereo", {})
    spectral = analysis.get("spectral", {})
    musical = analysis.get("musical", {})
    dynamics = analysis.get("dynamics", {})
    meta = analysis.get("metadata", {})
    validation = analysis.get("validation", {})
    checks: list[dict[str, Any]] = []

    # File integrity / validation warnings.
    if validation.get("errors"):
        checks.append(_check(
            "integrity", "Integrity", "File integrity", "error",
            "The file failed structural validation.",
            "; ".join(validation.get("errors", [])),
            "Re-export the file from the source application and upload the new copy.",
            time_positions=[], confidence="high",
        ))
    elif validation.get("warnings"):
        checks.append(_check(
            "integrity_warnings", "Integrity", "File integrity", "information",
            "Structural warnings were reported during validation.",
            "; ".join(validation.get("warnings", [])),
            "Verify the file plays completely in a reference player before using it for delivery.",
            time_positions=[], confidence="medium",
        ))
    else:
        checks.append(_check(
            "integrity_ok", "Integrity", "File integrity", "normal",
            "Container structure and decoder probe passed.",
            "The file signature matches its extension and no truncation indicators were found.",
            "No action required.", confidence="high",
        ))

    # Clipping
    clipping = td.get("clipping", {})
    clip_pct = float(clipping.get("clipped_percent", 0.0) or 0.0)
    clip_regions = clipping.get("regions", [])
    if clip_pct >= thresholds["clipping_percent_error"]:
        severity = "error"
    elif clip_pct >= thresholds["clipping_percent_warning"]:
        severity = "warning"
    elif clip_pct > 0:
        severity = "information"
    else:
        severity = "normal"
    checks.append(_check(
        "clipping", "Signal quality", "Clipping", severity,
        f"{clip_pct:.4f}% of samples reach the clipping threshold ({clipping.get('threshold_dbfs', -0.1)} dBFS).",
        "Clipped waveforms lose peaks and add harmonic distortion. The percentage is calculated from sample-level threshold crossings; flat-top samples indicate hard clipping.",
        "Reduce gain before the clipper/limiter, or restore the unclipped source. Re-export with at least 1 dB of headroom.",
        measured=round_sig(clip_pct, 4), unit="%",
        threshold=round_sig(thresholds["clipping_percent_warning"], 4), threshold_unit="% warning",
        time_positions=clip_regions[:50], confidence="high",
        standard="Sample threshold -0.1 dBFS (configurable analysis setting)",
    ))

    # True peak.  0.0 dBTP is a valid (and important) value, so test for None
    # explicitly instead of using a falsy fallback.
    true_peak_raw = loud.get("true_peak_dbtp")
    if true_peak_raw is None:
        checks.append(_check(
            "true_peak", "Signal quality", "True peak", "information",
            "True peak could not be measured.",
            "No true-peak value is available for this file, so no value is reported.",
            "Re-run the analysis; if the problem persists, check that the file decodes completely.",
            measured=None, unit="dBTP", confidence="unavailable",
            standard="ITU-R BS.1770-4 Annex 2 (4x oversampling)",
        ))
    else:
        true_peak = float(true_peak_raw)
        if true_peak > thresholds["true_peak_error_dbtp"]:
            severity = "error"
        elif true_peak > thresholds["true_peak_warning_dbtp"]:
            severity = "warning"
        else:
            severity = "normal"
        checks.append(_check(
            "true_peak", "Signal quality", "True peak", severity,
            f"True peak is {true_peak:.2f} dBTP.",
            "True peak is estimated with 4x oversampling. Levels above 0 dBTP can clip during D/A conversion even when sample peaks are below full scale.",
            "Lower the final limiter ceiling or reduce output gain. Leave at least the configured true-peak margin for the delivery target.",
            measured=round_sig(true_peak, 2), unit="dBTP",
            threshold=round_sig(thresholds["true_peak_warning_dbtp"], 2), threshold_unit="dBTP warning",
            confidence="high", standard="ITU-R BS.1770-4 Annex 2 (4x oversampling)",
        ))

    # Integrated loudness
    integrated = loud.get("integrated_lufs")
    if integrated is None:
        checks.append(_check(
            "integrated_loudness", "Loudness", "Integrated loudness", "information",
            "Integrated loudness is not measurable: no 400 ms block exceeds the -70 LUFS absolute gate.",
            "BS.1770 defines integrated loudness only over gated blocks. The file is silent or extremely quiet, so no LUFS value is reported.",
            "Confirm that the file contains the intended programme material.",
            measured=None, unit="LUFS", confidence="high", standard="ITU-R BS.1770-4 / EBU R128",
        ))
    else:
        if integrated < thresholds["loudness_min_lufs"]:
            severity = "warning"
            message = f"Integrated loudness is {integrated:.2f} LUFS, below the configured minimum."
        elif integrated > thresholds["loudness_max_lufs"]:
            severity = "warning"
            message = f"Integrated loudness is {integrated:.2f} LUFS, above the configured maximum."
        else:
            severity = "normal"
            message = f"Integrated loudness is {integrated:.2f} LUFS."
        checks.append(_check(
            "integrated_loudness", "Loudness", "Integrated loudness", severity, message,
            "The configured range is a QC policy, not an absolute defect. Delivery targets vary by platform and genre.",
            "Confirm the intended delivery target before changing level. Use the track-gain preview; no processing is applied automatically.",
            measured=round_sig(integrated, 2), unit="LUFS",
            threshold=[thresholds["loudness_min_lufs"], thresholds["loudness_max_lufs"]], threshold_unit="LUFS range",
            confidence="high", standard="ITU-R BS.1770-4 / EBU R128",
        ))

    # Loudness range
    lra = loud.get("loudness_range_lu")
    if lra is not None:
        if lra < thresholds["lra_min_lu"]:
            severity = "information"
            message = f"Loudness range is {lra:.2f} LU, below the configured minimum."
        elif lra > thresholds["lra_max_lu"]:
            severity = "warning"
            message = f"Loudness range is {lra:.2f} LU, above the configured maximum."
        else:
            severity = "normal"
            message = f"Loudness range is {lra:.2f} LU."
        checks.append(_check(
            "loudness_range", "Dynamics", "Loudness range", severity, message,
            "LRA describes loudness variation, not artistic quality. Very low values suggest dense limiting; very high values may require level automation.",
            "Review the loudness timeline and dynamic-range plot. Decide whether the variation matches the arrangement and delivery context.",
            measured=round_sig(lra, 2), unit="LU",
            threshold=[thresholds["lra_min_lu"], thresholds["lra_max_lu"]], threshold_unit="LU range",
            confidence="high", standard="EBU Tech 3342",
        ))

    # Noise floor and SNR
    noise = td.get("noise", {})
    noise_floor_raw = noise.get("noise_floor_dbfs")
    snr_raw = noise.get("snr_db")
    if noise_floor_raw is None or snr_raw is None:
        checks.append(_check(
            "noise", "Signal quality", "Noise floor and SNR", "information",
            "A noise floor could not be separated from the signal.",
            "The file does not contain enough quiet material for a reliable noise-floor estimate. Reporting a value here would be misleading, so none is given.",
            "Inspect quiet sections manually. If noise is audible, identify its source before considering noise reduction.",
            measured=None, unit="dBFS", confidence="unavailable",
        ))
    else:
        noise_floor = float(noise_floor_raw)
        snr = float(snr_raw)
        if noise_floor > thresholds["noise_floor_error_dbfs"] or snr < thresholds["snr_warning_db"] / 2:
            severity = "error" if noise_floor > thresholds["noise_floor_error_dbfs"] else "warning"
            message = f"Noise floor is {noise_floor:.2f} dBFS with estimated SNR {snr:.2f} dB."
        elif noise_floor > thresholds["noise_floor_warning_dbfs"] or snr < thresholds["snr_warning_db"]:
            severity = "warning"
            message = f"Noise floor is {noise_floor:.2f} dBFS with estimated SNR {snr:.2f} dB."
        elif noise_floor > thresholds["noise_floor_warning_dbfs"] - 10:
            severity = "information"
            message = f"Noise floor is {noise_floor:.2f} dBFS with estimated SNR {snr:.2f} dB."
        else:
            severity = "normal"
            message = f"Noise floor is {noise_floor:.2f} dBFS with estimated SNR {snr:.2f} dB."
        checks.append(_check(
            "noise", "Signal quality", "Noise floor and SNR", severity, message,
            "The noise floor is the 10th percentile of audible 50 ms RMS frames when there is at least 6 dB of separation from the median level. Quiet passages can bias it downward. SNR compares overall RMS with that floor.",
            "Inspect quiet sections in the waveform view. If the noise is audible, identify the source (recording, processing, or dither) before applying noise reduction.",
            measured=round_sig(noise_floor, 2), unit="dBFS",
            threshold=round_sig(thresholds["noise_floor_warning_dbfs"], 2), threshold_unit="dBFS warning",
            confidence="medium", standard="Internal noise-floor estimate",
        ))

    # DC offset
    dc = td.get("dc_offset", {})
    dc_max = float(dc.get("max_abs", 0.0) or 0.0)
    severity = "warning" if dc_max > thresholds["dc_offset_warning"] else "normal"
    checks.append(_check(
        "dc_offset", "Signal quality", "DC offset", severity,
        f"Maximum absolute channel mean is {dc_max:.6f} ({dc.get('max_abs_dbfs', -160):.2f} dBFS).",
        "A non-zero mean wastes headroom and can cause clicks or thumps at edit points. The mean is measured over the full channel.",
        "Apply a DC-blocking high-pass only if the offset is audible or wastes headroom; preserve the original file.",
        measured=round_sig(dc_max, 6), unit="linear",
        threshold=round_sig(thresholds["dc_offset_warning"], 6), threshold_unit="linear warning",
        confidence="high",
    ))

    # Silence
    silence = td.get("silence", {})
    silence_pct = float(silence.get("percent", 0.0) or 0.0)
    silence_regions = silence.get("regions", [])
    if silence_pct >= thresholds["silence_percent_error"]:
        severity = "error"
    elif silence_pct >= thresholds["silence_percent_warning"]:
        severity = "warning"
    elif silence_regions:
        severity = "information"
    else:
        severity = "normal"
    checks.append(_check(
        "silence", "Signal quality", "Silence", severity,
        f"{silence_pct:.2f}% of the duration is below {silence.get('threshold_dbfs', -60)} dBFS.",
        "Leading/trailing silence can be intentional. Long internal gaps may indicate dropouts or missing content.",
        "Audition the listed regions. Remove unintentional silence at the edit stage; do not destructively edit the source here.",
        measured=round_sig(silence_pct, 2), unit="%",
        threshold=round_sig(thresholds["silence_percent_warning"], 2), threshold_unit="% warning",
        time_positions=silence_regions[:50], confidence="high",
    ))

    # Stereo checks
    if stereo.get("supported"):
        correlation_raw = stereo.get("correlation", {}).get("value")
        if correlation_raw is None:
            checks.append(_check(
                "correlation", "Stereo", "Stereo phase correlation", "information",
                "Correlation is undefined: at least one channel has no signal variance.",
                "Pearson correlation cannot be computed for silent or constant channels, so no value is reported.",
                "Check whether both channels are expected to carry signal.",
                measured=None, unit="r", confidence="high",
            ))
        else:
            correlation = float(correlation_raw)
            if correlation <= thresholds["correlation_error"]:
                severity = "error"
            elif correlation <= thresholds["correlation_warning"]:
                severity = "warning"
            else:
                severity = "normal"
            checks.append(_check(
                "correlation", "Stereo", "Stereo phase correlation", severity,
                f"Correlation is {correlation:.3f}.",
                "Positive correlation indicates in-phase channels. Negative correlation can cause mono fold-down cancellation.",
                "Check polarity and phase alignment. Audition the mono fold-down before delivery.",
                measured=round_sig(correlation, 4), unit="r",
                threshold=round_sig(thresholds["correlation_warning"], 3), threshold_unit="r warning",
                time_positions=stereo.get("phase_regions", [])[:20], confidence="high",
            ))
        balance = float(stereo.get("balance", {}).get("balance_db", 0.0) or 0.0)
        abs_balance = abs(balance)
        if abs_balance >= thresholds["channel_imbalance_error_db"]:
            severity = "error"
        elif abs_balance >= thresholds["channel_imbalance_warning_db"]:
            severity = "warning"
        else:
            severity = "normal"
        checks.append(_check(
            "channel_imbalance", "Stereo", "Channel imbalance", severity,
            f"Right/left RMS difference is {balance:+.2f} dB.",
            "A persistent level difference can indicate routing, panning, or capture problems.",
            "Confirm the intended stereo image. If unintentional, inspect channel gain and routing.",
            measured=round_sig(balance, 2), unit="dB",
            threshold=round_sig(thresholds["channel_imbalance_warning_db"], 2), threshold_unit="dB warning",
            confidence="high",
        ))
        for issue in stereo.get("issues", []):
            if issue.get("severity") in {"warning", "error"} and issue.get("type") not in {"negative_phase_correlation", "channel_imbalance"}:
                checks.append(_check(
                    f"stereo_{issue.get('type', 'issue')}", "Stereo", issue.get("type", "Stereo issue").replace("_", " ").title(),
                    issue.get("severity", "warning"), issue.get("message", ""),
                    "This finding is derived from the measured stereo properties.",
                    issue.get("recommendation", "Review the stereo analysis section."),
                    measured=issue.get("measurement"), confidence="high",
                ))
    else:
        checks.append(_check(
            "stereo_mono", "Stereo", "Stereo analysis", "information",
            "Mono file: stereo width, correlation, and phase metrics are not applicable.",
            "The platform intentionally does not fabricate stereo measurements for mono sources.",
            "No action required unless a stereo deliverable was expected.",
            confidence="high",
        ))

    # Sample rate / bit depth
    sr = int(meta.get("sample_rate", 0) or 0)
    common_rates = thresholds.get("common_sample_rates", [])
    if sr and sr not in common_rates:
        checks.append(_check(
            "sample_rate", "Digital", "Unusual sample rate", "information",
            f"Sample rate is {sr} Hz, outside the common delivery rates list.",
            "This is informational only; unusual rates can be valid for sound design or archival work.",
            "Confirm the project/delivery specification. Do not resample during analysis.",
            measured=sr, unit="Hz", threshold=common_rates, threshold_unit="Hz common rates",
            confidence="high",
        ))
    else:
        checks.append(_check(
            "sample_rate_ok", "Digital", "Sample rate", "normal",
            f"Sample rate is {sr} Hz.",
            "The file was analysed at its native sample rate; no resampling was applied.",
            "No action required.", measured=sr, unit="Hz", confidence="high",
        ))
    bit_depth = meta.get("bit_depth")
    if bit_depth is not None:
        severity = "warning" if int(bit_depth) < thresholds["bit_depth_warning_bits"] else "normal"
        checks.append(_check(
            "bit_depth", "Digital", "Bit depth", severity,
            f"Encoded PCM bit depth is {bit_depth} bits.",
            "Lower bit depths reduce dynamic resolution. Lossy files do not have a meaningful PCM bit depth and are handled separately.",
            "Confirm the source resolution. Avoid upsampling bit depth as a substitute for better source material.",
            measured=bit_depth, unit="bits",
            threshold=thresholds["bit_depth_warning_bits"], threshold_unit="bits minimum",
            confidence="high",
        ))
    elif meta.get("is_lossy"):
        checks.append(_check(
            "bit_depth_lossy", "Digital", "Bit depth", "information",
            "Lossy codec: no original PCM bit depth exists.",
            f"{meta.get('bit_depth_note') or 'The codec is lossy.'} The encoded bitrate is reported separately.",
            "No action required. Do not treat the encoded bitrate as an uncompressed bit depth.",
            confidence="high",
        ))

    # Dropouts
    dropouts = td.get("dropouts", {})
    dropout_count = int(dropouts.get("count", 0) or 0)
    severity = "warning" if dropout_count >= thresholds["dropout_warning_count"] and dropout_count > 0 else "normal"
    checks.append(_check(
        "dropouts", "Integrity", "Dropouts", severity,
        f"{dropout_count} possible dropout region(s) detected.",
        "Dropouts are short, abrupt dips below the local level. Some may be intentional edits or silence.",
        "Audition each region. If unintentional, recover the original recording or re-export from the source project.",
        measured=dropout_count, unit="regions",
        threshold=thresholds["dropout_warning_count"], threshold_unit="regions warning",
        time_positions=dropouts.get("regions", [])[:20], confidence="medium",
    ))

    # Crest factor / compression
    crest = loud.get("crest_factor_db")
    if crest is not None:
        severity = "information" if crest < thresholds["crest_factor_warning_db"] else "normal"
        checks.append(_check(
            "crest_factor", "Dynamics", "Crest factor", severity,
            f"Crest factor is {crest:.2f} dB.",
            "Crest factor compares sample peak to RMS. A low value can indicate limiting or dense compression; it is not a defect by itself.",
            "Audition transients and compare with a less-processed version if available.",
            measured=round_sig(crest, 2), unit="dB",
            threshold=thresholds["crest_factor_warning_db"], threshold_unit="dB warning",
            confidence="high",
        ))

    # Spectral observations
    for i, observation in enumerate(spectral.get("observations", [])[:6]):
        checks.append(_check(
            f"spectral_{observation.get('type', i)}", "Frequency", observation.get("type", "Spectral observation").replace("_", " ").title(),
            "information", observation.get("message", ""),
            "This is an observation from the measured spectrum, not a defect classification.",
            observation.get("recommendation", "Review the frequency analysis section."),
            measured=observation.get("measurement"), confidence="high",
        ))

    # Dynamic observations
    for indicator in dynamics.get("compression_indicators", [])[:4]:
        checks.append(_check(
            f"dynamics_{indicator.get('type', 'indicator')}", "Dynamics", indicator.get("type", "Dynamic observation").replace("_", " ").title(),
            "information", indicator.get("message", ""),
            "Dynamics indicators are contextual observations based on measured loudness and peak values.",
            indicator.get("recommendation", "Review the dynamic-range section."),
            measured=indicator.get("measurement"), confidence="high",
        ))

    # Estimate confidence
    for estimate_name, label in (
        ("key", musical.get("confidence", {}).get("key")),
        ("tempo", musical.get("confidence", {}).get("tempo")),
        ("pitch", musical.get("confidence", {}).get("pitch")),
    ):
        if label == "low":
            checks.append(_check(
                f"confidence_{estimate_name}", "Confidence", f"{estimate_name.title()} confidence", "information",
                f"The {estimate_name} estimate has low confidence.",
                "Algorithmic estimates can be ambiguous for this material. The measured chroma/tempo/pitch evidence is still shown.",
                "Verify manually against a reference or DAW before relying on this estimate.",
                measured=label, unit="confidence", confidence="low",
            ))

    for check in checks:
        error = ERROR_LIMITS.get(check["id"])
        if error:
            check["error_threshold_value"] = thresholds.get(error[0])
            check["error_threshold_unit"] = error[1]
    findings = [c for c in checks if c["severity"] != "normal"]
    counts = {severity: sum(1 for c in checks if c["severity"] == severity) for severity in SEVERITY_ORDER}
    overall = "error" if counts["error"] else "warning" if counts["warning"] else "information" if counts["information"] else "normal"
    findings.sort(key=lambda c: (-SEVERITY_ORDER.get(c["severity"], 0), c["category"], c["title"]))
    return {
        "overall": overall,
        "overall_label": overall.capitalize(),
        "summary": counts,
        "checks": checks,
        "findings": findings,
        "thresholds": thresholds,
        "threshold_schema": THRESHOLD_SCHEMA,
        "method": "Each check compares a measured value against an explicit user-configurable threshold. A result is only classified as an error when it crosses the configured error threshold. 'Information' findings are context, not defects.",
        "error_count": counts["error"],
        "warning_count": counts["warning"],
        "information_count": counts["information"],
        "normal_count": counts["normal"],
    }
