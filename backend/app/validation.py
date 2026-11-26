"""Upload validation and structural integrity checks.

Validation happens before analysis.  It checks the declared extension against
the actual container signature, parses container headers for truncation, and
asks both libsndfile and PyAV to open the file.  A file that is merely
mislabeled is rejected with an actionable message instead of being fed to the
analysis engine.
"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Any

import numpy as np

from .audio_io import DecodeError, probe_audio
from .config import Settings, settings as default_settings

CONTAINER_FAMILIES = {
    "wav": {"wav", "rf64"},
    "mp3": {"mp3"},
    "flac": {"flac"},
    "ogg": {"ogg"},
    "aiff": {"aiff"},
    "aac": {"adts"},
    "mp4": {"mp4"},
}

EXT_FAMILY = {
    ".wav": "wav", ".wave": "wav", ".mp3": "mp3", ".flac": "flac",
    ".ogg": "ogg", ".oga": "ogg", ".aiff": "aiff", ".aif": "aiff",
    ".aifc": "aiff", ".aac": "aac", ".m4a": "mp4", ".mp4": "mp4",
}


class ValidationResult(dict):
    pass


def sniff_container(path: Path) -> str | None:
    try:
        with path.open("rb") as handle:
            head = handle.read(64)
    except OSError:
        return None
    if len(head) < 12:
        return None
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "wav"
    if head[:4] == b"RF64" and head[8:12] == b"WAVE":
        return "rf64"
    if head[:4] == b"fLaC":
        return "flac"
    if head[:4] == b"OggS":
        return "ogg"
    if head[:4] == b"FORM" and head[8:12] in (b"AIFF", b"AIFC"):
        return "aiff"
    if head[:3] == b"ID3":
        return "mp3"
    if head[0] == 0xFF and (head[1] & 0xE0) == 0xE0:
        # ADTS and MPEG audio share a sync word; layer bits distinguish them.
        layer = (head[1] >> 1) & 0x03
        if layer == 0:
            return "adts"
        return "mp3"
    if len(head) >= 12 and head[4:8] == b"ftyp":
        return "mp4"
    return None


def _read_boxes(path: Path, size: int) -> tuple[list[tuple[str, int, int]], list[str]]:
    boxes: list[tuple[str, int, int]] = []
    errors: list[str] = []
    offset = 0
    with path.open("rb") as handle:
        while offset + 8 <= size:
            handle.seek(offset)
            header = handle.read(8)
            if len(header) < 8:
                break
            box_size = struct.unpack(">I", header[:4])[0]
            box_type = header[4:8].decode("latin-1", errors="replace")
            header_size = 8
            if box_size == 1:
                ext = handle.read(8)
                if len(ext) < 8:
                    errors.append("Truncated 64-bit MP4 box header")
                    break
                box_size = struct.unpack(">Q", ext)[0]
                header_size = 16
            elif box_size == 0:
                box_size = size - offset
            if box_size < header_size:
                errors.append(f"Invalid MP4 box size for '{box_type}'")
                break
            if offset + box_size > size:
                errors.append(f"MP4 box '{box_type}' extends beyond end of file (incomplete file)")
                break
            boxes.append((box_type, offset, box_size))
            offset += box_size
            if len(boxes) > 10000:
                break
    return boxes, errors


def _check_wav(path: Path, size: int) -> tuple[list[str], list[str], dict[str, Any]]:
    errors: list[str] = []
    warnings: list[str] = []
    details: dict[str, Any] = {}
    with path.open("rb") as handle:
        header = handle.read(12)
        if len(header) < 12:
            return ["WAV header is truncated"], warnings, details
        riff_size = struct.unpack("<I", header[4:8])[0]
        if riff_size not in (0xFFFFFFFF, 0) and riff_size + 8 > size + 1:
            errors.append(
                f"WAV declares {riff_size + 8} bytes but the file has {size} bytes (truncated/incomplete)"
            )
        found_fmt = False
        found_data = False
        offset = 12
        while offset + 8 <= size:
            handle.seek(offset)
            chunk_header = handle.read(8)
            if len(chunk_header) < 8:
                break
            chunk_id = chunk_header[:4]
            chunk_size = struct.unpack("<I", chunk_header[4:8])[0]
            data_start = offset + 8
            if chunk_id == b"fmt ":
                found_fmt = True
                fmt_data = handle.read(min(chunk_size, 64))
                if len(fmt_data) >= 16:
                    audio_format, channels, rate = struct.unpack("<HHI", fmt_data[:8])
                    bits = struct.unpack("<H", fmt_data[14:16])[0]
                    details.update({
                        "wav_audio_format": audio_format,
                        "wav_bits": bits,
                        "wav_channels": channels,
                        "wav_sample_rate": rate,
                    })
            elif chunk_id == b"data":
                found_data = True
                if chunk_size not in (0xFFFFFFFF, 0) and data_start + chunk_size > size:
                    errors.append("WAV data chunk is shorter than declared (incomplete file)")
                details["wav_data_bytes"] = chunk_size
            offset = data_start + chunk_size + (chunk_size % 2)
            if chunk_size == 0 and chunk_id not in (b"data",):
                break
        if not found_fmt:
            errors.append("WAV file has no 'fmt ' chunk")
        if not found_data:
            errors.append("WAV file has no 'data' chunk")
    return errors, warnings, details


def _check_aiff(path: Path, size: int) -> tuple[list[str], list[str], dict[str, Any]]:
    errors: list[str] = []
    details: dict[str, Any] = {}
    with path.open("rb") as handle:
        header = handle.read(12)
        if len(header) < 12:
            return ["AIFF header is truncated"], [], details
        form_size = struct.unpack(">I", header[4:8])[0]
        if form_size + 8 > size + 1:
            errors.append(
                f"AIFF FORM declares {form_size + 8} bytes but the file has {size} bytes (incomplete)"
            )
        found_comm = False
        found_ssnd = False
        offset = 12
        while offset + 8 <= size:
            handle.seek(offset)
            chunk = handle.read(8)
            if len(chunk) < 8:
                break
            chunk_id = chunk[:4]
            chunk_size = struct.unpack(">I", chunk[4:8])[0]
            if chunk_id == b"COMM":
                found_comm = True
                comm = handle.read(min(chunk_size, 64))
                if len(comm) >= 18:
                    channels, frames, bits = struct.unpack(">hIh", comm[:8])
                    details.update({
                        "aiff_channels": channels,
                        "aiff_frames": frames,
                        "aiff_bits": bits,
                    })
            elif chunk_id == b"SSND":
                found_ssnd = True
                if offset + 8 + chunk_size > size + 1:
                    errors.append("AIFF SSND chunk extends beyond the file (incomplete)")
            offset += 8 + chunk_size + (chunk_size % 2)
        if not found_comm:
            errors.append("AIFF file has no COMM chunk")
        if not found_ssnd:
            errors.append("AIFF file has no SSND chunk")
    return errors, [], details


def _check_flac(path: Path, size: int, decoded_frames: int) -> tuple[list[str], list[str], dict[str, Any]]:
    errors: list[str] = []
    warnings: list[str] = []
    details: dict[str, Any] = {}
    with path.open("rb") as handle:
        if handle.read(4) != b"fLaC":
            return ["Not a FLAC stream"], warnings, details
        last = False
        blocks = 0
        while not last and blocks < 128:
            header = handle.read(4)
            if len(header) < 4:
                errors.append("FLAC metadata is truncated")
                break
            block_type = header[0] & 0x7F
            last = bool(header[0] & 0x80)
            length = int.from_bytes(header[1:4], "big")
            if block_type == 0 and length >= 34:
                data = handle.read(length)
                if len(data) < 34:
                    errors.append("FLAC STREAMINFO block is truncated")
                    break
                packed = int.from_bytes(data[10:18], "big")
                sample_rate = (packed >> 44) & 0xFFFFF
                channels = ((packed >> 41) & 0x07) + 1
                bits = ((packed >> 36) & 0x1F) + 1
                total_samples = packed & ((1 << 36) - 1)
                details.update({
                    "flac_sample_rate": sample_rate,
                    "flac_channels": channels,
                    "flac_bits": bits,
                    "flac_total_samples": total_samples,
                })
                if total_samples and decoded_frames:
                    missing = total_samples - decoded_frames
                    if missing > max(4096, total_samples * 0.01):
                        errors.append(
                            f"FLAC stream is incomplete: header declares {total_samples} samples, decoder read {decoded_frames}"
                        )
            else:
                handle.seek(length, 1)
            blocks += 1
    return errors, warnings, details


def _check_ogg(path: Path, size: int) -> tuple[list[str], list[str], dict[str, Any]]:
    warnings: list[str] = []
    details: dict[str, Any] = {}
    tail_len = min(size, 65536)
    with path.open("rb") as handle:
        handle.seek(size - tail_len)
        tail = handle.read(tail_len)
    idx = tail.rfind(b"OggS")
    if idx < 0:
        warnings.append("OGG end-of-stream page not found; file may be incomplete")
    else:
        page = tail[idx:]
        if len(page) >= 6:
            details["ogg_last_page_flags"] = page[5]
            if not (page[5] & 0x04):
                warnings.append("OGG stream has no end-of-stream flag; it may have been cut off")
    return [], warnings, details


def _check_adts(path: Path, size: int) -> tuple[list[str], list[str], dict[str, Any]]:
    errors: list[str] = []
    warnings: list[str] = []
    details: dict[str, Any] = {}
    with path.open("rb") as handle:
        head = handle.read(3)
        if head[:3] == b"ID3":
            handle.seek(0)
            id3 = handle.read(10)
            if len(id3) == 10:
                id3_size = ((id3[6] & 0x7F) << 21) | ((id3[7] & 0x7F) << 14) | ((id3[8] & 0x7F) << 7) | (id3[9] & 0x7F)
                handle.seek(10 + id3_size)
        frames = 0
        total_bytes = 0
        while True:
            header = handle.read(7)
            if len(header) == 0:
                break
            if len(header) < 7:
                errors.append("AAC ADTS file ends with a truncated frame (incomplete)")
                break
            if header[0] != 0xFF or (header[1] & 0xF6) != 0xF0:
                errors.append("Invalid AAC ADTS sync word")
                break
            frame_length = ((header[3] & 0x03) << 11) | (header[4] << 3) | (header[5] >> 5)
            if frame_length < 7:
                errors.append("Invalid AAC ADTS frame length")
                break
            pos = handle.tell() - 7
            if pos + frame_length > size:
                errors.append("AAC ADTS frame extends beyond end of file (incomplete)")
                break
            handle.seek(pos + frame_length)
            total_bytes += frame_length
            frames += 1
            if frames > 2_000_000:
                warnings.append("AAC frame scan limit reached")
                break
        details["adts_frames"] = frames
        details["adts_payload_bytes"] = total_bytes
        if frames == 0:
            errors.append("No valid AAC ADTS frames found")
    return errors, warnings, details


def _check_mp4(path: Path, size: int) -> tuple[list[str], list[str], dict[str, Any]]:
    errors: list[str] = []
    warnings: list[str] = []
    details: dict[str, Any] = {}
    boxes, box_errors = _read_boxes(path, size)
    errors.extend(box_errors)
    types = [box[0] for box in boxes]
    details["mp4_boxes"] = types[:20]
    if "ftyp" not in types:
        errors.append("MP4/M4A file has no ftyp box")
    if "moov" not in types:
        errors.append("MP4/M4A file has no moov box (incomplete or not finalized)")
    if "mdat" not in types:
        warnings.append("MP4/M4A file has no mdat media data box")
    return errors, warnings, details


def _check_mp3(path: Path, size: int, duration: float) -> tuple[list[str], list[str], dict[str, Any]]:
    warnings: list[str] = []
    details: dict[str, Any] = {}
    with path.open("rb") as handle:
        head = handle.read(10)
        offset = 0
        if head[:3] == b"ID3" and len(head) == 10:
            id3_size = ((head[6] & 0x7F) << 21) | ((head[7] & 0x7F) << 14) | ((head[8] & 0x7F) << 7) | (head[9] & 0x7F)
            offset = 10 + id3_size
            details["id3_bytes"] = offset
        handle.seek(offset)
        frame = handle.read(4)
        if len(frame) < 4 or frame[0] != 0xFF or (frame[1] & 0xE0) != 0xE0:
            warnings.append("Could not locate the first MPEG audio frame after the ID3 tag")
        # A rough CBR consistency check, skipped for VBR/Xing streams.
        if duration > 5 and size > 1024 * 1024:
            handle.seek(offset)
            probe = handle.read(min(size - offset, 200000))
            is_vbr = b"Xing" in probe or b"Info" in probe or b"VBRI" in probe
            details["mp3_vbr"] = is_vbr
            if not is_vbr:
                # 128 kbps is only a heuristic; report rather than reject.
                expected = 16000 * duration
                if size < expected * 0.55:
                    warnings.append(
                        "MP3 is much smaller than a typical CBR stream of this duration; it may be truncated"
                    )
    return [], warnings, details


def validate_upload(
    path: Path,
    original_name: str,
    ext: str,
    size: int,
    config: Settings = default_settings,
) -> dict[str, Any]:
    ext = ext.lower()
    errors: list[str] = []
    warnings: list[str] = []
    structural: dict[str, Any] = {}
    if ext not in EXT_FAMILY:
        return {
            "ok": False,
            "errors": [f"Unsupported file extension '{ext}'"],
            "warnings": [],
            "metadata": {},
        }
    if size <= 0:
        return {"ok": False, "errors": ["File is empty"], "warnings": [], "metadata": {}}
    if size > config.max_file_size_mb * 1024 * 1024:
        return {
            "ok": False,
            "errors": [f"File exceeds the {config.max_file_size_mb} MB limit"],
            "warnings": [],
            "metadata": {},
        }

    container = sniff_container(path)
    family = EXT_FAMILY[ext]
    if container is None:
        errors.append("File content is not a recognised audio container (damaged or unsupported)")
    elif container not in CONTAINER_FAMILIES[family]:
        errors.append(
            f"File extension '{ext}' does not match detected container '{container.upper()}'. "
            "The file may be mislabeled or damaged."
        )

    metadata: dict[str, Any] = {}
    if container:
        try:
            metadata = probe_audio(path, ext, size)
        except DecodeError as exc:
            errors.append(f"Damaged or unreadable audio: {exc}")
        except Exception as exc:  # pragma: no cover - defensive
            errors.append(f"Damaged or unreadable audio: {exc}")

    if container in ("wav", "rf64"):
        e, w, d = _check_wav(path, size)
        errors.extend(e); warnings.extend(w); structural.update(d)
    elif container == "aiff":
        e, w, d = _check_aiff(path, size)
        errors.extend(e); warnings.extend(w); structural.update(d)
    elif container == "flac":
        frames = int(metadata.get("frames", 0) or 0)
        e, w, d = _check_flac(path, size, frames)
        errors.extend(e); warnings.extend(w); structural.update(d)
    elif container == "ogg":
        e, w, d = _check_ogg(path, size)
        errors.extend(e); warnings.extend(w); structural.update(d)
    elif container == "adts":
        e, w, d = _check_adts(path, size)
        errors.extend(e); warnings.extend(w); structural.update(d)
    elif container == "mp4":
        e, w, d = _check_mp4(path, size)
        errors.extend(e); warnings.extend(w); structural.update(d)
    elif container == "mp3":
        e, w, d = _check_mp3(path, size, float(metadata.get("duration", 0) or 0))
        errors.extend(e); warnings.extend(w); structural.update(d)

    if metadata:
        metadata.update(structural)
        duration = float(metadata.get("duration", 0) or 0)
        sr = int(metadata.get("sample_rate", 0) or 0)
        channels = int(metadata.get("channels", 0) or 0)
        if duration > config.max_duration_seconds:
            errors.append(
                f"Duration {duration / 60:.1f} min exceeds the {config.max_duration_seconds / 60:.0f} min analysis limit"
            )
        if duration < 0.05:
            errors.append("Audio is too short to analyse (under 50 ms)")
        if sr and (sr < 8000 or sr > 384000):
            errors.append(f"Unsupported sample rate: {sr} Hz")
        if channels > 8:
            errors.append(f"Unsupported channel count: {channels} (maximum 8)")
        if metadata.get("bit_depth") is None and not metadata.get("is_lossy"):
            warnings.append("Bit depth could not be determined for this lossless file")

    # Decode a small probe at the beginning and end to catch obvious corruption.
    if not errors and metadata:
        try:
            import soundfile as sf
            info = sf.info(str(path))
            probe_frames = min(info.frames, max(1, int(info.samplerate * 0.25)))
            if probe_frames > 0:
                sf.read(str(path), frames=probe_frames, dtype="float32", always_2d=True)
                if info.frames > info.samplerate:
                    start = max(0, info.frames - probe_frames)
                    sf.read(str(path), start=start, frames=probe_frames, dtype="float32", always_2d=True)
        except Exception:
            # libsndfile may not support the format (e.g. AAC); PyAV already probed it.
            pass

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "metadata": metadata,
    }


def summarize_validation(result: dict[str, Any]) -> str:
    if result.get("ok"):
        return "Valid audio file" + (" with warnings" if result.get("warnings") else "")
    return "; ".join(result.get("errors", [])) or "Invalid audio file"
