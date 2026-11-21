"""Generates the tray icon at runtime. Pure stdlib (zlib + struct).

The icon is a rounded dark tile with a mint lightning bolt; a desaturated
variant is used while hotkeys are suspended. Both are cached as .ico files.
"""
from __future__ import annotations

import os
import struct
import zlib

_SIZE = 64
_SS = 4  # supersampling factor


def _inside_round(x: float, y: float, size: float, radius: float) -> bool:
    cx = min(max(x, radius), size - radius)
    cy = min(max(y, radius), size - radius)
    dx, dy = x - cx, y - cy
    return dx * dx + dy * dy <= radius * radius


def _inside_poly(x: float, y: float, pts: list[tuple[float, float]]) -> bool:
    inside = False
    j = len(pts) - 1
    for i in range(len(pts)):
        xi, yi = pts[i]
        xj, yj = pts[j]
        if (yi > y) != (yj > y):
            if x < (xj - xi) * (y - yi) / (yj - yi) + xi:
                inside = not inside
        j = i
    return inside


def _mix(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return (
        round(a[0] + (b[0] - a[0]) * t),
        round(a[1] + (b[1] - a[1]) * t),
        round(a[2] + (b[2] - a[2]) * t),
    )


def render(accent: tuple[int, int, int] = (61, 224, 160)) -> list[list[tuple[int, int, int, int]]]:
    """Return an RGBA pixel grid (RGBA, straight alpha)."""
    size = _SIZE
    radius = size * 0.24
    top_bg = (12, 20, 33)
    bot_bg = (26, 39, 62)
    border = (46, 64, 96)
    accent_top = _mix(accent, (255, 255, 255), 0.28)
    accent_bot = _mix(accent, (0, 0, 0), 0.25)
    bolt = [
        (38.0, 2.0), (14.0, 36.0), (29.0, 36.0),
        (25.0, 62.0), (50.0, 27.0), (34.0, 27.0),
    ]

    grid: list[list[tuple[int, int, int, int]]] = []
    inv = 1.0 / _SS
    n = _SS * _SS
    for py in range(size):
        row = []
        for px in range(size):
            r = g = b = 0.0
            hits = 0
            for sy in range(_SS):
                for sx in range(_SS):
                    x = px + (sx + 0.5) * inv
                    y = py + (sy + 0.5) * inv
                    if not _inside_round(x, y, size, radius):
                        continue
                    hits += 1
                    t = y / size
                    col = _mix(top_bg, bot_bg, t)
                    if not _inside_round(x, y, size - 2.0, radius - 1.4):
                        col = _mix(col, border, 0.85)
                    if _inside_poly(x, y, bolt):
                        col = _mix(accent_top, accent_bot, t)
                    r += col[0]
                    g += col[1]
                    b += col[2]
            if not hits:
                row.append((0, 0, 0, 0))
            else:
                row.append((round(r / hits), round(g / hits), round(b / hits),
                            round(255 * hits / n)))
        grid.append(row)
    return grid


def _png(grid: list[list[tuple[int, int, int, int]]]) -> bytes:
    h = len(grid)
    w = len(grid[0])
    raw = bytearray()
    for row in grid:
        raw.append(0)
        for r, g, b, a in row:
            raw += bytes((r, g, b, a))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b""))


def _ico(png: bytes, size: int) -> bytes:
    header = struct.pack("<HHH", 0, 1, 1)
    entry = struct.pack("<BBBBHHII", size if size < 256 else 0,
                        size if size < 256 else 0, 0, 0, 1, 32, len(png), 22)
    return header + entry + png


def ensure_icon(cache_dir: str) -> tuple[str, str]:
    """Create (or reuse) active + paused icons, returning their paths."""
    os.makedirs(cache_dir, exist_ok=True)
    active = os.path.join(cache_dir, "hotkey.ico")
    paused = os.path.join(cache_dir, "hotkey-paused.ico")
    if not (os.path.isfile(active) and os.path.isfile(paused)):
        png = _png(render())
        with open(active, "wb") as fh:
            fh.write(_ico(png, _SIZE))
        png = _png(render((120, 132, 150)))
        with open(paused, "wb") as fh:
            fh.write(_ico(png, _SIZE))
    return active, paused


if __name__ == "__main__":  # manual preview: python -m hk.icon out.png
    import sys
    out = sys.argv[1] if len(sys.argv) > 1 else "icon-preview.png"
    with open(out, "wb") as fh:
        fh.write(_png(render()))
    print(out)
