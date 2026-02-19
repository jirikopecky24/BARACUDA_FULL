from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, List, Dict, Any, Tuple
import re
import numpy as np


@dataclass
class SpmChannel:
    name: str
    data_offset: int
    data_length: int
    bytes_per_pixel: int
    samps_per_line: int
    num_lines: int
    meta: Dict[str, Any]


_CIAO_BLOCK_RE = re.compile(rb"\\\*Ciao image list\r?\n", re.M)


def _read_ascii_header(fp_bytes: bytes, limit: int = 200000) -> bytes:
    # Bruker SPM has a big ASCII header; we only need enough to cover image lists.
    return fp_bytes[: min(len(fp_bytes), limit)]


def _parse_int_line(block: bytes, key: bytes, default: int = 0) -> int:
    m = re.search(rb"\\%s:\s*([-\d]+)" % re.escape(key), block)
    return int(m.group(1)) if m else default


def _parse_str_line(block: bytes, key: bytes, default: str = "") -> str:
    m = re.search(rb"\\%s:\s*(.*)" % re.escape(key), block)
    return m.group(1).decode("latin1", errors="replace").strip() if m else default


def _parse_image_name(block: bytes) -> str:
    # Example:
    # \@2:Image Data: S [ZSensor] "Height Sensor"
    m = re.search(rb'\\@2:Image Data:\s*S\s*\[[^\]]+\]\s*"([^"]+)"', block)
    if m:
        return m.group(1).decode("latin1", errors="replace").strip()
    return "Unknown"


def list_channels(spm_path: str) -> List[SpmChannel]:
    with open(spm_path, "rb") as f:
        b = f.read()

    head = _read_ascii_header(b)
    # Split into blocks starting at each \*Ciao image list
    starts = [m.start() for m in _CIAO_BLOCK_RE.finditer(head)]
    channels: List[SpmChannel] = []

    for i, st in enumerate(starts):
        en = starts[i + 1] if i + 1 < len(starts) else len(head)
        blk = head[st:en]

        data_offset = _parse_int_line(blk, b"Data offset", default=-1)
        data_length = _parse_int_line(blk, b"Data length", default=0)
        bpp = _parse_int_line(blk, b"Bytes/pixel", default=0)
        w = _parse_int_line(blk, b"Samps/line", default=0)
        h = _parse_int_line(blk, b"Number of lines", default=0)

        name = _parse_image_name(blk)
        if data_offset < 0 or data_length <= 0 or bpp <= 0 or w <= 0 or h <= 0:
            continue

        meta = {
            "scan_size": _parse_str_line(blk, b"Scan Size", ""),
            "line_direction": _parse_str_line(blk, b"Line Direction", ""),
            "frame_direction": _parse_str_line(blk, b"Frame direction", ""),
            "plane_fit": _parse_str_line(blk, b"Plane fit", ""),
            "start_context": _parse_str_line(blk, b"Start context", ""),
        }

        channels.append(
            SpmChannel(
                name=name,
                data_offset=data_offset,
                data_length=data_length,
                bytes_per_pixel=bpp,
                samps_per_line=w,
                num_lines=h,
                meta=meta,
            )
        )

    return channels


def read_channel(spm_path: str, prefer_name_contains: str = "Height") -> Tuple[np.ndarray, SpmChannel]:
    chs = list_channels(spm_path)
    if not chs:
        raise RuntimeError("No \\*Ciao image list blocks parsed. Unsupported/invalid SPM?")

    # Prefer height-like channel
    cand = None
    for c in chs:
        if prefer_name_contains.lower() in c.name.lower():
            cand = c
            break
    if cand is None:
        cand = chs[0]

    with open(spm_path, "rb") as f:
        f.seek(cand.data_offset)
        raw = f.read(cand.data_length)

    # Bruker often stores int32/uint16/etc. Here: your Height Sensor is 4 bytes/pixel.
    if cand.bytes_per_pixel == 4:
        # Usually signed int32 counts. Float32 interpretation gave NaNs for your file.
        arr = np.frombuffer(raw, dtype="<i4", count=cand.samps_per_line * cand.num_lines)
        img = arr.reshape((cand.num_lines, cand.samps_per_line)).astype(np.float32)
    elif cand.bytes_per_pixel == 2:
        arr = np.frombuffer(raw, dtype="<i2", count=cand.samps_per_line * cand.num_lines)
        img = arr.reshape((cand.num_lines, cand.samps_per_line)).astype(np.float32)
    elif cand.bytes_per_pixel == 1:
        arr = np.frombuffer(raw, dtype=np.uint8, count=cand.samps_per_line * cand.num_lines)
        img = arr.reshape((cand.num_lines, cand.samps_per_line)).astype(np.float32)
    else:
        raise RuntimeError(f"Unsupported Bytes/pixel={cand.bytes_per_pixel}")

    return img, cand
