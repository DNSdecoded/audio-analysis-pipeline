"""Full-file analysis pipeline and measurement-based recommendations."""

from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np

from ..audio_io import decode_audio
from ..config import Settings, settings as default_settings
from .dynamics import analyze_dynamics
from .loudness import gain_preview, measure_loudness
from .musical import analyze_musical
from .qc import analyze_qc
from .spectral import analyze_spectral
from .stereo import analyze_stereo
from .time_domain import analyze_time_domain
from .utils import round_sig, to_jsonable

SCHEMA_VERSION = "1.0"


class AnalysisError(Exception):
    pass


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _recommendations(analysis: dict[str, Any], target_lufs: float, true_peak_limit: float) -> list[dict[str, Any]]:
    recommendations: list[dict[str, Any]] = []
    loud = analysis["loudness"]
    td = analysis["time_domain"]
    stereo = analysis["stereo"]
    spectral = analysis["spectral"]
    musical = analysis["musical"]
    dynamics = analysis["dynamics"]
    clipping = td.get("clipping", {})
    clip_pct = float(clipping.get("clipped_percent", 0.0) or 0.0)
    if clip_pct > 0:
        recommendations.append({
            "id": "reduce_clipping",
            "category": "Signal quality",
            "priority": "warning" if clip_pct >= 0.005 else "info",
            "title": "Review clipping",
            "supporting_measurement": f"{clip_pct:.4f}% clipped samples at the {clipping.get('threshold_dbfs', -0.1)} dBFS threshold; {clipping.get('clipped_samples', 0)} samples.",
            "explanation": "Clipped samples cannot be restored by lowering gain after rendering; the waveform peaks have already been flattened.",
            "recommendation": "Reduce gain before the final clipper/limiter or restore an unclipped source. Re-render with peak headroom.",
            "automatic_processing": False,
            "time_positions": clipping.get("regions", [])[:20],
        })
    true_peak = loud.get("true_peak_dbtp")
    if true_peak is not None and true_peak > true_peak_limit:
        recommendations.append({
            "id": "control_true_peak",
            "category": "Loudness",
            "priority": "warning" if true_peak <= 0 else "error",
            "title": "Control true peak",
            "supporting_measurement": f"True peak {true_peak:.2f} dBTP exceeds the configured {true_peak_limit:.2f} dBTP limit.",
            "explanation": "Intersample peaks above the limit can clip in playback converters even when sample values are below full scale.",
            "recommendation": "Lower the limiter ceiling or output gain by at least the measured excess. This is a preview recommendation only.",
            "automatic_processing": False,
        })
    gain = gain_preview(loud.get("integrated_lufs"), loud.get("sample_peak_dbfs"), loud.get("true_peak_dbtp"), target_lufs, true_peak_limit)
    if gain.get("supported") and abs(float(gain.get("gain_db", 0.0))) >= 0.1:
        recommendations.append({
            "id": "track_gain",
            "category": "Loudness",
            "title": "Adjust track gain to target",
            "priority": "warning" if gain.get("true_peak_status") == "true_peak_limit_exceeded" else "info",
            "supporting_measurement": f"Integrated {loud.get('integrated_lufs')} LUFS vs target {target_lufs:.2f} LUFS; gain to target {gain['gain_db']:+.2f} dB; expected true peak {gain.get('expected_true_peak_dbtp')} dBTP (limit {true_peak_limit:.2f} dBTP).",
            "explanation": gain.get("explanation") or "The gain value is a linear level change calculated from measured integrated loudness.",
            "recommendation": (
                f"Gain alone is limited to {gain.get('recommended_gain_db'):+.2f} dB by the true-peak limit; reaching the target needs at least {gain.get('peak_control_required_db'):.2f} dB of peak control. Process a copy and re-measure."
                if gain.get("true_peak_status") == "true_peak_limit_exceeded" and gain.get("recommended_gain_db") is not None
                else "Apply the gain only in a copy, then verify true peak and dynamic range. The original file is not modified."
            ),
            "recommended_gain_db": gain.get("recommended_gain_db"),
            "target_reachable_with_gain_only": gain.get("target_reachable_with_gain_only"),
            "automatic_processing": False,
        })
    noise = td.get("noise", {})
    noise_floor = noise.get("noise_floor_dbfs")
    snr = noise.get("snr_db")
    if noise_floor is not None and snr is not None and (float(noise_floor) > -60 or float(snr) < 30):
        recommendations.append({
            "id": "review_noise",
            "category": "Signal quality",
            "priority": "warning" if float(noise_floor) > -45 else "info",
            "title": "Review background noise",
            "supporting_measurement": f"Noise floor {noise_floor} dBFS; estimated SNR {snr} dB.",
            "explanation": "The noise floor is estimated from quiet frames. Quiet musical passages can bias the estimate, so confirm audibly before processing.",
            "recommendation": "Inspect quiet sections and identify the noise source. If noise reduction is needed, process a copy and compare artifacts.",
            "automatic_processing": False,
        })
    if stereo.get("supported"):
        correlation_raw = stereo.get("correlation", {}).get("value")
        mono_loss_raw = stereo.get("mono_compatibility", {}).get("mono_loss_db")
        correlation = float(correlation_raw) if correlation_raw is not None else 0.0
        mono_loss = float(mono_loss_raw) if mono_loss_raw is not None else 0.0
        if correlation_raw is not None and (correlation < 0 or mono_loss < -3.5):
            recommendations.append({
                "id": "check_phase",
                "category": "Stereo",
                "priority": "warning" if correlation < -0.1 else "info",
                "title": "Check stereo phase compatibility",
                "supporting_measurement": f"Correlation {correlation:.3f}; mono fold-down loss {mono_loss:.2f} dB.",
                "explanation": "Negative correlation or large fold-down loss indicates that some content partially cancels in mono.",
                "recommendation": "Check polarity, phase alignment, and stereo widening. Audition the mono fold-down before delivery.",
                "automatic_processing": False,
            })
    for observation in spectral.get("observations", []):
        recommendations.append({
            "id": f"spectral_{observation.get('type')}",
            "category": "Frequency",
            "priority": "info",
            "title": observation.get("type", "Spectral observation").replace("_", " ").title(),
            "supporting_measurement": observation.get("message"),
            "explanation": "This recommendation is based on measured spectral energy, not on a subjective judgment of the mix.",
            "recommendation": observation.get("recommendation", "Review the frequency analysis section."),
            "automatic_processing": False,
        })
    if dynamics.get("compression_indicators"):
        recommendations.append({
            "id": "review_compression",
            "category": "Dynamics",
            "priority": "info",
            "title": "Review dynamics and limiting",
            "supporting_measurement": f"LRA {loud.get('loudness_range_lu')} LU; PLR {loud.get('peak_to_loudness_ratio_db')} dB; crest factor {loud.get('crest_factor_db')} dB.",
            "explanation": "Low dynamic-range indicators can result from intentional limiting or from excessive compression. The measurements alone cannot distinguish artistic intent.",
            "recommendation": "Compare against a less-processed version, inspect limiter gain reduction, and audition transient attack.",
            "automatic_processing": False,
        })
    silence_pct = float(td.get("silence", {}).get("percent", 0.0) or 0.0)
    if silence_pct > 30:
        recommendations.append({
            "id": "review_silence",
            "category": "Integrity",
            "priority": "warning",
            "title": "Review unexpected silence",
            "supporting_measurement": f"{silence_pct:.2f}% of the duration is below {td.get('silence', {}).get('threshold_dbfs', -60)} dBFS.",
            "explanation": "Long silent sections may be intentional (intros, gaps) or may indicate missing audio or a failed render.",
            "recommendation": "Audition the silence regions listed in the waveform analysis and confirm they match the intended arrangement.",
            "automatic_processing": False,
            "time_positions": td.get("silence", {}).get("regions", [])[:20],
        })
    sample_rate = analysis["metadata"].get("sample_rate")
    if sample_rate not in (44100, 48000, 88200, 96000, 176400, 192000):
        recommendations.append({
            "id": "check_sample_rate",
            "category": "Digital",
            "priority": "info",
            "title": "Check sample-rate compatibility",
            "supporting_measurement": f"Detected sample rate: {sample_rate} Hz.",
            "explanation": "The file was analysed at its native rate. Unusual rates can be valid, but may not match the delivery specification.",
            "recommendation": "Confirm the project delivery rate. Do not resample the original during analysis; create a separate processed copy if required.",
            "automatic_processing": False,
        })
    if musical.get("confidence", {}).get("key") == "low":
        recommendations.append({
            "id": "verify_key",
            "category": "Musical",
            "priority": "info",
            "title": "Verify the key estimate",
            "supporting_measurement": f"Estimated key {musical.get('key', {}).get('key')} with {musical.get('key', {}).get('confidence_label')} confidence.",
            "explanation": "Key finding is statistical and can be ambiguous for modal, atonal, or heavily processed material.",
            "recommendation": "Confirm the key in a DAW or against the written score before using it for harmonic decisions.",
            "automatic_processing": False,
        })
    return recommendations


def run_full_analysis(
    path: Path,
    ext: str,
    metadata: dict[str, Any],
    validation: dict[str, Any],
    file_id: str,
    original_name: str,
    target_lufs: float = -14.0,
    true_peak_limit: float = -1.0,
    n_fft: int = 4096,
    hop_length: int = 1024,
    qc_overrides: dict[str, Any] | None = None,
    config: Settings = default_settings,
    progress: Callable[[float, str], None] | None = None,
) -> dict[str, Any]:
    started = time.time()
    def report(fraction: float, message: str) -> None:
        if progress:
            try:
                progress(max(0.0, min(1.0, fraction)), message)
            except Exception:
                pass

    report(0.02, "Reading original file")
    file_hash = _hash_file(path)
    report(0.08, "Decoding audio")
    try:
        data, sr, decode_warnings = decode_audio(path, ext)
    except Exception as exc:
        raise AnalysisError(f"Decoding failed: {exc}") from exc
    if data.size == 0:
        raise AnalysisError("Decoded audio is empty")
    duration = data.shape[0] / float(sr)
    if duration > config.max_duration_seconds + 0.5:
        raise AnalysisError(
            f"Decoded duration {duration:.1f}s exceeds the configured {config.max_duration_seconds:.0f}s limit"
        )
    # float32 accumulation: avoids a transient full-length float64 copy.
    mono = data[:, 0].copy() if data.shape[1] == 1 else np.mean(data, axis=1, dtype=np.float32)
    report(0.14, "Measuring loudness (BS.1770 / EBU R128)")
    loudness = measure_loudness(data, sr, channel_layout=metadata.get("channel_layout"))
    report(0.28, "Analyzing time domain and signal integrity")
    time_domain = analyze_time_domain(
        data, sr,
        true_peak_dbtp=loudness.get("true_peak_dbtp"),
        max_points=config.max_feature_points,
        max_waveform_buckets=config.max_waveform_buckets,
    )
    report(0.40, "Computing spectrum, spectrogram and spectral features")
    spectral = analyze_spectral(
        mono, sr, duration,
        n_fft=n_fft, hop_length=hop_length,
        max_spectrogram_frames=config.max_spectrogram_frames,
        max_feature_points=config.max_feature_points,
        hpss_seconds=config.hpss_analysis_seconds,
        progress=lambda f, m: report(0.40 + 0.25 * f, m),
    )
    chroma_mean = np.asarray(spectral.get("chroma", {}).get("mean_energy", []), dtype=np.float64)
    report(0.70, "Detecting key, tempo, beats and pitch")
    musical = analyze_musical(
        mono, sr, duration,
        chroma_mean=chroma_mean,
        pitch_seconds=config.pitch_analysis_seconds,
    )
    report(0.82, "Analyzing stereo, phase and dynamics")
    stereo = analyze_stereo(data, sr)
    dynamics = analyze_dynamics(loudness, time_domain, duration, musical.get("rhythm"))
    gain = gain_preview(
        loudness.get("integrated_lufs"), loudness.get("sample_peak_dbfs"),
        loudness.get("true_peak_dbtp"), target_lufs, true_peak_limit,
    )
    report(0.88, "Running quality control")
    analysis: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "file_id": file_id,
        "original_name": original_name,
        "analyzed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sha256": file_hash,
        "metadata": metadata,
        "validation": {
            "ok": bool(validation.get("ok", True)),
            "errors": validation.get("errors", []),
            "warnings": list(validation.get("warnings", [])) + decode_warnings,
        },
        "loudness": loudness,
        "time_domain": time_domain,
        "spectral": spectral,
        "musical": musical,
        "stereo": stereo,
        "dynamics": dynamics,
        "track_gain": gain,
        "analysis_settings": {
            "target_lufs": target_lufs,
            "true_peak_limit": true_peak_limit,
            "fft_size": spectral.get("fft", {}).get("n_fft"),
            "hop_length": spectral.get("spectrogram", {}).get("hop_length"),
            "spectrogram_frames": config.max_spectrogram_frames,
            "pitch_analysis_seconds": min(config.pitch_analysis_seconds, duration),
            "hpss_analysis_seconds": min(config.hpss_analysis_seconds, duration),
            "native_sample_rate": sr,
            "resampled_for_analysis": False,
        },
        "methods": {
            "loudness": "ITU-R BS.1770-4 / EBU R128 K-weighting and gating; true peak with 4x oversampling",
            "spectrum": f"STFT with Hann window, n_fft={spectral.get('fft', {}).get('n_fft')}, hop={hop_length}; amplitude calibrated to dBFS",
            "spectrogram": "STFT magnitude, averaged into display cells; full-resolution values are computed from the source audio",
            "mel": "Slaney-normalised Mel filterbank over the calibrated power spectrogram",
            "chroma": "Chroma-STFT from the source STFT",
            "key": "Krumhansl-Schmuckler profile correlation (estimate)",
            "tempo": "librosa beat tracker and tempogram autocorrelation (estimate)",
            "pitch": "librosa.pyin probabilistic YIN on the most energetic segment (estimate)",
            "stereo": "Pearson correlation, mid/side RMS, mono fold-down level comparison",
            "dynamics": "Crest factor, EBU R128 LRA, short-term loudness variation",
            "qc": "Threshold-based checks with configurable warning/error limits",
        },
        "confidence": {
            "direct_measurements": [
                "sample rate", "channels", "bit depth (when PCM)", "duration", "file size",
                "sample peak", "true peak", "RMS", "DC offset", "clipping", "silence",
                "integrated loudness", "loudness range", "stereo correlation", "mid/side energy",
            ],
            "estimates": [
                "noise floor / SNR", "musical key", "tempo / beats", "pitch contour",
                "harmonic/percussive separation", "onset detection",
            ],
            "notes": [
                "Estimated values are labelled and include confidence information where available.",
                "Lossy files do not have a meaningful original PCM bit depth; encoded bitrate is reported separately.",
                "All analysis is performed on decoded copies. The original upload is never modified.",
            ],
        },
    }
    analysis["recommendations"] = _recommendations(analysis, target_lufs, true_peak_limit)
    qc = analyze_qc(analysis, qc_overrides)
    analysis["qc"] = qc
    analysis["summary"] = {
        "format": metadata.get("format"),
        "sample_rate": metadata.get("sample_rate"),
        "bit_depth": metadata.get("bit_depth"),
        "bit_depth_source": metadata.get("bit_depth_source"),
        "channels": metadata.get("channels"),
        "duration_seconds": metadata.get("duration"),
        "integrated_lufs": loudness.get("integrated_lufs"),
        "true_peak_dbtp": loudness.get("true_peak_dbtp"),
        "loudness_range_lu": loudness.get("loudness_range_lu"),
        "crest_factor_db": loudness.get("crest_factor_db"),
        "key": musical.get("key", {}).get("key"),
        "tempo_bpm": musical.get("tempo", {}).get("bpm"),
        "correlation": stereo.get("correlation", {}).get("value") if stereo.get("supported") else None,
        "qc_overall": qc.get("overall"),
        "qc_errors": qc.get("error_count"),
        "qc_warnings": qc.get("warning_count"),
    }
    analysis["analysis_duration_seconds"] = round_sig(time.time() - started, 2)
    report(0.98, "Finalizing results")
    return to_jsonable(analysis)
