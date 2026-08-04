from __future__ import annotations

import struct
import tempfile
import unittest
import zlib
from pathlib import Path

from gates_of_codex.strategic_map import decode_png_rgb


class StrategicMapPngFormatTests(unittest.TestCase):
    def test_rgba_png_ignores_alpha_for_id_lookup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "rgba id map.png"
            _write_png(
                path,
                width=2,
                height=1,
                color_type=6,
                rows=[bytes([10, 20, 30, 0, 40, 50, 60, 255])],
            )
            image = decode_png_rgb(path)
            self.assertEqual((10, 20, 30), image.color_at(0, 0))
            self.assertEqual((40, 50, 60), image.color_at(1, 0))

    def test_indexed_png_resolves_palette_colors(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "indexed id map.png"
            _write_png(
                path,
                width=3,
                height=1,
                color_type=3,
                rows=[bytes([0, 1, 2])],
                palette=bytes([
                    1, 2, 3,
                    4, 5, 6,
                    7, 8, 9,
                ]),
            )
            image = decode_png_rgb(path)
            self.assertEqual((1, 2, 3), image.color_at(0, 0))
            self.assertEqual((4, 5, 6), image.color_at(1, 0))
            self.assertEqual((7, 8, 9), image.color_at(2, 0))

    def test_interlaced_png_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "interlaced.png"
            raw = bytes([0, 1, 2, 3])
            signature = b"\x89PNG\r\n\x1a\n"
            ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 1)
            path.write_bytes(
                signature
                + _chunk(b"IHDR", ihdr)
                + _chunk(b"IDAT", zlib.compress(raw))
                + _chunk(b"IEND", b"")
            )
            with self.assertRaisesRegex(ValueError, "non-interlaced"):
                decode_png_rgb(path)


def _write_png(
    path: Path,
    *,
    width: int,
    height: int,
    color_type: int,
    rows: list[bytes],
    palette: bytes | None = None,
) -> None:
    raw = b"".join(bytes([0]) + row for row in rows)
    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)
    payload = signature + _chunk(b"IHDR", ihdr)
    if palette is not None:
        payload += _chunk(b"PLTE", palette)
    payload += _chunk(b"IDAT", zlib.compress(raw)) + _chunk(b"IEND", b"")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def _chunk(kind: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    )


if __name__ == "__main__":
    unittest.main()
