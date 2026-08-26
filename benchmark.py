"""Measures the planner: how tight the layouts are, and how long they take.

    python benchmark.py                # the sample boards
    python benchmark.py boards/*.json  # whatever you point it at

The saving column is what road sharing buys.  The baseline is every house
running its own private road to its store, which is what you get with no
sharing at all, so the gap between that and the plan is the whole point of the
routing stage.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from board import Board
from solver import Grid, solve

SPREADS = (0.0, 0.5, 1.0)


def unshared_baseline(board: Board, solution) -> int:
    """Tiles needed if every house laid its own road, sharing nothing."""
    grid = Grid(board)
    total = 0
    for house, store in solution.assignment.items():
        path = grid.route(house.pos, store.pos, roads=())
        total += len(path) if path else 0
    return total


def run(board: Board, name: str) -> None:
    print(f"\n{name}  ({board.width}x{board.height}, {len(board.houses)} houses, "
          f"{len(board.stores)} stores, {len(board.blocked)} blocked)")
    print(f"  {'spread':>6}  {'tiles':>6} {'saved':>6}  {'trip':>6} {'avg':>5}  "
          f"{'busy':>4} {'congest':>7}  {'time':>7}")
    for spread in SPREADS:
        start = time.perf_counter()
        s = solve(board, spread=spread)
        elapsed = time.perf_counter() - start
        base = unshared_baseline(board, s)
        saved = f"{100 * (1 - s.road_tiles / base):.0f}%" if base else "-"
        busiest = s.hotspots(1)[0][1] if s.traffic else 0
        print(f"  {spread:>6.2f}  {s.road_tiles:>6} {saved:>6}  "
              f"{s.total_trip_length:>6} {s.average_trip_length:>5.1f}  "
              f"{busiest:>4} {s.congestion:>7}  {elapsed:>6.2f}s")


def main(argv: list[str]) -> int:
    named = [Path(a) for a in argv]
    paths = named or sorted(Path("boards").glob("*.json"))
    if not paths:
        print("no boards found", file=sys.stderr)
        return 1
    for path in paths:
        run(Board.load(path), path.stem)

    # Only part of the default sweep: naming boards means those boards.
    sample = Path("test_image.jpeg")
    if not named and sample.exists():
        import vision

        start = time.perf_counter()
        board, blobs = vision.detect(sample)
        elapsed = time.perf_counter() - start
        print(f"\ndetection on {sample}: {len(blobs)} buildings in {elapsed:.2f}s")
        run(board, f"{sample.stem} (detected)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
