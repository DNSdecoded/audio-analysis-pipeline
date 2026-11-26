"""Report generation and server-side PNG plots from real analysis data."""

from __future__ import annotations

import csv
import io
import json
import threading
from datetime import datetime, timezone
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.ticker import FuncFormatter
from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    Image as RLImage,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from .analysis.qc import ERROR_LIMITS, describe_limit

PLOT_LOCK = threading.Lock()
# PDF tables are capped to keep the report readable; the cut is always stated
# in the PDF and the complete data is in the CSV / JSON exports.
PDF_MAX_QC_ROWS = 40
PDF_MAX_COMPARISON_ROWS = 80
STATUS_COLORS = {
    "match": "#1f9d55",
    "different": "#b7791f",
    "large_deviation": "#c53030",
    "low_confidence": "#6b46c1",
    "unsupported": "#718096",
}
SEVERITY_COLORS = {
    "normal": "#2f855a",
    "information": "#2b6cb0",
    "warning": "#b7791f",
    "error": "#c53030",
}


def _style_axes(ax: plt.Axes, title: str | None = None, xlabel: str | None = None, ylabel: str | None = None) -> None:
    ax.grid(True, color="#d8dee9", linewidth=0.6, alpha=0.8)
    ax.set_facecolor("#ffffff")
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    if title:
        ax.set_title(title, fontsize=11, fontweight="bold", loc="left", color="#1a202c")
    if xlabel:
        ax.set_xlabel(xlabel, fontsize=8.5, color="#2d3748")
    if ylabel:
        ax.set_ylabel(ylabel, fontsize=8.5, color="#2d3748")
    ax.tick_params(labelsize=8, colors="#2d3748")


def _new_figure(width: float, height: float):
    fig, ax = plt.subplots(figsize=(width, height), dpi=110)
    fig.patch.set_facecolor("#ffffff")
    fig.subplots_adjust(left=0.075, right=0.985, top=0.9, bottom=0.13)
    return fig, ax


def _save(fig) -> bytes:
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=110, bbox_inches="tight", facecolor="#ffffff", pil_kwargs={"optimize": True})
    plt.close(fig)
    buffer.seek(0)
    return buffer.getvalue()


def _arr(values: Any) -> np.ndarray:
    """Float array with JSON nulls (unmeasurable points) as NaN gaps."""
    return np.asarray([np.nan if v is None else v for v in (values or [])], dtype=float)


def _name(analysis: dict[str, Any]) -> str:
    return analysis.get("original_name") or analysis.get("metadata", {}).get("original_name") or "Audio file"


def _times(analysis: dict[str, Any]) -> np.ndarray:
    return np.asarray(analysis.get("time_domain", {}).get("waveform", {}).get("times", []), dtype=float)


def _slice(times: np.ndarray, values: np.ndarray, start: float | None, end: float | None):
    if times.size == 0:
        return times, values
    mask = np.ones(times.size, dtype=bool)
    if start is not None:
        mask &= times >= float(start)
    if end is not None:
        mask &= times <= float(end)
    return times[mask], values[mask]


def plot_waveform(analysis: dict[str, Any], width: float = 12.0, height: float = 3.6, start: float | None = None, end: float | None = None) -> bytes:
    with PLOT_LOCK:
        fig, ax = _new_figure(width, height)
        wf = analysis.get("time_domain", {}).get("waveform", {})
        times = np.asarray(wf.get("times", []), dtype=float)
        mins = np.asarray(wf.get("mono_min", []), dtype=float)
        maxs = np.asarray(wf.get("mono_max", []), dtype=float)
        if times.size == 0:
            ax.text(0.5, 0.5, "No waveform data", ha="center", va="center", transform=ax.transAxes)
        else:
            mask = np.ones(times.size, dtype=bool)
            if start is not None:
                mask &= times >= start
            if end is not None:
                mask &= times <= end
            ax.fill_between(times[mask], mins[mask], maxs[mask], color="#2b6cb0", linewidth=0, alpha=0.85, label="Peak envelope")
            env = analysis.get("time_domain", {}).get("envelopes", {})
            et = np.asarray(env.get("times", []), dtype=float)
            er = np.asarray(env.get("rms_db", []), dtype=float)
            if et.size:
                emask = np.ones(et.size, dtype=bool)
                if start is not None:
                    emask &= et >= start
                if end is not None:
                    emask &= et <= end
                amp = 10.0 ** (er / 20.0)
                ax.plot(et[emask], amp[emask], color="#ed8936", linewidth=1.0, label="RMS envelope")
                ax.plot(et[emask], -amp[emask], color="#ed8936", linewidth=1.0)
            for region in analysis.get("time_domain", {}).get("clipping", {}).get("regions", [])[:80]:
                ax.axvspan(region["start"], region["end"], color="#e53e3e", alpha=0.18, linewidth=0)
            for region in analysis.get("time_domain", {}).get("silence", {}).get("regions", [])[:80]:
                ax.axvspan(region["start"], region["end"], color="#a0aec0", alpha=0.18, linewidth=0)
            beats = analysis.get("musical", {}).get("tempo", {}).get("beats", [])
            for beat in beats[:600]:
                ax.axvline(beat, color="#3182ce", alpha=0.35, linewidth=0.5)
            if start is not None or end is not None:
                ax.set_xlim(max(0, start or 0), end or max(times.max(), 1))
            else:
                ax.set_xlim(0, max(float(times.max()), 0.01))
            ax.set_ylim(-1.05, 1.05)
            ax.set_xlabel("Time (s)")
            ax.set_ylabel("Amplitude (linear)")
            ax.legend(loc="upper right", fontsize=7, frameon=False)
        _style_axes(ax, f"Waveform — {_name(analysis)}", "Time (s)", "Amplitude")
        return _save(fig)


def plot_spectrum(analysis: dict[str, Any], width: float = 12.0, height: float = 4.0, log_scale: bool = True) -> bytes:
    with PLOT_LOCK:
        fig, ax = _new_figure(width, height)
        fft = analysis.get("spectral", {}).get("fft", {})
        freqs = np.asarray(fft.get("frequencies_hz", []), dtype=float)
        dbfs = np.asarray(fft.get("average_dbfs", []), dtype=float)
        if freqs.size == 0:
            ax.text(0.5, 0.5, "No spectrum data", ha="center", va="center", transform=ax.transAxes)
        else:
            mask = freqs >= 20
            ax.plot(freqs[mask], dbfs[mask], color="#2b6cb0", linewidth=0.9, label="Average spectrum")
            if log_scale:
                ax.set_xscale("log")
            ax.set_xlim(20, min(20000, freqs[-1]))
            ax.set_ylim(max(-120, float(np.nanmin(dbfs[mask])) - 4), 6)
            for low, high, label in [
                (20, 60, "Sub"), (60, 250, "Bass"), (250, 500, "Low-mid"),
                (500, 2000, "Mid"), (2000, 4000, "Upper-mid"), (4000, 6000, "Presence"),
                (6000, 20000, "Brilliance"),
            ]:
                if low < ax.get_xlim()[1]:
                    ax.axvline(low, color="#cbd5e0", linewidth=0.7, linestyle="--")
            for peak in fft.get("peaks", [])[:5]:
                ax.annotate(
                    f"{peak['frequency_hz']:.0f} Hz\n{peak['amplitude_dbfs']:.1f} dBFS",
                    (peak["frequency_hz"], peak["amplitude_dbfs"]),
                    xytext=(8, 8), textcoords="offset points", fontsize=6.5,
                    color="#2d3748",
                    arrowprops={"arrowstyle": "-", "color": "#718096", "lw": 0.6},
                )
            ax.set_xlabel("Frequency (Hz)")
            ax.set_ylabel("Amplitude (dBFS)")
            ax.legend(loc="upper right", fontsize=7, frameon=False)
        _style_axes(ax, f"FFT spectrum — {_name(analysis)}", "Frequency (Hz)", "Amplitude (dBFS)")
        return _save(fig)


def plot_spectrogram(analysis: dict[str, Any], width: float = 12.0, height: float = 4.5, log_frequency: bool = False) -> bytes:
    with PLOT_LOCK:
        fig, ax = _new_figure(width, height)
        spec = analysis.get("spectral", {}).get("spectrogram", {})
        if log_frequency:
            freqs = np.asarray(spec.get("log_frequencies_hz", []), dtype=float)
            matrix = np.asarray(spec.get("log_magnitude_db", []), dtype=float)
        else:
            freqs = np.asarray(spec.get("frequencies_hz", []), dtype=float)
            matrix = np.asarray(spec.get("magnitude_db", []), dtype=float)
        times = np.asarray(spec.get("times", []), dtype=float)
        if matrix.size == 0 or times.size == 0:
            ax.text(0.5, 0.5, "No spectrogram data", ha="center", va="center", transform=ax.transAxes)
        else:
            mesh = ax.pcolormesh(times, freqs, matrix, shading="auto", cmap="magma", vmin=-100, vmax=0, rasterized=True)
            if log_frequency:
                ax.set_yscale("log")
            ax.set_ylim(max(20, freqs[0]), min(20000, freqs[-1]))
            ax.set_xlim(0, max(times.max(), 0.01))
            cbar = fig.colorbar(mesh, ax=ax, pad=0.01, fraction=0.025)
            cbar.set_label("Magnitude (dBFS)", fontsize=8)
            cbar.ax.tick_params(labelsize=7)
            ax.set_xlabel("Time (s)")
            ax.set_ylabel("Frequency (Hz)")
        _style_axes(ax, f"Spectrogram — {_name(analysis)}", "Time (s)", "Frequency (Hz)")
        return _save(fig)


def plot_mel(analysis: dict[str, Any], width: float = 12.0, height: float = 4.0) -> bytes:
    with PLOT_LOCK:
        fig, ax = _new_figure(width, height)
        mel = analysis.get("spectral", {}).get("mel", {})
        times = np.asarray(mel.get("times", []), dtype=float)
        freqs = np.asarray(mel.get("frequencies_hz", []), dtype=float)
        matrix = np.asarray(mel.get("power_db", []), dtype=float)
        if matrix.size == 0 or times.size == 0:
            ax.text(0.5, 0.5, "No Mel data", ha="center", va="center", transform=ax.transAxes)
        else:
            mesh = ax.pcolormesh(times, freqs, matrix, shading="auto", cmap="viridis", vmin=-100, vmax=0, rasterized=True)
            ax.set_yscale("symlog", linthresh=100)
            ax.set_ylim(20, min(20000, freqs[-1]))
            ax.set_xlim(0, max(times.max(), 0.01))
            cbar = fig.colorbar(mesh, ax=ax, pad=0.01, fraction=0.025)
            cbar.set_label("Mel power (dB)", fontsize=8)
            cbar.ax.tick_params(labelsize=7)
        _style_axes(ax, f"Mel spectrogram — {_name(analysis)}", "Time (s)", "Frequency (Hz)")
        return _save(fig)


def plot_chroma(analysis: dict[str, Any], width: float = 12.0, height: float = 3.2) -> bytes:
    with PLOT_LOCK:
        fig, ax = _new_figure(width, height)
        chroma = analysis.get("spectral", {}).get("chroma", {})
        times = np.asarray(chroma.get("times", []), dtype=float)
        matrix = np.asarray(chroma.get("energy", []), dtype=float)
        classes = chroma.get("pitch_classes", [])
        if matrix.size == 0 or times.size == 0:
            ax.text(0.5, 0.5, "No chroma data", ha="center", va="center", transform=ax.transAxes)
        else:
            mesh = ax.pcolormesh(times, np.arange(12), matrix, shading="auto", cmap="YlGnBu", vmin=0, vmax=1, rasterized=True)
            ax.set_yticks(np.arange(12))
            ax.set_yticklabels(classes, fontsize=7)
            ax.set_xlim(0, max(times.max(), 0.01))
            cbar = fig.colorbar(mesh, ax=ax, pad=0.01, fraction=0.025)
            cbar.set_label("Chroma energy", fontsize=8)
            cbar.ax.tick_params(labelsize=7)
        _style_axes(ax, f"Chromagram — {_name(analysis)}", "Time (s)", "Pitch class")
        return _save(fig)


def plot_loudness(analysis: dict[str, Any], width: float = 12.0, height: float = 4.0) -> bytes:
    with PLOT_LOCK:
        fig, ax = _new_figure(width, height)
        loud = analysis.get("loudness", {})
        mo = loud.get("momentary", {})
        st = loud.get("short_term", {})
        ax.plot(_arr(mo.get("times")), _arr(mo.get("lufs")), color="#a0aec0", linewidth=0.7, label="Momentary (400 ms)")
        ax.plot(_arr(st.get("times")), _arr(st.get("lufs")), color="#2b6cb0", linewidth=1.6, label="Short-term (3 s)")
        integrated = loud.get("integrated_lufs")
        if integrated is not None:
            ax.axhline(integrated, color="#1f9d55", linewidth=1.2, linestyle="--", label=f"Integrated {integrated:.1f} LUFS")
        target = analysis.get("analysis_settings", {}).get("target_lufs")
        if target is not None:
            ax.axhline(target, color="#ed8936", linewidth=1.0, linestyle=":", label=f"Target {target:.1f} LUFS")
        limit = analysis.get("qc", {}).get("thresholds", {}).get("loudness_max_lufs")
        if limit is not None and st.get("lufs"):
            times = _arr(st.get("times"))
            values = _arr(st.get("lufs"))
            mask = np.nan_to_num(values, nan=-np.inf) > float(limit)
            if np.any(mask):
                ax.fill_between(times, values, float(limit), where=mask, color="#e53e3e", alpha=0.2, label="Above configured max")
        ax.set_xlabel("Time (s)")
        ax.set_ylabel("Loudness (LUFS)")
        ax.legend(loc="lower right", fontsize=7, frameon=False, ncol=2)
        _style_axes(ax, f"Loudness timeline — {_name(analysis)}", "Time (s)", "Loudness (LUFS)")
        return _save(fig)


def plot_rms_peak(analysis: dict[str, Any], width: float = 12.0, height: float = 4.0) -> bytes:
    with PLOT_LOCK:
        fig, ax = _new_figure(width, height)
        env = analysis.get("time_domain", {}).get("envelopes", {})
        times = np.asarray(env.get("times", []), dtype=float)
        rms = np.asarray(env.get("rms_db", []), dtype=float)
        peak = np.asarray(env.get("peak_db", []), dtype=float)
        ax.plot(times, rms, color="#2b6cb0", linewidth=1.0, label="RMS")
        ax.plot(times, peak, color="#c53030", linewidth=0.7, alpha=0.8, label="Sample peak")
        true_peak = analysis.get("loudness", {}).get("true_peak_dbtp")
        if true_peak is not None:
            ax.axhline(true_peak, color="#805ad5", linewidth=0.9, linestyle="--", label=f"True peak {true_peak:.1f} dBTP")
        ax.set_ylim(max(-100, float(np.nanmin(rms)) - 5) if rms.size else -100, 3)
        ax.set_xlabel("Time (s)")
        ax.set_ylabel("Level (dBFS / dBTP)")
        ax2 = ax.twinx()
        if rms.size == peak.size:
            crest = peak - rms
            ax2.plot(times, crest, color="#718096", linewidth=0.7, alpha=0.7, label="Crest factor")
            ax2.set_ylabel("Crest factor (dB)", fontsize=8.5, color="#4a5568")
            ax2.tick_params(labelsize=7, colors="#4a5568")
        ax.legend(loc="lower right", fontsize=7, frameon=False)
        _style_axes(ax, f"RMS, peak and crest factor — {_name(analysis)}", "Time (s)", "Level (dBFS)")
        return _save(fig)


def plot_bands(analysis: dict[str, Any], width: float = 10.0, height: float = 3.8) -> bytes:
    with PLOT_LOCK:
        fig, ax = _new_figure(width, height)
        bands = analysis.get("spectral", {}).get("bands", {}).get("bands", [])
        labels = [b["label"] for b in bands]
        shares = [b.get("relative_energy_pct") or 0.0 for b in bands]
        dbs = [b.get("average_db") for b in bands]
        bars = ax.bar(labels, shares, color="#4299e1", alpha=0.85)
        ax.set_ylabel("Share of energy (%)")
        ax.set_ylim(0, max(100, max(shares) * 1.15 if shares else 100))
        ax.tick_params(axis="x", rotation=20, labelsize=7.5)
        for bar, db_value in zip(bars, dbs):
            if db_value is not None:
                ax.annotate(f"{db_value:.1f} dB", (bar.get_x() + bar.get_width() / 2, bar.get_height()),
                            xytext=(0, 3), textcoords="offset points", ha="center", fontsize=6.5)
        _style_axes(ax, f"Frequency-band energy — {_name(analysis)}", None, "Share of energy (%)")
        return _save(fig)


def plot_vectorscope(analysis: dict[str, Any], width: float = 6.0, height: float = 5.0) -> bytes:
    with PLOT_LOCK:
        fig, ax = _new_figure(width, height)
        stereo = analysis.get("stereo", {})
        if not stereo.get("supported"):
            ax.text(0.5, 0.5, "Mono file\nNo stereo vectorscope", ha="center", va="center", transform=ax.transAxes, fontsize=12)
            ax.set_axis_off()
        else:
            scope = stereo.get("vectorscope", {})
            left = np.asarray(scope.get("left", []), dtype=float)
            right = np.asarray(scope.get("right", []), dtype=float)
            ax.scatter(left, right, s=1.2, color="#2b6cb0", alpha=0.35, linewidths=0)
            ax.axhline(0, color="#cbd5e0", linewidth=0.6)
            ax.axvline(0, color="#cbd5e0", linewidth=0.6)
            ax.plot([-1, 1], [-1, 1], color="#a0aec0", linewidth=0.6, linestyle="--")
            ax.plot([-1, 1], [1, -1], color="#e2e8f0", linewidth=0.6, linestyle=":")
            ax.set_xlim(-1.05, 1.05)
            ax.set_ylim(-1.05, 1.05)
            ax.set_aspect("equal")
            ax.set_xlabel("Left")
            ax.set_ylabel("Right")
            corr = stereo.get("correlation", {}).get("value")
            if corr is not None:
                ax.text(0.03, 0.97, f"r = {corr:.3f}", transform=ax.transAxes, va="top", fontsize=9,
                        bbox={"boxstyle": "round,pad=0.25", "facecolor": "#edf2f7", "edgecolor": "#cbd5e0"})
        _style_axes(ax, f"Stereo vectorscope — {_name(analysis)}", "Left amplitude", "Right amplitude")
        return _save(fig)


def plot_dynamics(analysis: dict[str, Any], width: float = 12.0, height: float = 4.2) -> bytes:
    with PLOT_LOCK:
        fig, ax = _new_figure(width, height)
        dyn = analysis.get("dynamics", {})
        tl = dyn.get("timeline", {})
        times = _arr(tl.get("times"))
        rms = _arr(tl.get("rms_db"))
        peak = _arr(tl.get("peak_db"))
        crest = _arr(tl.get("crest_db"))
        ax.plot(times, rms, color="#2b6cb0", linewidth=0.9, label="RMS")
        ax.plot(times, peak, color="#c53030", linewidth=0.6, alpha=0.7, label="Peak")
        for section in dyn.get("reduced_dynamic_sections", [])[:30]:
            ax.axvspan(section["start"], section["end"], color="#ed8936", alpha=0.13, linewidth=0)
        ax2 = ax.twinx()
        if crest.size == times.size:
            ax2.plot(times, crest, color="#6b46c1", linewidth=0.8, alpha=0.8, label="Crest")
            ax2.set_ylabel("Crest factor (dB)", fontsize=8.5, color="#553c9a")
            ax2.tick_params(labelsize=7, colors="#553c9a")
        ax.set_xlabel("Time (s)")
        ax.set_ylabel("Level (dBFS)")
        ax.legend(loc="lower right", fontsize=7, frameon=False)
        _style_axes(ax, f"Dynamic range — {_name(analysis)}", "Time (s)", "Level (dBFS)")
        return _save(fig)


def plot_tempo(analysis: dict[str, Any], width: float = 12.0, height: float = 5.2) -> bytes:
    with PLOT_LOCK:
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(width, height), dpi=130, sharex=True)
        fig.patch.set_facecolor("#ffffff")
        fig.subplots_adjust(left=0.075, right=0.985, top=0.91, bottom=0.1, hspace=0.18)
        rhythm = analysis.get("musical", {}).get("rhythm", {})
        env = rhythm.get("onset_envelope", {})
        times = np.asarray(env.get("times", []), dtype=float)
        values = np.asarray(env.get("values", []), dtype=float)
        ax1.plot(times, values, color="#2b6cb0", linewidth=0.7, label="Onset strength")
        for beat in analysis.get("musical", {}).get("tempo", {}).get("beats", [])[:800]:
            ax1.axvline(beat, color="#ed8936", alpha=0.4, linewidth=0.6)
        ax1.set_ylabel("Onset strength")
        ax1.legend(loc="upper right", fontsize=7, frameon=False)
        _style_axes(ax1, f"Tempo and beats — {_name(analysis)}", None, "Onset strength")
        local = analysis.get("musical", {}).get("tempo", {}).get("local_tempo", [])
        if local:
            ax2.plot([p["time"] for p in local], [p["bpm"] for p in local], color="#6b46c1", linewidth=1.0, marker=".", markersize=2, label="Local tempo")
        bpm = analysis.get("musical", {}).get("tempo", {}).get("bpm")
        if bpm:
            ax2.axhline(bpm, color="#1f9d55", linewidth=1.0, linestyle="--", label=f"Global {bpm:.1f} BPM")
        ax2.set_ylabel("Tempo (BPM)")
        ax2.set_xlabel("Time (s)")
        ax2.legend(loc="upper right", fontsize=7, frameon=False)
        _style_axes(ax2, None, "Time (s)", "Tempo (BPM)")
        return _save(fig)


def plot_pitch(analysis: dict[str, Any], width: float = 12.0, height: float = 5.0) -> bytes:
    with PLOT_LOCK:
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(width, height), dpi=130, gridspec_kw={"height_ratios": [2.2, 1]})
        fig.patch.set_facecolor("#ffffff")
        fig.subplots_adjust(left=0.075, right=0.985, top=0.9, bottom=0.12, hspace=0.35)
        pitch = analysis.get("musical", {}).get("pitch", {})
        if not pitch.get("supported"):
            ax1.text(0.5, 0.5, pitch.get("reason", "Pitch not available"), ha="center", va="center", transform=ax1.transAxes)
            ax1.set_axis_off()
            ax2.set_axis_off()
        else:
            contour = pitch.get("contour", {})
            times = np.asarray(contour.get("times", []), dtype=float)
            f0 = np.asarray([v if v is not None else np.nan for v in contour.get("f0_hz", [])], dtype=float)
            ax1.plot(times, f0, color="#2b6cb0", linewidth=1.0)
            ax1.set_ylabel("F0 (Hz)")
            ax1.set_yscale("log")
            ax1.set_ylim(max(50, np.nanmin(f0) * 0.85) if np.any(np.isfinite(f0)) else 50, min(2200, np.nanmax(f0) * 1.15) if np.any(np.isfinite(f0)) else 2200)
            dist = pitch.get("pitch_distribution", {})
            centers = np.asarray(dist.get("midi_centers", []), dtype=float)
            counts = np.asarray(dist.get("normalized", []), dtype=float)
            if centers.size:
                ax2.bar(centers, counts, width=0.8, color="#805ad5", alpha=0.8)
                ax2.set_xlabel("MIDI note number")
                ax2.set_ylabel("Proportion")
        _style_axes(ax1, f"Pitch contour and distribution — {_name(analysis)}", None, "F0 (Hz)")
        _style_axes(ax2, None, "MIDI note number", "Proportion")
        return _save(fig)


def plot_spectral_features(analysis: dict[str, Any], width: float = 12.0, height: float = 6.0) -> bytes:
    with PLOT_LOCK:
        fig, axes = plt.subplots(2, 3, figsize=(width, height), dpi=130)
        fig.patch.set_facecolor("#ffffff")
        fig.subplots_adjust(left=0.06, right=0.99, top=0.9, bottom=0.1, hspace=0.45, wspace=0.3)
        features = analysis.get("spectral", {}).get("spectral_features", {})
        specs = [
            ("centroid_hz", "Centroid (Hz)", "#2b6cb0"),
            ("bandwidth_hz", "Bandwidth (Hz)", "#2f855a"),
            ("rolloff85_hz", "Roll-off 85% (Hz)", "#b7791f"),
            ("flux", "Spectral flux", "#c53030"),
            ("flatness", "Flatness", "#6b46c1"),
            ("zero_crossing_rate", "Zero-crossing rate", "#0987a0"),
        ]
        for ax, (key, label, color) in zip(axes.flat, specs):
            series = features.get(key, {}).get("series", {})
            times = np.asarray(series.get("times", []), dtype=float)
            values = np.asarray(series.get("values", []), dtype=float)
            if times.size:
                ax.plot(times, values, color=color, linewidth=0.8)
            ax.set_title(label, fontsize=8.5, loc="left", fontweight="bold")
            ax.tick_params(labelsize=6.5)
            ax.grid(True, color="#e2e8f0", linewidth=0.5)
            for spine in ("top", "right"):
                ax.spines[spine].set_visible(False)
        fig.suptitle(f"Spectral features — {_name(analysis)}", fontsize=11, fontweight="bold", x=0.06, ha="left")
        return _save(fig)


def plot_stereo(analysis: dict[str, Any], width: float = 12.0, height: float = 5.5) -> bytes:
    with PLOT_LOCK:
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(width, height), dpi=130, gridspec_kw={"height_ratios": [1.2, 1]})
        fig.patch.set_facecolor("#ffffff")
        fig.subplots_adjust(left=0.075, right=0.985, top=0.91, bottom=0.1, hspace=0.35)
        stereo = analysis.get("stereo", {})
        if not stereo.get("supported"):
            ax1.text(0.5, 0.5, "Mono file — no artificial stereo measurements", ha="center", va="center", transform=ax1.transAxes)
            ax1.set_axis_off()
            ax2.set_axis_off()
        else:
            env = stereo.get("channel_envelope", {})
            times = np.asarray(env.get("times", []), dtype=float)
            left = np.asarray(env.get("left_db", []), dtype=float)
            right = np.asarray(env.get("right_db", []), dtype=float)
            ax1.plot(times, left, color="#2b6cb0", linewidth=0.7, label="Left")
            ax1.plot(times, right, color="#ed8936", linewidth=0.7, alpha=0.8, label="Right")
            ax1.set_ylabel("Sample level (dBFS)")
            ax1.legend(loc="upper right", fontsize=7, frameon=False)
            tl = stereo.get("timeline", {})
            tt = np.asarray(tl.get("times", []), dtype=float)
            corr = np.asarray(tl.get("correlation", []), dtype=float)
            width_vals = np.asarray(tl.get("width", []), dtype=float)
            ax2.plot(tt, corr, color="#1f9d55", linewidth=1.0, label="Correlation")
            ax2.axhline(0, color="#a0aec0", linewidth=0.6)
            ax2.set_ylim(-1.05, 1.05)
            ax2.set_ylabel("Correlation")
            ax2.set_xlabel("Time (s)")
            ax3 = ax2.twinx()
            ax3.plot(tt, width_vals, color="#6b46c1", linewidth=0.8, alpha=0.7, label="Side/mid ratio")
            ax3.set_ylabel("Side/mid ratio", fontsize=8.5, color="#553c9a")
            ax3.tick_params(labelsize=7, colors="#553c9a")
            ax2.legend(loc="lower left", fontsize=7, frameon=False)
        _style_axes(ax1, f"Stereo channels and correlation — {_name(analysis)}", None, "Sample level (dBFS)")
        _style_axes(ax2, None, "Time (s)", "Correlation")
        return _save(fig)


def plot_comparison_bands(analyses: list[dict[str, Any]], width: float = 11.0, height: float = 4.2) -> bytes:
    with PLOT_LOCK:
        fig, ax = _new_figure(width, height)
        if not analyses:
            ax.text(0.5, 0.5, "No files selected", ha="center", va="center", transform=ax.transAxes)
        else:
            labels = [b["label"] for b in analyses[0].get("spectral", {}).get("bands", {}).get("bands", [])]
            x = np.arange(len(labels))
            count = len(analyses)
            width_bar = 0.8 / max(1, count)
            palette = ["#2b6cb0", "#ed8936", "#38a169", "#805ad5", "#d53f8c", "#319795", "#b7791f", "#718096"]
            for index, analysis in enumerate(analyses):
                bands = analysis.get("spectral", {}).get("bands", {}).get("bands", [])
                values = [b.get("relative_energy_pct") or 0.0 for b in bands]
                ax.bar(x + (index - (count - 1) / 2) * width_bar, values, width_bar, label=_name(analysis), color=palette[index % len(palette)], alpha=0.85)
            ax.set_xticks(x)
            ax.set_xticklabels(labels, rotation=20, fontsize=7.5)
            ax.set_ylabel("Share of energy (%)")
            ax.legend(fontsize=7, frameon=False)
        _style_axes(ax, "Frequency-band comparison", None, "Share of energy (%)")
        return _save(fig)


def plot_comparison_loudness(analyses: list[dict[str, Any]], width: float = 12.0, height: float = 4.2) -> bytes:
    with PLOT_LOCK:
        fig, ax = _new_figure(width, height)
        palette = ["#2b6cb0", "#ed8936", "#38a169", "#805ad5", "#d53f8c", "#319795", "#b7791f", "#718096"]
        for index, analysis in enumerate(analyses):
            short = analysis.get("loudness", {}).get("short_term", {})
            ax.plot(_arr(short.get("times")), _arr(short.get("lufs")), color=palette[index % len(palette)], linewidth=1.2, label=_name(analysis))
        ax.set_xlabel("Time (s)")
        ax.set_ylabel("Short-term loudness (LUFS)")
        ax.legend(fontsize=7, frameon=False)
        _style_axes(ax, "Loudness comparison (short-term, unaligned)", "Time (s)", "Short-term loudness (LUFS)")
        return _save(fig)


def plot_comparison_spectrum(analyses: list[dict[str, Any]], width: float = 12.0, height: float = 4.2) -> bytes:
    with PLOT_LOCK:
        fig, ax = _new_figure(width, height)
        palette = ["#2b6cb0", "#ed8936", "#38a169", "#805ad5", "#d53f8c", "#319795", "#b7791f", "#718096"]
        for index, analysis in enumerate(analyses):
            fft = analysis.get("spectral", {}).get("fft", {})
            freqs = np.asarray(fft.get("frequencies_hz", []), dtype=float)
            values = np.asarray(fft.get("average_dbfs", []), dtype=float)
            if freqs.size:
                mask = freqs >= 20
                ax.plot(freqs[mask], values[mask], color=palette[index % len(palette)], linewidth=0.8, label=_name(analysis))
        ax.set_xscale("log")
        ax.set_xlim(20, 20000)
        ax.set_ylim(-120, 6)
        ax.set_xlabel("Frequency (Hz)")
        ax.set_ylabel("Amplitude (dBFS)")
        ax.legend(fontsize=7, frameon=False)
        _style_axes(ax, "Spectrum comparison", "Frequency (Hz)", "Amplitude (dBFS)")
        return _save(fig)


PLOT_BUILDERS = {
    "waveform": plot_waveform,
    "spectrum": plot_spectrum,
    "spectrogram": plot_spectrogram,
    "mel": plot_mel,
    "chroma": plot_chroma,
    "loudness": plot_loudness,
    "rms_peak": plot_rms_peak,
    "bands": plot_bands,
    "vectorscope": plot_vectorscope,
    "dynamics": plot_dynamics,
    "tempo": plot_tempo,
    "pitch": plot_pitch,
    "spectral_features": plot_spectral_features,
    "stereo": plot_stereo,
}


def render_plot(kind: str, analysis: dict[str, Any], **kwargs: Any) -> bytes:
    builder = PLOT_BUILDERS.get(kind)
    if not builder:
        raise ValueError(f"Unknown plot type '{kind}'")
    return builder(analysis, **kwargs)


def _flatten_analysis(analysis: dict[str, Any]) -> dict[str, Any]:
    meta = analysis.get("metadata", {})
    loud = analysis.get("loudness", {})
    td = analysis.get("time_domain", {})
    stereo = analysis.get("stereo", {})
    spectral = analysis.get("spectral", {})
    musical = analysis.get("musical", {})
    qc = analysis.get("qc", {})
    bands = {b["key"]: b.get("relative_energy_pct") for b in spectral.get("bands", {}).get("bands", [])}
    return {
        "file_id": analysis.get("file_id"),
        "file_name": analysis.get("original_name"),
        "format": meta.get("format"),
        "codec": meta.get("codec"),
        "container": meta.get("container"),
        "duration_s": meta.get("duration"),
        "sample_rate_hz": meta.get("sample_rate"),
        "bit_depth_bits": meta.get("bit_depth"),
        "bit_depth_source": meta.get("bit_depth_source"),
        "channels": meta.get("channels"),
        "channel_layout": meta.get("channel_layout"),
        "file_size_bytes": meta.get("size_bytes"),
        "bitrate_kbps": meta.get("bitrate_kbps"),
        "is_lossy": meta.get("is_lossy"),
        "integrated_lufs": loud.get("integrated_lufs"),
        "loudness_range_lu": loud.get("loudness_range_lu"),
        "true_peak_dbtp": loud.get("true_peak_dbtp"),
        "sample_peak_dbfs": loud.get("sample_peak_dbfs"),
        "rms_dbfs": loud.get("rms_dbfs"),
        "crest_factor_db": loud.get("crest_factor_db"),
        "peak_to_loudness_ratio_db": loud.get("peak_to_loudness_ratio_db"),
        "dc_offset": td.get("dc_offset", {}).get("max_abs"),
        "clipping_percent": td.get("clipping", {}).get("clipped_percent"),
        "silence_percent": td.get("silence", {}).get("percent"),
        "snr_db": td.get("noise", {}).get("snr_db"),
        "noise_floor_dbfs": td.get("noise", {}).get("noise_floor_dbfs"),
        "correlation": stereo.get("correlation", {}).get("value") if stereo.get("supported") else None,
        "stereo_width_percent": stereo.get("mid_side", {}).get("stereo_width_percent") if stereo.get("supported") else None,
        "channel_balance_db": stereo.get("balance", {}).get("balance_db") if stereo.get("supported") else None,
        "mono_fold_loss_db": stereo.get("mono_compatibility", {}).get("mono_loss_db") if stereo.get("supported") else None,
        "key": musical.get("key", {}).get("key"),
        "key_confidence": musical.get("key", {}).get("confidence"),
        "tempo_bpm": musical.get("tempo", {}).get("bpm"),
        "tempo_confidence": musical.get("tempo", {}).get("confidence"),
        "pitch_median_hz": musical.get("pitch", {}).get("f0_median_hz"),
        "spectral_centroid_hz": spectral.get("spectral_features", {}).get("centroid_hz", {}).get("mean"),
        "spectral_bandwidth_hz": spectral.get("spectral_features", {}).get("bandwidth_hz", {}).get("mean"),
        "spectral_rolloff85_hz": spectral.get("spectral_features", {}).get("rolloff85_hz", {}).get("mean"),
        "spectral_flatness": spectral.get("spectral_features", {}).get("flatness", {}).get("mean"),
        "zero_crossing_rate": spectral.get("spectral_features", {}).get("zero_crossing_rate", {}).get("mean"),
        "hnr_db": spectral.get("spectral_features", {}).get("harmonic_to_noise_ratio_db"),
        "gain_to_target_db": analysis.get("track_gain", {}).get("gain_db"),
        "expected_true_peak_dbtp": analysis.get("track_gain", {}).get("expected_true_peak_dbtp"),
        "qc_overall": qc.get("overall"),
        "qc_errors": qc.get("error_count"),
        "qc_warnings": qc.get("warning_count"),
        **{f"band_{key}_percent": value for key, value in bands.items()},
    }


_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _is_number(text: str) -> bool:
    try:
        float(text.replace(",", ""))
        return True
    except ValueError:
        return False


def _csv_safe(value: Any) -> Any:
    """Neutralise spreadsheet formula injection (CWE-1236).

    Text cells that start with a formula trigger are prefixed with an
    apostrophe; genuine numbers (including negative values) are unchanged.
    """
    if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES) and not _is_number(value):
        return "'" + value
    return value


def _csv_row(row: dict[str, Any]) -> dict[str, Any]:
    return {key: _csv_safe(value) for key, value in row.items()}


def build_csv(analyses: list[dict[str, Any]]) -> str:
    rows = [_flatten_analysis(analysis) for analysis in analyses]
    if not rows:
        return ""
    # Union of columns in first-seen order: files can differ in optional
    # columns (e.g. band energies), and taking only the first file's keys made
    # DictWriter raise ValueError (HTTP 500) for the whole export.
    fieldnames: list[str] = []
    for row in rows:
        fieldnames.extend(key for key in row if key not in fieldnames)
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(_csv_row(row))
    return output.getvalue()


def _cell(value: Any) -> Any:
    """Scalars as-is; structured values as JSON (never Python repr)."""
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False)
    return value


_SEVERITY_RANK = {"error": 0, "warning": 1, "information": 2, "normal": 3}


def build_qc_csv(analyses: list[dict[str, Any]]) -> str:
    """One row per QC check, passed checks included (an audit trail must show
    what was checked, not only what failed)."""
    output = io.StringIO()
    fields = [
        "file_id", "file_name", "severity", "category", "title", "message", "measured_value", "measured_unit",
        "threshold_value", "threshold_unit", "error_threshold_value", "limit", "time_positions",
        "recommendation", "confidence", "rule_id", "standard",
    ]
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for analysis in analyses:
        qc = analysis.get("qc", {})
        thresholds = qc.get("thresholds") or {}
        checks = qc.get("checks") or qc.get("findings", [])
        for check in sorted(checks, key=lambda c: (_SEVERITY_RANK.get(c.get("severity"), 9), c.get("category") or "", c.get("title") or "")):
            error = ERROR_LIMITS.get(str(check.get("id")))
            error_value = check.get("error_threshold_value", thresholds.get(error[0]) if error else None)
            writer.writerow(_csv_row({
                "file_id": analysis.get("file_id"),
                "file_name": analysis.get("original_name"),
                "severity": check.get("severity"),
                "category": check.get("category"),
                "title": check.get("title"),
                "message": check.get("message"),
                "measured_value": _cell(check.get("measured_value")),
                "measured_unit": check.get("measured_unit"),
                "threshold_value": _cell(check.get("threshold_value")),
                "threshold_unit": check.get("threshold_unit"),
                "error_threshold_value": error_value,
                "limit": describe_limit(check, thresholds),
                "time_positions": json.dumps(check.get("time_positions", []), ensure_ascii=False),
                "recommendation": check.get("recommendation"),
                "confidence": check.get("confidence"),
                "rule_id": check.get("id"),
                "standard": check.get("standard"),
            }))
    return output.getvalue()


def build_comparison_csv(comparison: dict[str, Any]) -> str:
    output = io.StringIO()
    files = comparison.get("files", [])
    # Column headers must be unique: two files with the same name previously
    # shared one dict key, so the second value overwrote the first.
    name_counts: dict[str, int] = {}
    for file in files:
        name_counts[file["name"]] = name_counts.get(file["name"], 0) + 1
    columns = [
        (file["id"], file["name"] if name_counts[file["name"]] == 1 else f"{file['name']} [{file['id'][-8:]}]")
        for file in files
    ]
    fixed = ["parameter", "group", "unit", "status", "deviation_status", "tolerance", "spread"]
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(fixed + [_csv_safe(label) for _fid, label in columns])
    for row in comparison.get("rows", []):
        values = [
            row["label"], row["group"], row["unit"], row["status"], row["deviation_status"],
            row.get("tolerance"), row.get("spread"),
        ] + [row.get("display", {}).get(fid, "") for fid, _label in columns]
        writer.writerow([_csv_safe(value) for value in values])
    return output.getvalue()


def build_json_report(session: dict[str, Any], analyses: list[dict[str, Any]], comparison: dict[str, Any] | None = None, qc_overrides: dict[str, Any] | None = None) -> str:
    payload = {
        "report_type": "combined_audio_analysis",
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "session": {
            "id": session.get("id"),
            "name": session.get("name"),
            "created_at": session.get("created_at"),
            "settings": session.get("settings", {}),
        },
        "files": analyses,
        "comparison": comparison,
        # The full threshold set the QC results were computed with (session
        # defaults merged with any user changes).
        "qc_thresholds": qc_overrides or {},
        "qc_threshold_overrides": qc_overrides or {},
        "disclaimer": "Measurements are computed from the uploaded audio. Estimated values are labelled; no processing is applied to the original files.",
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _escape(text: str) -> str:
    """Escape text for ReportLab's mini-markup (user-supplied names!)."""
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _value_text(value: Any, unit: str = "", missing: str = "not available") -> str:
    """Format a measurement, stating explicitly when it is unavailable."""
    if value is None:
        return missing
    if isinstance(value, float):
        text = f"{value:.2f}"
    else:
        text = str(value)
    return f"{text} {unit}".strip()


def _paragraph(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(_escape(text), style)


def _rich_paragraph(title: str, body: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(f"<b>{_escape(title)}</b> — {_escape(body)}", style)


def _number_text(value: float | int) -> str:
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, int):
        return f"{value:,}"
    text = f"{value:,.4f}".rstrip("0").rstrip(".")
    return "0" if text in {"-0", ""} else text


def _mapping_text(value: dict[str, Any]) -> str:
    peaks = value.get("peaks")
    if isinstance(peaks, list):
        if not peaks:
            return "no peaks"
        strongest = max(peaks, key=lambda peak: abs(peak.get("amplitude_dbfs") or 0))
        return f"{len(peaks)} peaks · strongest {_number_text(strongest.get('frequency_hz') or 0)} Hz"
    bands = value.get("bands")
    if isinstance(bands, list):
        if not bands:
            return "no bands"
        worst = max(bands, key=lambda band: abs(band.get("variation_db") or 0))
        return (
            f"{len(bands)} bands · max variation "
            f"{_number_text(worst.get('variation_db') or 0)} dB ({worst.get('band')})"
        )
    parts = [
        f"{key.replace('_', ' ')} {_number_text(item)}"
        for key, item in value.items()
        if isinstance(item, (int, float)) and not isinstance(item, bool)
    ]
    return "; ".join(parts) if parts else "—"


def _measurement_text(value: Any, unit: str | None = None) -> str:
    if value is None:
        return "—"
    if isinstance(value, (bool, int, float)):
        text = _number_text(value)
    elif isinstance(value, dict):
        text = _mapping_text(value)
    elif isinstance(value, (list, tuple)):
        text = ", ".join(_measurement_text(item) for item in value[:6]) + ("…" if len(value) > 6 else "")
    else:
        text = str(value)
    return f"{text} {unit}".strip() if unit else text


def _jpeg_for_pdf(png_bytes: bytes) -> io.BytesIO:
    """Convert a rendered PNG to a compact JPEG for embedding in PDFs."""
    image = PILImage.open(io.BytesIO(png_bytes)).convert("RGB")
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=86, optimize=True)
    buffer.seek(0)
    return buffer


def build_pdf(session: dict[str, Any], analyses: list[dict[str, Any]], comparison: dict[str, Any] | None = None, qc_overrides: dict[str, Any] | None = None) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=1.5 * cm, rightMargin=1.5 * cm,
        topMargin=1.5 * cm, bottomMargin=1.5 * cm,
        title="Audio Analysis Report",
        author="Audio Analysis Pipeline",
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="AAPTitle", parent=styles["Title"], fontSize=24, leading=28, textColor=colors.HexColor("#1a365d"), spaceAfter=12))
    styles.add(ParagraphStyle(name="AAPSubtitle", parent=styles["Normal"], fontSize=11, textColor=colors.HexColor("#4a5568"), spaceAfter=18))
    styles.add(ParagraphStyle(name="AAPHeading", parent=styles["Heading2"], fontSize=14, leading=17, textColor=colors.HexColor("#1a365d"), spaceBefore=10, spaceAfter=6))
    styles.add(ParagraphStyle(name="AAPSmall", parent=styles["Normal"], fontSize=7.5, leading=9.5, textColor=colors.HexColor("#2d3748")))
    styles.add(ParagraphStyle(name="AAPSmallBold", parent=styles["AAPSmall"], fontName="Helvetica-Bold"))
    styles.add(ParagraphStyle(name="AAPTableHead", parent=styles["AAPSmallBold"], textColor=colors.white))
    styles.add(ParagraphStyle(name="AAPBody", parent=styles["Normal"], fontSize=9, leading=12, textColor=colors.HexColor("#2d3748")))
    story: list[Any] = []
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    story.append(Spacer(1, 3 * cm))
    story.append(Paragraph("Audio Analysis Report", styles["AAPTitle"]))
    story.append(Paragraph(_escape(f"{session.get('name') or 'Analysis session'} · {len(analyses)} file(s) · {generated}"), styles["AAPSubtitle"]))
    story.append(Paragraph(
        "Technical, musical, spectral, loudness, dynamic and stereo analysis with automated quality control. "
        "All measurements are derived from the uploaded audio; estimated values are explicitly labelled.",
        styles["AAPBody"],
    ))
    story.append(Spacer(1, 1.0 * cm))

    overview_rows = [["File", "Format", "Sample rate", "Bit depth", "Channels", "Duration", "Integrated", "True peak", "QC"]]
    for analysis in analyses:
        meta = analysis.get("metadata", {})
        loud = analysis.get("loudness", {})
        qc = analysis.get("qc", {})
        overview_rows.append([
            _paragraph(analysis.get("original_name", "—"), styles["AAPSmall"]),
            _paragraph(str(meta.get("format", "—")), styles["AAPSmall"]),
            _paragraph(f"{meta.get('sample_rate', '—')} Hz", styles["AAPSmall"]),
            _paragraph(str(meta.get("bit_depth") or "n/a"), styles["AAPSmall"]),
            _paragraph(str(meta.get("channels", "—")), styles["AAPSmall"]),
            _paragraph(f"{meta.get('duration', 0):.2f} s", styles["AAPSmall"]),
            _paragraph(_value_text(loud.get('integrated_lufs'), "LUFS"), styles["AAPSmall"]),
            _paragraph(_value_text(loud.get('true_peak_dbtp'), "dBTP"), styles["AAPSmall"]),
            _paragraph(qc.get("overall_label", "—"), styles["AAPSmall"]),
        ])
    overview = Table(overview_rows, repeatRows=1, colWidths=[3.2 * cm, 1.6 * cm, 1.9 * cm, 1.5 * cm, 1.5 * cm, 1.7 * cm, 2.1 * cm, 1.9 * cm, 1.6 * cm])
    overview.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a365d")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 7.5),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#cbd5e0")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7fafc")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(overview)
    story.append(Spacer(1, 0.6 * cm))
    story.append(Paragraph(
        "Confidence: file properties, sample peak, true peak, RMS, loudness, LRA, clipping, silence, correlation and mid/side energy are direct measurements. "
        "Key, tempo/beats, pitch, noise floor/SNR and harmonic/percussive separation are algorithmic estimates and are labelled accordingly.",
        styles["AAPSmall"],
    ))
    story.append(PageBreak())

    for analysis in analyses:
        meta = analysis.get("metadata", {})
        loud = analysis.get("loudness", {})
        stereo = analysis.get("stereo", {})
        musical = analysis.get("musical", {})
        qc = analysis.get("qc", {})
        story.append(Paragraph("File: " + _escape(analysis.get("original_name", "Audio")), styles["AAPHeading"]))
        bit_depth_text = (
            f"{meta.get('bit_depth')} bits" + (f" ({meta.get('bit_depth_source')})" if meta.get('bit_depth_source') else "")
            if meta.get("bit_depth") else ("not applicable (lossy codec)" if meta.get("is_lossy") else "not determined")
        )
        info_rows = [
            ["File name", analysis.get("original_name") or "—", "Format", meta.get("format") or "—"],
            ["Duration", f"{float(meta.get('duration') or 0):.3f} s", "File size", meta.get("size_human") or "—"],
            ["Sample rate", _value_text(meta.get('sample_rate'), "Hz"), "Channels", str(meta.get("channels") or "—")],
            ["Bit depth", bit_depth_text, "Codec", meta.get("codec") or "—"],
            ["Encoded bitrate", _value_text(meta.get('bitrate_kbps'), "kbps"), "Lossy", "Yes" if meta.get("is_lossy") else "No"],
        ]
        info_table = Table([[Paragraph(_escape(a), styles["AAPSmallBold"]), Paragraph(_escape(str(b)), styles["AAPSmall"]), Paragraph(_escape(c), styles["AAPSmallBold"]), Paragraph(_escape(str(d)), styles["AAPSmall"])] for a, b, c, d in info_rows],
                           colWidths=[2.6 * cm, 5.4 * cm, 2.6 * cm, 7.0 * cm])
        info_table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#e2e8f0")),
            ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f7fafc")),
            ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#f7fafc")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(info_table)
        story.append(Spacer(1, 0.35 * cm))
        key_info = musical.get("key", {})
        tempo_info = musical.get("tempo", {})
        metric_rows = [
            ["Integrated loudness", _value_text(loud.get('integrated_lufs'), "LUFS", missing="not measurable (below gate)"), "Loudness range", _value_text(loud.get('loudness_range_lu'), "LU")],
            ["True peak", _value_text(loud.get('true_peak_dbtp'), "dBTP"), "Sample peak", _value_text(loud.get('sample_peak_dbfs'), "dBFS")],
            ["RMS", _value_text(loud.get('rms_dbfs'), "dBFS"), "Crest factor", _value_text(loud.get('crest_factor_db'), "dB")],
            ["Peak-to-loudness ratio", _value_text(loud.get('peak_to_loudness_ratio_db'), "dB"), "Stereo correlation", (_value_text(stereo.get('correlation', {}).get('value'), missing="undefined") if stereo.get('supported') else 'mono')],
            ["Estimated key", (f"{key_info.get('key')} ({key_info.get('confidence_label', 'unknown')} confidence)" if key_info.get('key') else "not estimated"), "Estimated tempo", (f"{_value_text(tempo_info.get('bpm'), 'BPM')} ({tempo_info.get('confidence_label', 'unknown')} confidence)" if tempo_info.get('bpm') else "not estimated")],
            ["QC result", f"{qc.get('overall_label', '—')}", "Findings", f"{qc.get('error_count', 0)} errors / {qc.get('warning_count', 0)} warnings"],
        ]
        metrics_table = Table([[Paragraph(_escape(a), styles["AAPSmallBold"]), Paragraph(_escape(str(b)), styles["AAPSmall"]), Paragraph(_escape(c), styles["AAPSmallBold"]), Paragraph(_escape(str(d)), styles["AAPSmall"])] for a, b, c, d in metric_rows],
                              colWidths=[3.6 * cm, 4.4 * cm, 3.6 * cm, 6.0 * cm])
        metrics_table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#e2e8f0")),
            ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f7fafc")),
            ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#f7fafc")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(metrics_table)
        story.append(Spacer(1, 0.4 * cm))
        if analysis.get("recommendations"):
            story.append(Paragraph("Measurement-based recommendations", styles["AAPHeading"]))
            for rec in analysis["recommendations"][:8]:
                story.append(_rich_paragraph(
                    rec.get("title") or "Recommendation",
                    f"{rec.get('supporting_measurement') or ''} {rec.get('recommendation') or ''}".strip(),
                    styles["AAPSmall"],
                ))
                story.append(Spacer(1, 0.08 * cm))
        story.append(PageBreak())

        plot_jobs = [
            ("Waveform", plot_waveform, 6.1 * cm),
            ("FFT spectrum", plot_spectrum, 6.2 * cm),
            ("Spectrogram", plot_spectrogram, 7.0 * cm),
            ("Mel spectrogram", plot_mel, 6.2 * cm),
            ("Chromagram", plot_chroma, 5.4 * cm),
            ("Loudness timeline", plot_loudness, 6.2 * cm),
            ("RMS, peak and crest", plot_rms_peak, 6.2 * cm),
            ("Frequency-band energy", plot_bands, 5.8 * cm),
            ("Stereo vectorscope", plot_vectorscope, 6.4 * cm),
            ("Dynamic range", plot_dynamics, 6.2 * cm),
            ("Tempo and beats", plot_tempo, 7.2 * cm),
        ]
        for label, builder, image_height in plot_jobs:
            try:
                figure_height = max(2.6, 11.0 * image_height / (17.0 * cm))
                image_bytes = builder(analysis, width=11.0, height=figure_height)
                story.append(KeepTogether([
                    Paragraph(label, styles["AAPSmallBold"]),
                    RLImage(_jpeg_for_pdf(image_bytes), width=17.0 * cm, height=image_height),
                    Spacer(1, 0.25 * cm),
                ]))
            except Exception as exc:
                story.append(_paragraph(f"Plot unavailable: {exc}", styles["AAPSmall"]))
        story.append(PageBreak())

        story.append(Paragraph("Quality control", styles["AAPHeading"]))
        if qc.get("findings"):
            qc_rows = [[
                Paragraph("Severity", styles["AAPTableHead"]), Paragraph("Check", styles["AAPTableHead"]),
                Paragraph("Measured", styles["AAPTableHead"]), Paragraph("Limit", styles["AAPTableHead"]),
                Paragraph("Action", styles["AAPTableHead"]),
            ]]
            for finding in qc["findings"][:PDF_MAX_QC_ROWS]:
                measured = _measurement_text(finding.get("measured_value"), finding.get("measured_unit"))
                # Name the limit that was actually crossed (critical findings
                # previously printed the warning limit).
                limit_text = describe_limit(finding, qc.get("thresholds")) or "—"
                qc_rows.append([
                    _paragraph(finding.get("status_label", ""), styles["AAPSmall"]),
                    _paragraph(f"{finding.get('title')}: {finding.get('message')}", styles["AAPSmall"]),
                    _paragraph(measured, styles["AAPSmall"]),
                    _paragraph(limit_text, styles["AAPSmall"]),
                    _paragraph(finding.get("recommendation", ""), styles["AAPSmall"]),
                ])
            table = Table(qc_rows, repeatRows=1, colWidths=[1.8 * cm, 5.4 * cm, 2.7 * cm, 2.7 * cm, 5.0 * cm])
            table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a365d")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#cbd5e0")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]))
            story.append(table)
            if len(qc["findings"]) > PDF_MAX_QC_ROWS:
                story.append(_paragraph(
                    f"{len(qc['findings']) - PDF_MAX_QC_ROWS} further finding(s) are not listed here; the QC findings CSV contains every check.",
                    styles["AAPSmall"],
                ))
        else:
            story.append(Paragraph("No findings outside the configured thresholds.", styles["AAPBody"]))
        story.append(PageBreak())

    if comparison:
        story.append(Paragraph("Multi-file comparison", styles["AAPHeading"]))
        story.append(_paragraph(comparison.get("method", ""), styles["AAPSmall"]))
        story.append(Spacer(1, 0.25 * cm))
        rows = [[Paragraph("Parameter", styles["AAPTableHead"]), Paragraph("File", styles["AAPTableHead"]), Paragraph("Value", styles["AAPTableHead"]), Paragraph("Status", styles["AAPTableHead"])]]
        files = comparison.get("files", [])
        comparison_rows = comparison.get("rows", [])
        for row in comparison_rows[:PDF_MAX_COMPARISON_ROWS]:
            for file in files:
                rows.append([
                    _paragraph(row["label"], styles["AAPSmall"]),
                    _paragraph(file["name"], styles["AAPSmall"]),
                    _paragraph(str(row.get("display", {}).get(file["id"], "—")), styles["AAPSmall"]),
                    _paragraph(row.get("status", "").replace("_", " ").title(), styles["AAPSmall"]),
                ])
        table = Table(rows, repeatRows=1, colWidths=[5.0 * cm, 5.5 * cm, 3.2 * cm, 3.9 * cm])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a365d")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#cbd5e0")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]))
        story.append(table)
        if len(comparison_rows) > PDF_MAX_COMPARISON_ROWS:
            story.append(_paragraph(
                f"{len(comparison_rows) - PDF_MAX_COMPARISON_ROWS} further parameter(s) are not listed here; the comparison CSV contains all of them.",
                styles["AAPSmall"],
            ))
        story.append(Spacer(1, 0.5 * cm))
        if comparison.get("findings"):
            story.append(Paragraph("Cross-file findings", styles["AAPHeading"]))
            for finding in comparison["findings"]:
                story.append(_rich_paragraph(
                    finding.get("title") or "Finding",
                    f"{finding.get('message') or ''} {finding.get('recommendation') or ''}".strip(),
                    styles["AAPSmall"],
                ))
                story.append(Spacer(1, 0.1 * cm))
        try:
            for heading, builder in (
                ("Frequency-band comparison", plot_comparison_bands),
                ("Spectrum comparison", plot_comparison_spectrum),
                ("Loudness comparison", plot_comparison_loudness),
            ):
                story.append(KeepTogether([
                    Paragraph(heading, styles["AAPHeading"]),
                    RLImage(_jpeg_for_pdf(builder(analyses)), width=17.0 * cm, height=6.2 * cm),
                    Spacer(1, 0.2 * cm),
                ]))
        except Exception as exc:
            story.append(_paragraph(f"Comparison plots unavailable: {exc}", styles["AAPSmall"]))
        story.append(PageBreak())

    story.append(Paragraph("Methodology and measurement settings", styles["AAPHeading"]))
    story.append(Paragraph(
        "Loudness: ITU-R BS.1770-4 / EBU R128 with K-weighting, 400 ms momentary blocks, 3 s short-term blocks, absolute -70 LUFS and relative gating; "
        "true peak uses 4x polyphase oversampling. Loudness range follows EBU Tech 3342.",
        styles["AAPSmall"],
    ))
    story.append(Paragraph(
        "Spectrum: STFT with a periodic Hann window at the file's native sample rate. FFT bin width is sample_rate / n_fft. "
        "Spectrogram and Mel displays are aggregated from the measured STFT; no synthetic data is used. "
        "Chroma is computed from the same STFT. Key uses Krumhansl-Schmuckler profiles, tempo uses librosa's beat tracker and tempogram, "
        "and pitch uses probabilistic YIN on the most energetic segment.",
        styles["AAPSmall"],
    ))
    story.append(Paragraph(
        "Stereo: Pearson correlation, mid/side RMS, mono fold-down loss, and windowed correlation/width timelines. Mono files are reported as mono without fabricated stereo values.",
        styles["AAPSmall"],
    ))
    story.append(Paragraph(
        "Quality control: every check compares a measured value with an explicit threshold. 'Error' is only used when the configured error threshold is crossed. "
        "Information findings are context, not defects. Thresholds can be changed in the application settings.",
        styles["AAPSmall"],
    ))
    if qc_overrides:
        story.append(Paragraph(_escape("Custom QC overrides: " + json.dumps(qc_overrides, ensure_ascii=False)), styles["AAPSmall"]))
    story.append(Spacer(1, 0.5 * cm))
    story.append(Paragraph(
        "The original uploads were preserved throughout. No gain, EQ, limiting or other processing was applied. "
        "Gain values are preview calculations only. Estimated measurements should be verified against a reference when used for critical decisions.",
        styles["AAPSmall"],
    ))

    def add_page_number(canvas, doc_obj):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#718096"))
        canvas.drawRightString(A4[0] - 1.5 * cm, 0.9 * cm, f"Page {doc_obj.page}")
        canvas.drawString(1.5 * cm, 0.9 * cm, "Audio Analysis Pipeline")
        canvas.restoreState()

    doc.build(story, onFirstPage=add_page_number, onLaterPages=add_page_number)
    buffer.seek(0)
    return buffer.getvalue()
