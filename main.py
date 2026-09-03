"""Mini Motorways route planner.

    python main.py solve boards/riverside.json -o layout.png
    python main.py solve boards/riverside.json --spread 1 --fit-budget
    python main.py detect shot.png -o board.json --solve
    python main.py capture
    python main.py overlay --now
"""

from __future__ import annotations

import argparse
import json
import sys

from board import Board
from solver import Solution, solve


def _version() -> str:
    """The installed version, or a placeholder when run straight from a checkout."""
    try:
        from importlib.metadata import version
    except ImportError:  # pragma: no cover - Python 3.8 only
        return "unknown"
    try:
        return version("minimotor")
    except Exception:  # not installed, e.g. `python main.py` from the repo
        return "unknown"


def _report(board: Board, solution: Solution, out=None) -> None:
    # Resolved on each call, not bound at import, so redirected output works.
    stream = out if out is not None else sys.stdout

    def p(*a):
        print(*a, file=stream)

    over = solution.road_tiles > board.road_budget
    p(f"road tiles   : {solution.road_tiles} / {board.road_budget} budget"
      f"{'  OVER' if over else ''}")
    p(f"connected    : {len(solution.paths)} of {len(board.houses)} houses")
    if solution.paths:
        p(f"average trip : {solution.average_trip_length:.1f} tiles "
          f"(total {solution.total_trip_length})")
    if solution.traffic:
        cell, load = solution.hotspots(1)[0]
        p(f"congestion   : {solution.congestion} "
          f"(busiest tile {cell[0]},{cell[1]} carries {load} routes)")

    loads = solution.store_loads()
    pressure = solution.store_pressure()
    p("stores:")
    for s in sorted(board.stores, key=lambda s: -loads.get(s.pos, 0)):
        n = loads.get(s.pos, 0)
        flag = "  OVER CAPACITY" if n > s.capacity else ""
        p(f"  {s.color:<7} at ({s.x},{s.y}): {n}/{s.capacity} houses, "
          f"{pressure.get(s.pos, 0)} tiles of driving{flag}")

    for h in solution.unreachable:
        p(f"  ! {h.color} house at ({h.x},{h.y}) cannot reach a store")
    for h in solution.dropped:
        p(f"  ~ {h.color} house at ({h.x},{h.y}) left unconnected to fit the budget")
    for w in solution.warnings:
        p(f"  ! {w}")


def _load_board(path: str) -> Board:
    try:
        board = Board.load(path)
    except FileNotFoundError:
        raise SystemExit(f"no such board file: {path}") from None
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{path} is not valid JSON: {exc}") from None
    except ValueError as exc:
        raise SystemExit(f"{path}: {exc}") from None
    except OSError as exc:  # a directory, a bad permission, a broken link
        raise SystemExit(f"cannot read {path}: {exc.strerror}") from None
    problems = board.validate()
    if problems:
        raise SystemExit(
            "board is not valid:\n" + "\n".join(f"  - {p}" for p in problems)
        )
    return board


def _write(what: str, dest: str, write) -> None:
    """Run an output step, reporting a bad destination instead of unwinding.

    The report has already been printed by the time anything is written, so a
    file that cannot be created is worth one line, not a traceback.
    """
    try:
        write()
    except OSError as exc:
        raise SystemExit(f"cannot write the {what} to {dest}: {exc.strerror}") from None
    except ValueError as exc:  # pillow rejects a name it cannot pick a format from
        raise SystemExit(f"cannot write the {what} to {dest}: {exc}") from None
    print("wrote", dest)


def _plan(board: Board, args) -> Solution:
    return solve(
        board,
        attempts=args.attempts,
        rounds=args.rounds,
        spread=args.spread,
        fit_budget=args.fit_budget,
    )


def cmd_solve(args) -> int:
    board = _load_board(args.board)
    solution = _plan(board, args)
    if args.json:
        print(json.dumps(solution.summary(), indent=2))
    else:
        _report(board, solution)
    if args.out:
        from render import render

        _write("layout", args.out,
               lambda: render(board, solution, args.out, heat=not args.no_heat))
    return 0


def cmd_detect(args) -> int:
    from PIL import UnidentifiedImageError

    import vision

    try:
        board, blobs = vision.detect(args.image, detect_water=not args.no_water)
    except FileNotFoundError:
        raise SystemExit(f"no such image: {args.image}") from None
    except UnidentifiedImageError:
        raise SystemExit(f"{args.image} is not an image file") from None
    except OSError as exc:  # a directory, a bad permission, a truncated file
        raise SystemExit(f"cannot read {args.image}: {exc.strerror}") from None
    if not board.houses and not board.stores:
        print("no buildings found -- is this a screenshot of the game?",
              file=sys.stderr)
        return 1
    print(f"found {len(blobs)} buildings -> {len(board.houses)} houses, "
          f"{len(board.stores)} stores, {len(board.blocked)} blocked cells "
          f"on a {board.width}x{board.height} grid")
    if args.out:
        _write("board", args.out, lambda: board.save(args.out))
    if args.preview:
        _write("preview", args.preview,
               lambda: vision.preview(args.image, blobs, args.preview))
    if args.solve:
        problems = board.validate()
        if problems:
            print("detected board is not solvable:", file=sys.stderr)
            for p in problems:
                print("  -", p, file=sys.stderr)
            return 1
        solution = _plan(board, args)
        _report(board, solution)
        if args.layout:
            from render import render

            _write("layout", args.layout,
                   lambda: render(board, solution, args.layout,
                                  heat=not args.no_heat))
    return 0


def cmd_overlay(args) -> int:
    import overlay

    return overlay.run(args)


def cmd_capture(args) -> int:
    from overlay import grab

    try:
        grab(args.shot)
    except (RuntimeError, OSError) as exc:
        print(exc, file=sys.stderr)
        return 1
    print("wrote", args.shot)
    args.image = args.shot
    args.solve = True
    return cmd_detect(args)


def _spread(value: str) -> float:
    """argparse type for --spread: a price, so it cannot be negative."""
    try:
        f = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{value!r} is not a number") from None
    if f < 0:
        raise argparse.ArgumentTypeError("spread must not be negative")
    return f


def _add_solver_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument("--attempts", type=int, default=6,
                   help="routing orders to try; more is slower but tighter")
    p.add_argument("--rounds", type=int, default=4,
                   help="cap on improvement passes per attempt; the loops stop "
                        "when nothing improves, which is usually after two")
    p.add_argument("--spread", type=_spread, default=0.0,
                   help="price of congestion in road tiles; raise it to fan "
                        "traffic out instead of funnelling it through one junction")
    p.add_argument("--fit-budget", action="store_true",
                   help="drop the least valuable houses until the plan fits "
                        "the board's road budget")
    p.add_argument("--no-heat", action="store_true",
                   help="draw plain tarmac instead of shading roads by traffic")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--version", action="version", version=f"minimotor {_version()}")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("solve", help="plan roads for a board file")
    s.add_argument("board")
    s.add_argument("-o", "--out", default="layout.png", help="PNG to write")
    s.add_argument("--json", action="store_true", help="print stats as JSON")
    _add_solver_flags(s)
    s.set_defaults(func=cmd_solve)

    d = sub.add_parser("detect", help="read a screenshot into a board file")
    d.add_argument("image")
    d.add_argument("-o", "--out", help="board JSON to write")
    d.add_argument("--preview", default="detected.png",
                   help="PNG showing what was detected")
    d.add_argument("--no-water", action="store_true",
                   help="skip water detection and treat the whole map as open")
    d.add_argument("--solve", action="store_true", help="also plan roads")
    d.add_argument("--layout", default="layout.png", help="PNG for the plan")
    _add_solver_flags(d)
    d.set_defaults(func=cmd_detect)

    c = sub.add_parser("capture", help="grab the screen, detect, and plan")
    c.add_argument("--shot", default="screenshot.png")
    c.add_argument("-o", "--out", default="board.json")
    c.add_argument("--preview", default="detected.png")
    c.add_argument("--layout", default="layout.png")
    c.add_argument("--no-water", action="store_true")
    _add_solver_flags(c)
    c.set_defaults(func=cmd_capture)

    o = sub.add_parser("overlay", help="floating panel that re-plans on a hotkey")
    o.add_argument("--geometry", default="+40+40",
                   help="Tk geometry for the panel, e.g. 500x700+40+40")
    o.add_argument("--width", type=int, default=380,
                   help="widest the plan image is drawn")
    o.add_argument("--height", type=int, default=520,
                   help="tallest the plan image is drawn")
    o.add_argument("--alpha", type=float, default=1.0,
                   help="panel opacity, 0 to 1")
    o.add_argument("--cell", type=int, default=18,
                   help="pixels per grid cell when drawing the plan")
    o.add_argument("--hide-ms", type=int, default=180,
                   help="how long to wait for the panel to disappear before "
                        "grabbing, so it is not in its own screenshot")
    o.add_argument("--now", action="store_true", help="plan once on startup")
    o.add_argument("--no-water", action="store_true",
                   help="skip water detection and treat the whole map as open")
    _add_solver_flags(o)
    o.set_defaults(func=cmd_overlay)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
