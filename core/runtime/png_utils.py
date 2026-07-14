#!/usr/bin/env python3
"""Minimal PNG helpers for diagnostics without external dependencies."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", crc)


def encode_rgb_png(width: int, height: int, rows: list[list[tuple[int, int, int]]]) -> bytes:
    if len(rows) != height or any(len(row) != width for row in rows):
        raise ValueError("PNG row dimensions do not match requested width/height.")
    raw = bytearray()
    for row in rows:
        raw.append(0)
        for red, green, blue in row:
            raw.extend((red, green, blue))
    compressed = zlib.compress(bytes(raw), 9)
    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return signature + _png_chunk(b"IHDR", ihdr) + _png_chunk(b"IDAT", compressed) + _png_chunk(b"IEND", b"")


def encode_rgba_png(width: int, height: int, rows: list[list[tuple[int, int, int, int]]]) -> bytes:
    if len(rows) != height or any(len(row) != width for row in rows):
        raise ValueError("PNG row dimensions do not match requested width/height.")
    raw = bytearray()
    for row in rows:
        raw.append(0)
        for red, green, blue, alpha in row:
            raw.extend((red, green, blue, alpha))
    compressed = zlib.compress(bytes(raw), 9)
    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return signature + _png_chunk(b"IHDR", ihdr) + _png_chunk(b"IDAT", compressed) + _png_chunk(b"IEND", b"")


def write_rgb_png(path: Path, width: int, height: int, rows: list[list[tuple[int, int, int]]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encode_rgb_png(width, height, rows))


def write_rgba_png(path: Path, width: int, height: int, rows: list[list[tuple[int, int, int, int]]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encode_rgba_png(width, height, rows))


def decode_png(path: Path) -> tuple[tuple[int, int], str, list[list[tuple[int, int, int, int]]]]:
    data = path.read_bytes()
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise OSError("Not a PNG file.")
    offset = 8
    width = 0
    height = 0
    color_type = 0
    idat = bytearray()
    while offset < len(data):
        if offset + 8 > len(data):
            break
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        chunk_type = data[offset + 4 : offset + 8]
        chunk_data = data[offset + 8 : offset + 8 + length]
        if chunk_type == b"IHDR":
            width, height, _, color_type, _, _, _ = struct.unpack(">IIBBBBB", chunk_data)
        elif chunk_type == b"IDAT":
            idat.extend(chunk_data)
        offset += 12 + length

    if color_type not in {2, 6}:
        raise OSError(f"Unsupported PNG color type: {color_type}")

    raw = zlib.decompress(bytes(idat))
    rows: list[list[tuple[int, int, int, int]]] = []
    stride = width * (4 if color_type == 6 else 3)
    index = 0
    for _ in range(height):
        if index >= len(raw):
            break
        index += 1
        row: list[tuple[int, int, int, int]] = []
        for _ in range(width):
            if color_type == 6:
                red, green, blue, alpha = raw[index : index + 4]
                index += 4
            else:
                red, green, blue = raw[index : index + 3]
                alpha = 255
                index += 3
            row.append((red, green, blue, alpha))
        rows.append(row)
    mode = "RGBA" if color_type == 6 else "RGB"
    return (width, height), mode, rows
