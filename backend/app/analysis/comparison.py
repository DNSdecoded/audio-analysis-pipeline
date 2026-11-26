"""Multi-file comparison engine."""

from __future__ import annotations

import math
from typing import Any, Callable

from .loudness import gain_preview
from .utils import round_sig

STATUS_ORDER = {"match": 0, "different": 1, "large_deviation": 2, "low_confidence": 3, "unsupported": 4}


def _get(analysis: dict[str, Any], path: tuple[str, ...]) -> Any:
    value: Any = analysis
    for part in path:
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _spec(
    key: str, label: str, group: str, unit: str, path: tuple[str, ...],
    kind: str = "numeric", tolerance: float = 0.0, relative: float = 0.0,
    confidence_path: tuple[str, ...] | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    return {
        "key": key, "label": label, "group": group, "unit": unit, "path": path,
        "kind": kind, "tolerance": tolerance, "relative": relative,
        "confidence_path": confidence_path, "note": note,
    }


PARAMETER_SPECS = [
    _spec("format", "Format", "File", "", ("metadata", "format"), "categorical"),
    _spec("codec", "Codec", "File", "", ("metadata", "codec"), "categorical"),
    _spec("duration", "Duration", "File", "s", ("metadata", "duration"), tolerance=0.1, relative=0.005),
    _spec("sample_rate", "Sample rate", "File", "Hz", ("metadata", "sample_rate"), tolerance=0.0),
    _spec("bit_depth", "Bit depth", "File", "bits", ("metadata", "bit_depth"), tolerance=0.0),
    _spec("bitrate", "Encoded bitrate", "File", "kbps", ("metadata", "bitrate_kbps"), tolerance=16.0, relative=0.05),
    _spec("channels", "Channels", "File", "", ("metadata", "channels"), tolerance=0.0),
    _spec("file_size", "File size", "File", "MB", ("metadata", "size_bytes"), tolerance=0.05, relative=0.05),
    _spec("is_lossy", "Lossy codec", "File", "", ("metadata", "is_lossy"), "categorical"),
    _spec("integrated_lufs", "Integrated loudness", "Loudness", "LUFS", ("loudness", "integrated_lufs"), tolerance=0.5),
    _spec("loudness_range", "Loudness range", "Loudness", "LU", ("loudness", "loudness_range_lu"), tolerance=0.5),
    _spec("true_peak", "True peak", "Loudness", "dBTP", ("loudness", "true_peak_dbtp"), tolerance=0.3),
    _spec("sample_peak", "Sample peak", "Loudness", "dBFS", ("loudness", "sample_peak_dbfs"), tolerance=0.3),
    _spec("rms", "RMS level", "Loudness", "dBFS", ("loudness", "rms_dbfs"), tolerance=0.5),
    _spec("crest_factor", "Crest factor", "Dynamics", "dB", ("loudness", "crest_factor_db"), tolerance=0.5),
    _spec("plr", "Peak-to-loudness ratio", "Dynamics", "dB", ("loudness", "peak_to_loudness_ratio_db"), tolerance=0.5),
    _spec("dc_offset", "DC offset", "Signal quality", "linear", ("time_domain", "dc_offset", "max_abs"), tolerance=0.0005),
    _spec("clipping", "Clipping", "Signal quality", "%", ("time_domain", "clipping", "clipped_percent"), tolerance=0.001),
    _spec("silence", "Silence", "Signal quality", "%", ("time_domain", "silence", "percent"), tolerance=0.5),
    _spec("snr", "SNR", "Signal quality", "dB", ("time_domain", "noise", "snr_db"), tolerance=1.0),
    _spec("noise_floor", "Noise floor", "Signal quality", "dBFS", ("time_domain", "noise", "noise_floor_dbfs"), tolerance=1.0),
    _spec("correlation", "Stereo correlation", "Stereo", "r", ("stereo", "correlation", "value"), tolerance=0.05),
    _spec("stereo_width", "Stereo width", "Stereo", "%", ("stereo", "mid_side", "stereo_width_percent"), tolerance=3.0),
    _spec("channel_balance", "Channel balance", "Stereo", "dB", ("stereo", "balance", "balance_db"), tolerance=0.3),
    _spec("mono_loss", "Mono fold-down loss", "Stereo", "dB", ("stereo", "mono_compatibility", "mono_loss_db"), tolerance=0.5),
    _spec("key", "Musical key", "Musical", "", ("musical", "key", "key"), "categorical", confidence_path=("musical", "key", "confidence_label")),
    _spec("tempo", "Tempo", "Musical", "BPM", ("musical", "tempo", "bpm"), tolerance=0.5, relative=0.01, confidence_path=("musical", "tempo", "confidence_label")),
    _spec("tempo_stability", "Tempo stability", "Musical", "", ("musical", "tempo", "tempo_stability"), tolerance=0.03),
    _spec("pitch_median", "Median F0", "Musical", "Hz", ("musical", "pitch", "f0_median_hz"), tolerance=2.0, relative=0.01, confidence_path=("musical", "pitch", "confidence_label")),
    _spec("spectral_centroid", "Spectral centroid", "Spectral", "Hz", ("spectral", "spectral_features", "centroid_hz", "mean"), tolerance=30.0, relative=0.05),
    _spec("spectral_bandwidth", "Spectral bandwidth", "Spectral", "Hz", ("spectral", "spectral_features", "bandwidth_hz", "mean"), tolerance=50.0, relative=0.05),
    _spec("spectral_rolloff", "Spectral roll-off 85%", "Spectral", "Hz", ("spectral", "spectral_features", "rolloff85_hz", "mean"), tolerance=50.0, relative=0.05),
    _spec("spectral_flatness", "Spectral flatness", "Spectral", "", ("spectral", "spectral_features", "flatness", "mean"), tolerance=0.02),
    _spec("zcr", "Zero-crossing rate", "Spectral", "", ("spectral", "spectral_features", "zero_crossing_rate", "mean"), tolerance=0.01),
    _spec("hnr", "Harmonic/percussive ratio", "Spectral", "dB", ("spectral", "spectral_features", "harmonic_to_noise_ratio_db"), tolerance=1.0),
] + [
    _spec(f"band_{band}", f"{label} share", "Frequency bands", "%", ("spectral", "bands", "bands"), "band", tolerance=2.0)
    for band, label in [
        ("sub_bass", "Sub-bass"), ("bass", "Bass"), ("low_midrange", "Low-midrange"),
        ("midrange", "Midrange"), ("upper_midrange", "Upper-midrange"),
        ("presence", "Presence"), ("brilliance", "Brilliance"),
    ]
]


def _band_value(analysis: dict[str, Any], band_key: str) -> Any:
    bands = _get(analysis, ("spectral", "bands", "bands"))
    if not isinstance(bands, list):
        return None
    for band in bands:
        if band.get("key") == band_key:
            return band.get("relative_energy_pct") if band.get("supported") else None
    return None


def _value(analysis: dict[str, Any], spec: dict[str, Any]) -> Any:
    if spec["kind"] == "band":
        return _band_value(analysis, spec["key"].replace("band_", "", 1))
    value = _get(analysis, spec["path"])
    if spec["key"] == "file_size" and value is not None:
        value = float(value) / (1024 * 1024)
    return value


def _confidence(analysis: dict[str, Any], spec: dict[str, Any]) -> str | None:
    if not spec.get("confidence_path"):
        return None
    value = _get(analysis, spec["confidence_path"])
    return value if isinstance(value, str) else None


def _fmt(value: Any, spec: dict[str, Any]) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (int, float)):
        if spec["key"] in {"sample_rate", "channels", "bit_depth", "bitrate"}:
            return f"{int(round(value)):,}" if spec["key"] != "bitrate" else f"{value:.0f}"
        if spec["key"] in {"dc_offset", "spectral_flatness", "zcr", "correlation", "tempo_stability"}:
            return f"{value:.4f}" if abs(value) < 1 else f"{value:.2f}"
        return f"{value:.2f}"
    return str(value)


def compare_analyses(
    analyses: dict[str, dict[str, Any]],
    file_order: list[str],
    file_names: dict[str, str],
    selected_parameters: list[str] | None = None,
    target_lufs: float = -14.0,
    true_peak_limit: float = -1.0,
    reference_file_id: str | None = None,
    mode: str = "full",
    segment_ranges: dict[str, dict[str, float]] | None = None,
) -> dict[str, Any]:
    if len(file_order) < 2:
        raise ValueError("At least two files are required for comparison")
    specs = PARAMETER_SPECS
    if selected_parameters:
        wanted = set(selected_parameters)
        specs = [s for s in specs if s["key"] in wanted]
    rows = []
    for spec in specs:
        values: dict[str, Any] = {}
        displays: dict[str, str] = {}
        confidences: dict[str, str | None] = {}
        for fid in file_order:
            analysis = analyses.get(fid)
            value = _value(analysis, spec) if analysis else None
            values[fid] = value
            displays[fid] = _fmt(value, spec)
            confidences[fid] = _confidence(analysis, spec) if analysis else None
        non_null = [v for v in values.values() if v is not None and not (isinstance(v, float) and not math.isfinite(v))]
        low_confidence = any(c == "low" for c in confidences.values() if c)
        unsupported = len(non_null) < len(file_order)
        deviation_status = "unsupported"
        spread = None
        tolerance = spec["tolerance"]
        if not unsupported:
            if spec["kind"] in {"categorical"}:
                deviation_status = "match" if len({str(v) for v in non_null}) == 1 else "different"
                spread = 0.0 if deviation_status == "match" else None
            else:
                numeric = [float(v) for v in non_null]
                mean_abs = sum(abs(v) for v in numeric) / len(numeric)
                effective_tolerance = max(spec["tolerance"], spec["relative"] * mean_abs)
                spread = max(numeric) - min(numeric)
                if spread <= effective_tolerance:
                    deviation_status = "match"
                elif spread <= effective_tolerance * 3.0:
                    deviation_status = "different"
                else:
                    deviation_status = "large_deviation"
                tolerance = effective_tolerance
        status = "unsupported" if unsupported else "low_confidence" if low_confidence else deviation_status
        row = {
            "key": spec["key"],
            "label": spec["label"],
            "group": spec["group"],
            "unit": spec["unit"],
            "kind": spec["kind"],
            "values": {fid: values[fid] for fid in file_order},
            "display": {fid: displays[fid] for fid in file_order},
            "status": status,
            "deviation_status": deviation_status,
            "spread": round_sig(spread, 4) if spread is not None else None,
            "tolerance": round_sig(tolerance, 4),
            "tolerance_note": f"±{round_sig(tolerance, 4)} {spec['unit']}".strip(),
            "low_confidence": low_confidence,
            "confidence": confidences,
            "note": spec.get("note"),
        }
        if reference_file_id and reference_file_id in values:
            reference_value = values[reference_file_id]
            row["reference_file_id"] = reference_file_id
            row["reference_value"] = reference_value
            row["deviations"] = {}
            for fid in file_order:
                value = values[fid]
                if value is None or reference_value is None:
                    row["deviations"][fid] = None
                elif isinstance(value, (int, float)) and isinstance(reference_value, (int, float)):
                    row["deviations"][fid] = round_sig(float(value) - float(reference_value), 4)
                else:
                    row["deviations"][fid] = None
        rows.append(row)

    # Gain rows use the same gain_preview() as the per-file analysis so the
    # gating and true-peak rules are identical everywhere.
    gain_rows = []
    for fid in file_order:
        analysis = analyses.get(fid) or {}
        preview = gain_preview(
            _get(analysis, ("loudness", "integrated_lufs")),
            _get(analysis, ("loudness", "sample_peak_dbfs")),
            _get(analysis, ("loudness", "true_peak_dbtp")),
            target_lufs, true_peak_limit,
        )
        gain_rows.append({
            "file_id": fid,
            "file_name": file_names.get(fid, fid),
            "supported": bool(preview.get("supported")),
            "reason": preview.get("reason"),
            "integrated_lufs": _get(analysis, ("loudness", "integrated_lufs")),
            "target_lufs": target_lufs,
            "gain_db": preview.get("gain_db"),
            "expected_sample_peak_dbfs": preview.get("expected_sample_peak_dbfs"),
            "expected_true_peak_dbtp": preview.get("expected_true_peak_dbtp"),
            "true_peak_limit": true_peak_limit,
            "peak_control_required_db": preview.get("peak_control_required_db"),
            "max_gain_within_true_peak_limit_db": preview.get("max_gain_within_true_peak_limit_db"),
            "recommended_gain_db": preview.get("recommended_gain_db"),
            "target_reachable_with_gain_only": preview.get("target_reachable_with_gain_only"),
            "status": preview.get("true_peak_status") if preview.get("supported") else "unsupported",
        })

    findings = []
    def add_finding(fid: str, severity: str, title: str, message: str, recommendation: str, measurement: dict[str, Any]):
        findings.append({
            "id": fid, "severity": severity, "title": title, "message": message,
            "recommendation": recommendation, "measurement": measurement,
        })

    sample_rates = {fid: _get(analyses[fid], ("metadata", "sample_rate")) for fid in file_order}
    if len({v for v in sample_rates.values() if v}) > 1:
        add_finding(
            "sample_rate_mismatch", "information", "Sample-rate mismatch",
            "The compared files use different sample rates.",
            "Confirm which rate is required for delivery. Do not resample during analysis; create a separate processed copy if conversion is needed.",
            {"sample_rates_hz": sample_rates},
        )
        numeric_rates = sorted({int(v) for v in sample_rates.values() if v})
        if len(numeric_rates) == 2:
            ratio = max(numeric_rates) / min(numeric_rates)
            if abs(ratio - round(ratio)) < 1e-6 and round(ratio) in {2, 4, 8}:
                add_finding(
                    "possible_resample_ratio", "information", "Integer sample-rate ratio",
                    f"The rates form an integer ratio of {round(ratio)}x. This is consistent with, but not proof of, sample-rate conversion.",
                    "Treat this only as a lineage hint; verify against the source project.",
                    {"ratio": round(ratio, 3), "rates_hz": numeric_rates},
                )
    bit_depths = {fid: _get(analyses[fid], ("metadata", "bit_depth")) for fid in file_order}
    if len({v for v in bit_depths.values() if v is not None}) > 1:
        add_finding(
            "bit_depth_mismatch", "information", "Bit-depth mismatch",
            "The compared files have different PCM bit depths.",
            "Confirm that the delivery specification allows the difference; avoid treating encoded lossy bitrate as bit depth.",
            {"bit_depths_bits": bit_depths},
        )
    channel_counts = {fid: _get(analyses[fid], ("metadata", "channels")) for fid in file_order}
    if len({v for v in channel_counts.values() if v}) > 1:
        add_finding(
            "channel_mismatch", "information", "Channel-configuration mismatch",
            "The compared files have different channel counts.",
            "Compare like with like, or account for mono/stereo differences when interpreting width and correlation.",
            {"channels": channel_counts},
        )
    loudness_values = {fid: _get(analyses[fid], ("loudness", "integrated_lufs")) for fid in file_order}
    loud_numeric = [v for v in loudness_values.values() if v is not None]
    if len(loud_numeric) >= 2 and (max(loud_numeric) - min(loud_numeric)) > 3.0:
        add_finding(
            "loudness_difference", "information", "Loudness difference",
            f"Integrated loudness differs by {max(loud_numeric) - min(loud_numeric):.2f} LU across files.",
            "Match levels before making perceptual judgments; use the track-gain preview to compare at the same loudness.",
            {"integrated_lufs": loudness_values, "difference_lu": round_sig(max(loud_numeric) - min(loud_numeric), 2)},
        )
    durations = {fid: _get(analyses[fid], ("metadata", "duration")) for fid in file_order}
    dur_numeric = [v for v in durations.values() if v is not None]
    if len(dur_numeric) >= 2 and (max(dur_numeric) - min(dur_numeric)) > 0.5:
        add_finding(
            "duration_difference", "information", "Duration difference",
            f"Durations differ by {max(dur_numeric) - min(dur_numeric):.2f} s.",
            "Use alignment or compare matching sections before overlaying time-based measurements.",
            {"durations_seconds": durations, "difference_seconds": round_sig(max(dur_numeric) - min(dur_numeric), 2)},
        )
    keys = {fid: _get(analyses[fid], ("musical", "key", "key")) for fid in file_order}
    if len({v for v in keys.values() if v}) > 1:
        add_finding(
            "key_mismatch", "information", "Different estimated keys",
            "The estimated musical keys are not identical.",
            "Verify the key estimates before using them for harmonic mixing or transposition decisions.",
            {"keys": keys},
        )
    tempos = {fid: _get(analyses[fid], ("musical", "tempo", "bpm")) for fid in file_order}
    tempo_numeric = [v for v in tempos.values() if v is not None]
    if len(tempo_numeric) >= 2 and (max(tempo_numeric) - min(tempo_numeric)) / max(np_mean(tempo_numeric), 1e-9) > 0.02:
        add_finding(
            "tempo_difference", "information", "Tempo difference",
            "The estimated tempi differ by more than 2%.",
            "Check half/double-time interpretations and align musical sections before comparison.",
            {"tempo_bpm": tempos},
        )

    status_counts = {status: sum(1 for row in rows if row["status"] == status) for status in STATUS_ORDER}
    groups = []
    for group in dict.fromkeys(row["group"] for row in rows):
        group_rows = [row for row in rows if row["group"] == group]
        groups.append({
            "name": group,
            "rows": group_rows,
            "summary": {status: sum(1 for row in group_rows if row["status"] == status) for status in STATUS_ORDER},
        })
    return {
        "mode": mode,
        "segment_ranges": segment_ranges or {},
        "file_order": file_order,
        "files": [{"id": fid, "name": file_names.get(fid, fid)} for fid in file_order],
        "reference_file_id": reference_file_id,
        "parameters": [
            {key: spec[key] for key in ("key", "label", "group", "unit", "kind", "tolerance", "relative")}
            for spec in PARAMETER_SPECS
        ],
        "rows": rows,
        "groups": groups,
        "summary": status_counts,
        "gain_preview": gain_rows,
        "findings": findings,
        "target_lufs": target_lufs,
        "true_peak_limit": true_peak_limit,
        "method": "Each numeric parameter is compared with an explicit tolerance. 'match' is within tolerance, 'different' is up to 3x tolerance, and 'large_deviation' exceeds 3x tolerance. Low-confidence estimates are flagged. Categorical values match only when identical.",
        "notes": [
            "Level-match before perceptual comparison; loudness differences can bias judgments.",
            "A sample-rate difference is not automatically a defect.",
            "MP3/AAC/Vorbis bit depth is not reported as PCM bit depth.",
        ],
    }


def np_mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0
