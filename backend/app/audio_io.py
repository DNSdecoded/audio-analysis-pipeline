"""Audio decoding and metadata probing.

libsndfile (through *soundfile*) handles WAV/AIFF/FLAC/OGG/MP3.  PyAV provides a
bundled FFmpeg decoder for AAC/MP4 and as a fallback for unusual containers.
The original file is only ever opened for reading.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

try:  # PyAV is optional at import time so the API can still start without it
    import av
except Exception:  # pragma: no cover - only on unusual installations
    av = None  # type: ignore[assignment]


PCM_SUBTYPES = {
    "PCM_S8": 8, "PCM_U8": 8, "PCM_16": 16, "PCM_24": 24, "PCM_32": 32,
    "FLOAT": 32, "DOUBLE": 64,
}


class DecodeError(Exception):
    pass


def _human_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 ** 2:
        return f"{size / 1024:.1f} KB"
    if size < 1024 ** 3:
        return f"{size / 1024 ** 2:.1f} MB"
    return f"{size / 1024 ** 3:.2f} GB"


def _sf_info(path: Path) -> dict[str, Any] | None:
    try:
        info = sf.info(str(path))
        return {
            "format": info.format,
            "subtype": info.subtype,
            "subtype_info": info.subtype_info,
            "sample_rate": int(info.samplerate),
            "channels": int(info.channels),
            "frames": int(info.frames),
            "duration": float(info.duration),
        }
    except Exception:
        return None


def _alac_bit_depth(codec: Any) -> int:
    """Read the source bit depth from the ALAC magic cookie (extradata).

    Older PyAV releases do not expose ``bits_per_raw_sample``. The cookie holds an
    ALACSpecificConfig: frameLength(4) compatibleVersion(1) bitDepth(1) ..., optionally
    wrapped in a 12-byte ``alac`` atom header.
    """
    try:
        extra = bytes(codec.extradata or b"")
    except Exception:
        return 0
    offset = 12 if extra[4:8] == b"alac" else 0
    return extra[offset + 5] if len(extra) > offset + 5 else 0


def _av_info(path: Path) -> dict[str, Any] | None:
    if av is None:
        return None
    try:
        with av.open(str(path)) as container:
            stream = next((s for s in container.streams if s.type == "audio"), None)
            if stream is None:
                return None
            duration = None
            if stream.duration is not None and stream.time_base is not None:
                duration = float(stream.duration * stream.time_base)
            elif container.duration:
                duration = float(container.duration / av.time_base)
            codec = stream.codec_context
            return {
                "container": container.format.name if container.format else None,
                "codec": codec.name,
                "sample_rate": int(stream.rate or codec.sample_rate or 0),
                "channels": int(stream.channels or codec.channels or 0),
                "channel_layout": getattr(stream.layout, "name", None) if stream.layout else None,
                "bit_rate": int(stream.bit_rate) if stream.bit_rate else None,
                "bits_per_raw_sample": int(getattr(codec, "bits_per_raw_sample", 0) or 0)
                or (_alac_bit_depth(codec) if codec.name == "alac" else 0),
                "duration": duration,
            }
    except Exception:
        return None


def probe_audio(path: Path, ext: str, size_bytes: int | None = None) -> dict[str, Any]:
    """Return technical metadata without decoding the full signal."""
    path = Path(path)
    size = int(size_bytes if size_bytes is not None else path.stat().st_size)
    sf_info = _sf_info(path)
    av_info = _av_info(path)
    if sf_info is None and av_info is None:
        raise DecodeError("The file could not be opened by any supported audio decoder")

    fmt = (sf_info or {}).get("format")
    container = (av_info or {}).get("container") or fmt
    codec = (av_info or {}).get("codec")
    if not codec:
        subtype = (sf_info or {}).get("subtype", "")
        codec = subtype or fmt
    sample_rate = int((sf_info or {}).get("sample_rate") or (av_info or {}).get("sample_rate") or 0)
    channels = int((sf_info or {}).get("channels") or (av_info or {}).get("channels") or 0)
    frames = int((sf_info or {}).get("frames") or 0)
    duration = float((sf_info or {}).get("duration") or (av_info or {}).get("duration") or 0.0)
    if duration <= 0 and sample_rate > 0 and frames > 0:
        duration = frames / sample_rate
    if frames <= 0 and sample_rate > 0 and duration > 0:
        frames = int(round(duration * sample_rate))

    subtype = (sf_info or {}).get("subtype") or ""
    is_pcm = subtype in PCM_SUBTYPES or subtype.startswith("PCM_")
    bit_depth = PCM_SUBTYPES.get(subtype) if is_pcm else None
    bit_depth_source = "pcm" if bit_depth else None
    bit_depth_note = None
    if subtype == "MPEG_LAYER_III" or (codec or "").lower().startswith("mp3"):
        bit_depth_note = "MP3 is a lossy codec; no original PCM bit depth exists."
    elif subtype == "VORBIS" or (codec or "").lower() == "vorbis":
        bit_depth_note = "Vorbis is a lossy codec; no original PCM bit depth exists."
    elif (codec or "").lower() in {"aac", "opus", "mp3float", "mp3"}:
        bit_depth_note = f"{codec} is a lossy codec; no original PCM bit depth exists."
    elif subtype == "FLAC" or (codec or "").lower() == "flac":
        # soundfile reports FLAC as PCM_xx with the stored bit depth
        bit_depth_source = "lossless"
        bit_depth_note = "Lossless FLAC stream; bit depth is the encoded source depth."
    elif (codec or "").lower() == "alac":
        raw_bits = int((av_info or {}).get("bits_per_raw_sample") or 0)
        if raw_bits in (16, 20, 24, 32):
            bit_depth = raw_bits
            bit_depth_source = "lossless"
            bit_depth_note = "Lossless ALAC stream; bit depth is the encoded source depth."

    bitrate_kbps = None
    bitrate_source = None
    if duration > 0 and size > 0:
        bitrate_kbps = round((size * 8 / duration) / 1000.0, 1)
        bitrate_source = "container (file size / duration)"
    if av_info and av_info.get("bit_rate"):
        bitrate_kbps = round(av_info["bit_rate"] / 1000.0, 1)
        bitrate_source = "codec stream"

    lossy = not is_pcm and (codec or "").lower() not in {"flac", "alac"}
    if (codec or "").lower() in {"mp3", "mp3float", "aac", "vorbis", "opus"}:
        lossy = True

    metadata = {
        "format": (sf_info or {}).get("format") or (container or "").upper(),
        "container": container,
        "codec": codec,
        "codec_long_name": (sf_info or {}).get("subtype_info") or codec,
        "sample_rate": sample_rate,
        "channels": channels,
        "channel_layout": (av_info or {}).get("channel_layout"),
        "frames": frames,
        "duration": round(duration, 6),
        "bit_depth": bit_depth,
        "bit_depth_source": bit_depth_source,
        "bit_depth_note": bit_depth_note,
        "bitrate_kbps": bitrate_kbps,
        "bitrate_source": bitrate_source,
        "size_bytes": size,
        "size_human": _human_size(size),
        "is_lossy": bool(lossy),
        "subtype": subtype or None,
        "decoder": "libsndfile" if sf_info else "PyAV/FFmpeg",
        "channels_label": _channels_label(channels, (av_info or {}).get("channel_layout")),
    }
    if sample_rate <= 0:
        raise DecodeError("Invalid or missing sample rate")
    if channels <= 0:
        raise DecodeError("Invalid or missing channel count")
    if frames <= 0 or duration <= 0:
        raise DecodeError("The file contains no decodable audio samples")
    return metadata


def _channels_label(channels: int, layout: str | None) -> str:
    if channels == 1:
        return "Mono"
    if channels == 2:
        return "Stereo"
    if layout:
        return f"{channels} channels ({layout})"
    return f"{channels} channels"


def _decode_with_soundfile(path: Path) -> tuple[np.ndarray, int]:
    data, sr = sf.read(str(path), dtype="float32", always_2d=True)
    if data.size == 0:
        raise DecodeError("No audio samples decoded")
    return np.ascontiguousarray(data, dtype=np.float32), int(sr)


def _scale_to_float(arr: np.ndarray) -> np.ndarray:
    """Convert decoded PCM of any FFmpeg sample format to float in [-1, 1).

    FFmpeg decoders emit float formats for most lossy codecs but integer
    formats (s16/s16p, s32/s32p, u8/u8p) for ALAC, PCM-in-MP4/MOV and others.
    Integer samples must be scaled by their full-scale value; casting them to
    float directly produces amplitudes in the thousands.
    """
    if np.issubdtype(arr.dtype, np.floating):
        return arr.astype(np.float32, copy=False)
    if arr.dtype == np.uint8:
        return ((arr.astype(np.float32) - 128.0) / 128.0)
    if np.issubdtype(arr.dtype, np.signedinteger):
        full_scale = float(2 ** (8 * arr.dtype.itemsize - 1))
        return (arr.astype(np.float64) / full_scale).astype(np.float32)
    raise DecodeError(f"Unsupported decoded sample type: {arr.dtype}")


def _frame_to_array(frame: Any) -> np.ndarray:
    arr = _scale_to_float(np.asarray(frame.to_ndarray()))
    channels = int(frame.layout.nb_channels) if frame.layout else 1
    if frame.format.is_planar:
        if arr.ndim == 1:
            arr = arr.reshape(1, -1)
        # shape is (channels, samples)
        return arr
    # packed interleaved: shape (1, samples * channels)
    flat = arr.reshape(-1)
    if channels <= 1:
        return flat.reshape(1, -1)
    usable = (flat.size // channels) * channels
    return flat[:usable].reshape(-1, channels).T


def _decode_with_av(path: Path) -> tuple[np.ndarray, int]:
    if av is None:
        raise DecodeError("PyAV/FFmpeg is not installed")
    chunks: list[np.ndarray] = []
    sample_rate = 0
    channels = 0
    try:
        with av.open(str(path)) as container:
            stream = next((s for s in container.streams if s.type == "audio"), None)
            if stream is None:
                raise DecodeError("No audio stream found")
            sample_rate = int(stream.rate or stream.codec_context.sample_rate or 0)
            channels = int(stream.channels or stream.codec_context.channels or 0)
            for frame in container.decode(stream):
                if sample_rate <= 0:
                    sample_rate = int(frame.sample_rate or 0)
                if channels <= 0:
                    channels = int(frame.layout.nb_channels) if frame.layout else 1
                arr = _frame_to_array(frame)
                if arr.size:
                    chunks.append(arr)
    except DecodeError:
        raise
    except Exception as exc:
        raise DecodeError(f"Decoding failed: {exc}") from exc
    if not chunks:
        raise DecodeError("No audio samples decoded")
    # Normalise channel count defensively.
    max_channels = max(chunk.shape[0] for chunk in chunks)
    normalised = []
    for chunk in chunks:
        if chunk.shape[0] < max_channels:
            pad = np.zeros((max_channels - chunk.shape[0], chunk.shape[1]), dtype=np.float32)
            chunk = np.vstack([chunk, pad])
        elif chunk.shape[0] > max_channels:
            chunk = chunk[:max_channels]
        normalised.append(chunk)
    data = np.concatenate(normalised, axis=1).T
    if sample_rate <= 0:
        raise DecodeError("Invalid sample rate in decoded stream")
    return np.ascontiguousarray(data, dtype=np.float32), sample_rate


def _public_error(exc: Exception, path: Path) -> str:
    """Decoder messages embed the absolute storage path; never expose it."""
    text = str(exc)
    for variant in {str(path), str(path).replace("\\", "\\\\"), path.as_posix()}:
        text = text.replace(variant, path.name)
    return text


def decode_audio(path: Path, ext: str | None = None) -> tuple[np.ndarray, int, list[str]]:
    """Decode an audio file to float32 (samples, channels).

    The returned array is a decoded copy; the source file is untouched.
    """
    path = Path(path)
    warnings: list[str] = []
    errors: list[str] = []
    data: np.ndarray | None = None
    sr = 0
    try:
        data, sr = _decode_with_soundfile(path)
    except Exception as exc:
        errors.append(f"libsndfile: {_public_error(exc, path)}")
    if data is None:
        try:
            data, sr = _decode_with_av(path)
        except Exception as exc:
            errors.append(f"FFmpeg: {_public_error(exc, path)}")
    if data is None:
        raise DecodeError("Unable to decode audio. " + "; ".join(errors))
    if not np.all(np.isfinite(data)):
        bad = int(np.count_nonzero(~np.isfinite(data)))
        warnings.append(f"{bad} non-finite samples were replaced with silence")
        data = np.nan_to_num(data, nan=0.0, posinf=0.0, neginf=0.0)
    # Guard against absurd amplitudes from malformed float files.
    peak = float(np.max(np.abs(data))) if data.size else 0.0
    if peak > 8.0:
        warnings.append("Decoded peak exceeds +18 dBFS; file may contain invalid float samples")
    return data, int(sr), warnings


def decode_segment(
    path: Path,
    ext: str | None,
    start_seconds: float,
    end_seconds: float,
) -> tuple[np.ndarray, int, list[str]]:
    """Decode a time range without modifying the original.

    libsndfile seeks precisely for uncompressed formats; for compressed formats
    seeking is codec-dependent.  PyAV is used as a fallback.
    """
    path = Path(path)
    start = max(0.0, float(start_seconds))
    end = max(start, float(end_seconds))
    try:
        info = sf.info(str(path))
        start_frame = min(int(round(start * info.samplerate)), max(0, info.frames - 1))
        frames = max(1, int(round((end - start) * info.samplerate)))
        frames = min(frames, max(0, info.frames - start_frame))
        data, sr = sf.read(
            str(path), start=start_frame, frames=frames, dtype="float32", always_2d=True
        )
        if data.size:
            return np.ascontiguousarray(data, dtype=np.float32), int(sr), []
    except Exception:
        pass
    data, sr, warnings = decode_audio(path, ext)
    a = min(len(data), int(round(start * sr)))
    b = min(len(data), int(round(end * sr)))
    if b <= a:
        raise DecodeError("Selected time range is outside the audio duration")
    return np.ascontiguousarray(data[a:b], dtype=np.float32), sr, warnings


def audio_duration(path: Path) -> float:
    info = _sf_info(path)
    if info:
        return float(info["duration"])
    avi = _av_info(path)
    if avi and avi.get("duration"):
        return float(avi["duration"])
    return 0.0


def peak_scan(data: np.ndarray) -> float:
    if data.size == 0:
        return 0.0
    return float(np.max(np.abs(data)))


def dbfs(value: float, floor: float = -160.0) -> float:
    if value is None or not math.isfinite(value) or value <= 0:
        return floor
    return max(floor, 20.0 * math.log10(value))
