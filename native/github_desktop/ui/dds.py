"""Software DDS decoder for image diffs (Desktop uses WebGL `parse-dds`)."""

from __future__ import annotations

import struct
from typing import Any

DDS_MAGIC = 0x20534444
DDPF_ALPHAPIXELS = 0x1
DDPF_FOURCC = 0x4
DDPF_RGB = 0x40
FOURCC_DXT1 = 0x31545844
FOURCC_DXT3 = 0x33545844
FOURCC_DXT5 = 0x35545844


def decode_dds_rgba(data: bytes) -> tuple[int, int, bytes] | None:
    """Return ``(width, height, rgba)`` for uncompressed and DXT1/3/5 DDS."""
    if len(data) < 128 or struct.unpack_from("<I", data, 0)[0] != DDS_MAGIC:
        return None
    height = struct.unpack_from("<I", data, 12)[0]
    width = struct.unpack_from("<I", data, 16)[0]
    if not width or not height or width > 8192 or height > 8192:
        return None
    pf_flags = struct.unpack_from("<I", data, 84)[0]
    fourcc = struct.unpack_from("<I", data, 88)[0]
    bit_count = struct.unpack_from("<I", data, 92)[0]
    r_mask = struct.unpack_from("<I", data, 96)[0]
    g_mask = struct.unpack_from("<I", data, 100)[0]
    b_mask = struct.unpack_from("<I", data, 104)[0]
    a_mask = struct.unpack_from("<I", data, 108)[0]
    payload = data[128:]
    if pf_flags & DDPF_FOURCC:
        if fourcc == FOURCC_DXT1:
            raw = _decode_dxt1(payload, width, height)
        elif fourcc == FOURCC_DXT3:
            raw = _decode_dxt3(payload, width, height)
        elif fourcc == FOURCC_DXT5:
            raw = _decode_dxt5(payload, width, height)
        else:
            return None
        if raw is None:
            return None
        return width, height, raw
    if pf_flags & DDPF_RGB:
        raw = _decode_uncompressed(
            payload, width, height, bit_count, r_mask, g_mask, b_mask, a_mask, bool(pf_flags & DDPF_ALPHAPIXELS)
        )
        if raw is None:
            return None
        return width, height, raw
    return None


def pixbuf_from_dds(data: bytes) -> Any | None:
    decoded = decode_dds_rgba(data)
    if decoded is None:
        return None
    width, height, rgba = decoded
    try:
        import gi

        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import GdkPixbuf, GLib
    except (ValueError, ImportError):
        return None
    try:
        return GdkPixbuf.Pixbuf.new_from_bytes(
            GLib.Bytes.new(rgba),
            GdkPixbuf.Colorspace.RGB,
            True,
            8,
            width,
            height,
            width * 4,
        )
    except Exception:
        return None


def _mask_shift(mask: int) -> tuple[int, int]:
    if mask == 0:
        return 0, 0
    shift = 0
    value = mask
    while value and value & 1 == 0:
        value >>= 1
        shift += 1
    bits = 0
    while value & 1:
        value >>= 1
        bits += 1
    return shift, bits


def _scale_channel(value: int, bits: int) -> int:
    if bits <= 0:
        return 0
    if bits >= 8:
        return (value >> (bits - 8)) & 0xFF
    return int(round(value * 255 / ((1 << bits) - 1)))


def _decode_uncompressed(
    payload: bytes,
    width: int,
    height: int,
    bit_count: int,
    r_mask: int,
    g_mask: int,
    b_mask: int,
    a_mask: int,
    has_alpha: bool,
) -> bytes | None:
    bpp = bit_count // 8
    if bpp not in (2, 3, 4) or len(payload) < width * height * bpp:
        return None
    r_shift, r_bits = _mask_shift(r_mask)
    g_shift, g_bits = _mask_shift(g_mask)
    b_shift, b_bits = _mask_shift(b_mask)
    a_shift, a_bits = _mask_shift(a_mask)
    out = bytearray(width * height * 4)
    i = 0
    for y in range(height):
        row = payload[y * width * bpp : (y + 1) * width * bpp]
        for x in range(width):
            chunk = row[x * bpp : (x + 1) * bpp] + b"\x00\x00"
            pixel = int.from_bytes(chunk[:4], "little")
            out[i] = _scale_channel((pixel & r_mask) >> r_shift, r_bits)
            out[i + 1] = _scale_channel((pixel & g_mask) >> g_shift, g_bits)
            out[i + 2] = _scale_channel((pixel & b_mask) >> b_shift, b_bits)
            if has_alpha and a_mask:
                out[i + 3] = _scale_channel((pixel & a_mask) >> a_shift, a_bits)
            else:
                out[i + 3] = 255
            i += 4
    return bytes(out)


def _rgb565(color: int) -> tuple[int, int, int]:
    r = ((color >> 11) & 0x1F) * 255 // 31
    g = ((color >> 5) & 0x3F) * 255 // 63
    b = (color & 0x1F) * 255 // 31
    return r, g, b


def _lerp(a: int, b: int, num: int, den: int) -> int:
    return (a * (den - num) + b * num) // den


def _dxt_colors(c0: int, c1: int, dxt1: bool) -> list[tuple[int, int, int, int]]:
    r0, g0, b0 = _rgb565(c0)
    r1, g1, b1 = _rgb565(c1)
    colors = [(r0, g0, b0, 255), (r1, g1, b1, 255)]
    if not dxt1 or c0 > c1:
        colors.append((_lerp(r0, r1, 1, 3), _lerp(g0, g1, 1, 3), _lerp(b0, b1, 1, 3), 255))
        colors.append((_lerp(r0, r1, 2, 3), _lerp(g0, g1, 2, 3), _lerp(b0, b1, 2, 3), 255))
    else:
        colors.append(((r0 + r1) // 2, (g0 + g1) // 2, (b0 + b1) // 2, 255))
        colors.append((0, 0, 0, 0))
    return colors


def _write_block(out: bytearray, width: int, height: int, bx: int, by: int, colors: list[tuple[int, int, int, int]], bits: int, alphas: list[int] | None) -> None:
    for py in range(4):
        y = by + py
        if y >= height:
            bits >>= 8
            continue
        for px in range(4):
            x = bx + px
            index = bits & 3
            bits >>= 2
            if x >= width:
                continue
            r, g, b, a = colors[index]
            if alphas is not None:
                a = alphas[py * 4 + px]
            offset = (y * width + x) * 4
            out[offset] = r
            out[offset + 1] = g
            out[offset + 2] = b
            out[offset + 3] = a


def _decode_dxt1(payload: bytes, width: int, height: int) -> bytes | None:
    blocks_x = (width + 3) // 4
    blocks_y = (height + 3) // 4
    if len(payload) < blocks_x * blocks_y * 8:
        return None
    out = bytearray(width * height * 4)
    offset = 0
    for by in range(0, height, 4):
        for bx in range(0, width, 4):
            c0, c1, bits = struct.unpack_from("<HHI", payload, offset)
            offset += 8
            _write_block(out, width, height, bx, by, _dxt_colors(c0, c1, True), bits, None)
    return bytes(out)


def _decode_dxt3(payload: bytes, width: int, height: int) -> bytes | None:
    blocks_x = (width + 3) // 4
    blocks_y = (height + 3) // 4
    if len(payload) < blocks_x * blocks_y * 16:
        return None
    out = bytearray(width * height * 4)
    offset = 0
    for by in range(0, height, 4):
        for bx in range(0, width, 4):
            alpha = struct.unpack_from("<Q", payload, offset)[0]
            offset += 8
            alphas = [((alpha >> (4 * i)) & 0xF) * 17 for i in range(16)]
            c0, c1, bits = struct.unpack_from("<HHI", payload, offset)
            offset += 8
            _write_block(out, width, height, bx, by, _dxt_colors(c0, c1, False), bits, alphas)
    return bytes(out)


def _decode_dxt5(payload: bytes, width: int, height: int) -> bytes | None:
    blocks_x = (width + 3) // 4
    blocks_y = (height + 3) // 4
    if len(payload) < blocks_x * blocks_y * 16:
        return None
    out = bytearray(width * height * 4)
    offset = 0
    for by in range(0, height, 4):
        for bx in range(0, width, 4):
            a0 = payload[offset]
            a1 = payload[offset + 1]
            table = int.from_bytes(payload[offset + 2 : offset + 8], "little")
            offset += 8
            alphas_lut = [a0, a1]
            if a0 > a1:
                for i in range(1, 7):
                    alphas_lut.append(((7 - i) * a0 + i * a1) // 7)
            else:
                for i in range(1, 5):
                    alphas_lut.append(((5 - i) * a0 + i * a1) // 5)
                alphas_lut.extend([0, 255])
            alphas = [alphas_lut[(table >> (3 * i)) & 7] for i in range(16)]
            c0, c1, bits = struct.unpack_from("<HHI", payload, offset)
            offset += 8
            _write_block(out, width, height, bx, by, _dxt_colors(c0, c1, False), bits, alphas)
    return bytes(out)
