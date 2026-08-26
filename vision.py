"""Best-effort reading of a Mini Motorways screenshot into a Board.

The game draws houses and stores as saturated rounded squares on a pale
background, so we mask out the saturated pixels, group them into blobs, throw
away anything that is not solid through the middle, and call the big square
blobs stores and the small ones houses.  Terraces of houses touching each other
merge into one elongated blob, so those get sliced back into their pieces.
Water is read separately, from the pale blue the game paints it.

This is heuristic.  It depends on resolution, zoom and map, so always eyeball
the board it produces -- `main.py detect` writes a preview.
"""

from __future__ import annotations

from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from board import COLORS, Board, House, Store

Cell = tuple[int, int]

# A blob at least this much wider than it is tall (or vice versa) is a terrace
# of touching houses rather than one building, and gets sliced up.
TERRACE_ASPECT = 0.7
# A square blob this many times the usual house size is a store.
STORE_SCALE = 1.6


def _saturation_mask(rgb: np.ndarray, min_sat: float, min_val: float) -> np.ndarray:
    """Pixels vivid enough to be a building rather than ground, water or road."""
    arr = rgb.astype(np.float32) / 255.0
    mx = arr.max(axis=2)
    mn = arr.min(axis=2)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0.0)
    return (sat >= min_sat) & (mx >= min_val)


def _blobs(mask: np.ndarray, min_area: int) -> list[np.ndarray]:
    """Label the connected regions of `mask`, largest-first is not guaranteed."""
    h, w = mask.shape
    seen = np.zeros((h, w), dtype=bool)
    out: list[np.ndarray] = []
    for sy, sx in zip(*np.nonzero(mask), strict=True):
        if seen[sy, sx]:
            continue
        stack = deque([(sy, sx)])
        seen[sy, sx] = True
        cells: list[tuple[int, int]] = []
        while stack:
            y, x = stack.pop()
            cells.append((y, x))
            for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ny, nx = y + dy, x + dx
                if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    stack.append((ny, nx))
        if len(cells) >= min_area:
            out.append(np.array(cells))
    return out


def _nearest_color(rgb) -> str:
    return min(COLORS, key=lambda n: sum((a - b) ** 2 for a, b in zip(COLORS[n], rgb, strict=True)))


def _is_water(patch: np.ndarray) -> bool:
    """Water is the one pale thing on the map that leans properly blue.

    Ground is cream (red above blue) and roads are near-grey, so bluer-than-red
    narrows it down.  But the maps also wash large stretches of *land* in pale
    mint, which is bluer than red too -- and would wall the board into islands
    if it counted.  Mint leans green, water leans blue, so requiring blue above
    green as well is what separates the two.
    """
    r, g, b = (float(v) for v in np.median(patch.reshape(-1, 3), axis=0))
    mx, mn = max(r, g, b), min(r, g, b)
    sat = (mx - mn) / mx if mx else 0.0
    return b > r + 8 and b > g + 2 and 0.02 < sat < 0.45 and mx > 120


def detect(
    image: str | Path | Image.Image,
    min_area: int = 40,
    min_sat: float = 0.30,
    min_val: float = 0.35,
    core_fill: float = 0.85,
    detect_water: bool = True,
) -> tuple[Board, list[dict]]:
    """Read a screenshot into a Board.

    Returns `(board, blobs)`.  Each blob is a dict of pixel geometry and what
    the blob was taken to be, so callers can draw a preview over the original.
    """
    if not isinstance(image, Image.Image):
        image = Image.open(image)
    rgb = np.asarray(image.convert("RGB"))
    mask = _saturation_mask(rgb, min_sat, min_val)

    solid = [b for b in (_measure(p, rgb, mask) for p in _blobs(mask, min_area))
             if b is not None and b["core"] >= core_fill]
    if not solid:
        return Board(1, 1), []

    squares = [b for b in solid if b["aspect"] >= TERRACE_ASPECT]
    unit = _house_size([max(b["w"], b["h"]) for b in (squares or solid)])

    blobs: list[dict] = []
    for b in solid:
        if b["aspect"] < TERRACE_ASPECT:
            blobs.extend(_split_terrace(b, unit))
        elif max(b["w"], b["h"]) >= unit * STORE_SCALE:
            blobs.append(b | {"kind": "store"})
        elif max(b["w"], b["h"]) >= unit * 0.55:
            blobs.append(b | {"kind": "house"})
    if not blobs:
        return Board(1, 1), []
    for b in blobs:
        b["color"] = _nearest_color(b["rgb"])

    return _to_board(blobs, unit, rgb if detect_water else None), blobs


def _house_size(sizes: list[int]) -> int:
    """The size of one house, given the sizes of every square building found.

    Buildings come in two sizes and the gap between them is wide, so the sizes
    are sorted and cut at their biggest jump; the smaller group is the houses.
    Taking a plain median instead breaks on boards with a lot of stores, where
    the middle of the list lands on a store.  With no clear jump, everything on
    the map is the same size and the median is right after all.
    """
    sizes = sorted(s for s in sizes if s > 0)
    if not sizes:
        return 1
    split, ratio = 0, 1.0
    for i in range(len(sizes) - 1):
        jump = sizes[i + 1] / sizes[i]
        if jump > ratio:
            split, ratio = i + 1, jump
    group = sizes[:split] if ratio >= STORE_SCALE * 0.85 else sizes
    return group[len(group) // 2]


def _measure(pixels: np.ndarray, rgb: np.ndarray, mask: np.ndarray) -> dict | None:
    y0, x0 = pixels.min(axis=0)
    y1, x1 = pixels.max(axis=0)
    bh, bw = int(y1 - y0 + 1), int(x1 - x0 + 1)
    # Buildings are solid, so the middle of the box is completely filled, while
    # lettering and thin scenery are hollow there.  This is what keeps the city
    # name off the board.
    my0, mx0 = y0 + bh // 4, x0 + bw // 4
    core = mask[my0:my0 + max(bh // 2, 1), mx0:mx0 + max(bw // 2, 1)]
    if core.size == 0:
        return None
    return {
        "cx": float(x0 + bw / 2),
        "cy": float(y0 + bh / 2),
        "w": bw,
        "h": bh,
        "area": int(len(pixels)),
        "aspect": min(bh, bw) / max(bh, bw),
        "core": float(core.mean()),
        "rgb": tuple(int(v) for v in rgb[pixels[:, 0], pixels[:, 1]].mean(axis=0)),
    }


def _split_terrace(blob: dict, unit: int) -> list[dict]:
    """Slice a run of touching houses back into individual houses.

    Houses built shoulder to shoulder merge into one long blob.  Dropping those
    loses real houses, so instead the blob is cut into however many house-widths
    fit along its long side.
    """
    horizontal = blob["w"] >= blob["h"]
    long_side = blob["w"] if horizontal else blob["h"]
    n = max(round(long_side / max(unit, 1)), 1)
    if n < 2:
        return []
    step = long_side / n
    start = (blob["cx"] if horizontal else blob["cy"]) - long_side / 2
    out = []
    for i in range(n):
        offset = start + step * (i + 0.5)
        out.append(blob | {
            "kind": "house",
            "cx": offset if horizontal else blob["cx"],
            "cy": blob["cy"] if horizontal else offset,
            "w": int(step) if horizontal else blob["w"],
            "h": blob["h"] if horizontal else int(step),
            "split": True,
        })
    return out


def _to_board(blobs: list[dict], unit: int, rgb: np.ndarray | None) -> Board:
    """Put the detected buildings on a grid, and read the water around them."""
    step = max(unit * 1.25, 1.0)
    ox = min(b["cx"] for b in blobs)
    oy = min(b["cy"] for b in blobs)

    taken: dict[Cell, dict] = {}
    houses: list[House] = []
    stores: list[Store] = []
    for b in sorted(blobs, key=lambda b: -b["area"]):  # stores claim cells first
        gx, gy = round((b["cx"] - ox) / step), round((b["cy"] - oy) / step)
        while (gx, gy) in taken:  # nudge off a collision rather than drop it
            gx += 1
        taken[(gx, gy)] = b
        b["grid"] = (gx, gy)
        if b["kind"] == "store":
            stores.append(Store(gx, gy, b["color"]))
        else:
            houses.append(House(gx, gy, b["color"]))

    width = max(g[0] for g in taken) + 2
    height = max(g[1] for g in taken) + 2
    board = Board(width, height, houses, stores, road_budget=width * height // 3)

    if rgb is not None:
        board.blocked = _read_water(rgb, board, ox, oy, step, taken)

    # A house whose colour has no store is almost always a mis-read, and would
    # make the board unsolvable, so drop it.
    store_colors = {s.color for s in stores}
    board.houses = [h for h in houses if h.color in store_colors]
    return board


def _read_water(
    rgb: np.ndarray, board: Board, ox: float, oy: float, step: float,
    taken: dict[Cell, dict],
) -> set[Cell]:
    """Sample the middle of each empty cell and mark the blue ones as water."""
    h, w, _ = rgb.shape
    half = max(int(step * 0.3), 1)
    blocked: set[Cell] = set()
    for gy in range(board.height):
        for gx in range(board.width):
            if (gx, gy) in taken:
                continue
            px, py = int(ox + gx * step), int(oy + gy * step)
            if not (half <= px < w - half and half <= py < h - half):
                continue
            if _is_water(rgb[py - half:py + half, px - half:px + half]):
                blocked.add((gx, gy))
    return blocked


def preview(
    image: str | Path | Image.Image, blobs: list[dict], path: str | Path = "detected.png"
) -> str:
    """Draw the detections back over the screenshot so they can be checked."""
    if not isinstance(image, Image.Image):
        image = Image.open(image)
    img = image.convert("RGB").copy()
    d = ImageDraw.Draw(img)
    for b in blobs:
        x0, y0 = b["cx"] - b["w"] / 2, b["cy"] - b["h"] / 2
        colour = (40, 200, 90) if b.get("kind") == "store" else (255, 60, 60)
        width = 1 if b.get("split") else 2
        d.rectangle((x0, y0, x0 + b["w"], y0 + b["h"]), outline=colour, width=width)
    img.save(path)
    return str(path)
