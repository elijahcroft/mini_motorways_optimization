"""Draws a board, and optionally a solved road network, to a PNG.

Roads are drawn as tarmac and shaded by how many routes run over them, so the
places where the layout will jam are visible at a glance rather than buried in
the numbers.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from board import COLORS, Board
from solver import NEIGHBOURS, Cell, Solution

LAND = (247, 244, 236)
WATER = (198, 230, 234)
GRID = (232, 227, 214)
INK = (74, 71, 64)
MUTED = (140, 134, 122)
PANEL = (255, 253, 248)
ALERT = (196, 92, 76)

QUIET_ROAD = (222, 217, 205)
BUSY_ROAD = (214, 128, 96)
ROAD_EDGE = (198, 192, 178)

# Above this many routes on one tile, a road starts shading towards hot.
BUSY = 3
# Traffic is shaded against at least this span, so a calm board whose worst
# tile carries four routes does not get painted as red as a gridlocked one.
HEAT_REFERENCE = 12


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in ("DejaVuSans.ttf", "LiberationSans-Regular.ttf", "Arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _link(a: Cell, b: Cell) -> tuple[Cell, Cell]:
    """One undirected road link, ordered so it is the same key from either end."""
    return (a, b) if a <= b else (b, a)


def _blend(a: tuple[int, int, int], b: tuple[int, int, int], t: float):
    t = max(0.0, min(1.0, t))
    return tuple(int(round(x + (y - x) * t)) for x, y in zip(a, b, strict=True))


def _rounded(draw, cx, cy, size, fill, radius=None, outline=None) -> None:
    half = size / 2
    draw.rounded_rectangle(
        (cx - half, cy - half, cx + half, cy + half),
        radius=radius if radius is not None else size * 0.28,
        fill=fill,
        outline=outline,
    )


def render(
    board: Board,
    solution: Solution | None = None,
    path: str | Path = "layout.png",
    cell: int = 34,
    margin: int = 18,
    heat: bool = True,
) -> str:
    """Draw `board` (and `solution`, if given) to a PNG and return the path."""
    panel = 118 if solution is not None else 0
    width = board.width * cell + margin * 2
    height = board.height * cell + margin * 2 + panel
    img = Image.new("RGB", (width, height), PANEL)
    d = ImageDraw.Draw(img)

    def centre(c: Cell) -> tuple[float, float]:
        return (margin + c[0] * cell + cell / 2, margin + c[1] * cell + cell / 2)

    d.rectangle(
        (margin, margin, margin + board.width * cell, margin + board.height * cell),
        fill=LAND,
    )
    for x in range(board.width + 1):
        gx = margin + x * cell
        d.line((gx, margin, gx, margin + board.height * cell), fill=GRID)
    for y in range(board.height + 1):
        gy = margin + y * cell
        d.line((margin, gy, margin + board.width * cell, gy), fill=GRID)

    for c in board.blocked:
        x0, y0 = margin + c[0] * cell, margin + c[1] * cell
        d.rounded_rectangle(
            (x0, y0, x0 + cell, y0 + cell), radius=cell * 0.2, fill=WATER
        )

    if solution is not None:
        _draw_roads(d, solution, centre, cell, heat)

    for s in board.stores:
        cx, cy = centre(s.pos)
        col = COLORS.get(s.color, (150, 150, 150))
        _rounded(d, cx, cy, cell * 0.84, col)
        _rounded(d, cx, cy, cell * 0.40, tuple(min(255, v + 55) for v in col))
    dropped = set(solution.dropped) if solution else set()
    for h in board.houses:
        cx, cy = centre(h.pos)
        col = COLORS.get(h.color, (150, 150, 150))
        if h in dropped:  # left unconnected on purpose, drawn hollow
            _rounded(d, cx, cy, cell * 0.50, LAND, outline=col)
        else:
            _rounded(d, cx, cy, cell * 0.50, col)

    if solution is not None:
        _draw_panel(d, board, solution, margin, margin + board.height * cell + 12)

    img.save(path)
    return str(path)


def _draw_roads(d, solution: Solution, centre, cell: int, heat: bool):
    """Tarmac first, then the shading, so busy stretches read as one ribbon."""
    thickness = cell * 0.52
    busiest = max(solution.traffic.values(), default=1)

    def shade(*cells: Cell):
        if not heat:
            return QUIET_ROAD
        load = max((solution.traffic.get(c, 0) for c in cells), default=0)
        if load <= BUSY or busiest <= BUSY:
            return QUIET_ROAD
        span = max(busiest - BUSY, HEAT_REFERENCE - BUSY)
        return _blend(QUIET_ROAD, BUSY_ROAD, (load - BUSY) / span)

    links: set[tuple[Cell, Cell]] = set()
    for c in solution.roads:
        for dx, dy in NEIGHBOURS:
            n = (c[0] + dx, c[1] + dy)
            if n in solution.roads:
                links.add(_link(c, n))
    for house, p in solution.paths.items():  # the driveways at each end
        store = solution.assignment[house].pos
        links.add(_link(house.pos, p[0] if p else store))
        links.add(_link(store, p[-1] if p else house.pos))

    for a, b in links:  # the darker kerb underneath
        d.line((*centre(a), *centre(b)), fill=ROAD_EDGE, width=int(thickness) + 4)
    for a, b in links:
        d.line((*centre(a), *centre(b)), fill=shade(a, b), width=int(thickness))
    for c in solution.roads:
        cx, cy = centre(c)
        _rounded(d, cx, cy, thickness, shade(c), radius=thickness * 0.3)


def _draw_panel(d, board: Board, solution: Solution, x: int, y: int) -> None:
    small, big = _font(13), _font(17)
    over = solution.road_tiles > board.road_budget
    d.text((x, y), "Suggested layout", font=big, fill=INK)

    lines = [
        (f"road tiles: {solution.road_tiles} / {board.road_budget} budget", over),
        (f"houses connected: {len(solution.paths)} of {len(board.houses)}",
         len(solution.paths) < len(board.houses)),
        (f"average trip: {solution.average_trip_length:.1f} tiles "
         f"(total {solution.total_trip_length})", False),
    ]
    if solution.traffic:
        cell, load = solution.hotspots(1)[0]
        lines.append((f"busiest tile: {load} routes at {cell[0]},{cell[1]}    "
                      f"congestion: {solution.congestion}", load >= 8))
    loads = solution.store_loads()
    if board.stores:
        lines.append((
            "store load: " + "  ".join(
                f"{s.color[:4]}({s.x},{s.y}) {loads.get(s.pos, 0)}/{s.capacity}"
                for s in board.stores[:6]
            ) + ("  ..." if len(board.stores) > 6 else ""),
            any(loads.get(s.pos, 0) > s.capacity for s in board.stores),
        ))
    for i, (line, bad) in enumerate(lines):
        d.text((x, y + 24 + i * 16), line, font=small, fill=ALERT if bad else INK)
    base = y + 24 + len(lines) * 16
    for i, warn in enumerate(solution.warnings[:2]):
        d.text((x, base + i * 16), "! " + warn, font=small, fill=ALERT)
