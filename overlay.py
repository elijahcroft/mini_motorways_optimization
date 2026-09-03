"""A floating panel that re-plans the board from whatever is on screen.

Run it beside the game, then hit the refresh hotkey whenever the board has
moved on.  The panel grabs the screen, reads it with `vision`, solves, and
draws the plan -- see `main.py overlay`.
"""

from __future__ import annotations

import os
import queue
import shutil
import signal
import subprocess
import sys
import tempfile
import threading

BG = "#12141a"
FG = "#c8ccd6"
DIM = "#6b7280"
ACCENT = "#7dd3a0"
BAD = "#e88b8b"


def grab(path: str) -> str:
    """Screenshot the whole screen to `path`, on Wayland or X11.

    `pyautogui` is X11-only and silently useless under Wayland, so prefer the
    compositor's own tool when there is one.
    """
    if os.environ.get("WAYLAND_DISPLAY"):
        if not shutil.which("grim"):
            raise RuntimeError("screen capture on Wayland needs grim: pacman -S grim")
        subprocess.run(["grim", path], check=True, capture_output=True)
        return path
    try:
        import pyautogui
    except ImportError:
        raise RuntimeError(
            "screen capture on X11 needs pyautogui: pip install pyautogui"
        ) from None
    pyautogui.screenshot().save(path)
    return path


def _plan_from_screen(shot: str, out: str, args) -> tuple[str, list[tuple[str, str]]]:
    """Grab, detect and solve.  Returns the layout PNG and lines to display."""
    import vision
    from render import render
    from solver import solve

    grab(shot)
    board, _ = vision.detect(shot, detect_water=not args.no_water)
    if not board.houses or not board.stores:
        raise RuntimeError("no board found on screen")
    problems = board.validate()
    if problems:
        raise RuntimeError(problems[0])

    solution = solve(board, attempts=args.attempts, rounds=args.rounds,
                     spread=args.spread, fit_budget=args.fit_budget)
    render(board, solution, out, cell=args.cell, heat=not args.no_heat)

    over = solution.road_tiles > board.road_budget
    lines = [
        (f"{solution.road_tiles}/{board.road_budget} tiles", BAD if over else FG),
        (f"{len(solution.paths)}/{len(board.houses)} houses",
         BAD if solution.unreachable or solution.dropped else FG),
    ]
    if solution.paths:
        lines.append((f"{solution.average_trip_length:.1f} avg trip", DIM))
    if solution.traffic:
        cell, load = solution.hotspots(1)[0]
        lines.append((f"busiest {cell[0]},{cell[1]} (x{load})", DIM))
    for w in solution.warnings[:2]:
        lines.append((w, BAD))
    return out, lines


def run(args) -> int:
    import tkinter as tk

    from PIL import Image, ImageTk

    tmp = tempfile.mkdtemp(prefix="minimotor-")
    shot = os.path.join(tmp, "shot.png")
    layout = os.path.join(tmp, "layout.png")

    results: queue.Queue = queue.Queue()
    pending = threading.Event()   # a refresh is in flight
    asked = threading.Event()     # SIGUSR1 arrived, or the button was pressed

    root = tk.Tk()
    root.title("minimotor")
    root.configure(bg=BG)
    root.attributes("-topmost", True)
    if args.alpha < 1.0:
        root.attributes("-alpha", args.alpha)

    head = tk.Frame(root, bg=BG)
    head.pack(fill="x", padx=8, pady=(8, 4))
    status = tk.Label(head, text="press refresh", bg=BG, fg=DIM,
                      font=("monospace", 9), anchor="w")
    status.pack(side="left")
    tk.Button(head, text="refresh", command=lambda: asked.set(), bg=BG, fg=ACCENT,
              relief="flat", font=("monospace", 9), highlightthickness=0,
              activebackground=BG, activeforeground=ACCENT).pack(side="right")

    canvas = tk.Label(root, bg=BG, text="", fg=DIM, font=("monospace", 9))
    canvas.pack(padx=8)
    stats = tk.Frame(root, bg=BG)
    stats.pack(fill="x", padx=8, pady=(4, 8))

    def set_stats(lines: list[tuple[str, str]]) -> None:
        for w in stats.winfo_children():
            w.destroy()
        for text, colour in lines:
            tk.Label(stats, text=text, bg=BG, fg=colour, font=("monospace", 9),
                     anchor="w", wraplength=args.width).pack(fill="x")

    def worker() -> None:
        try:
            results.put(("ok", _plan_from_screen(shot, layout, args)))
        except Exception as exc:  # a failed grab, an unreadable board, a bad solve
            results.put(("err", str(exc) or exc.__class__.__name__))

    def start() -> None:
        """Hide the panel so it is not in its own screenshot, then go."""
        if pending.is_set():
            return
        pending.set()
        status.config(text="grabbing...", fg=DIM)
        root.update_idletasks()
        root.withdraw()
        # Give the compositor a frame to actually take the window down.
        root.after(args.hide_ms, lambda: threading.Thread(
            target=worker, daemon=True).start())

    def finish(kind: str, payload) -> None:
        root.deiconify()
        root.attributes("-topmost", True)
        if kind == "err":
            status.config(text=payload, fg=BAD)
        else:
            path, lines = payload
            img = Image.open(path)
            img.thumbnail((args.width, args.height))
            photo = ImageTk.PhotoImage(img)
            canvas.configure(image=photo, text="")
            canvas.image = photo  # type: ignore[attr-defined]  # keep a reference or Tk drops the pixels
            status.config(text="planned", fg=ACCENT)
            set_stats(lines)
        pending.clear()

    def tick() -> None:
        if asked.is_set():
            asked.clear()
            start()
        try:
            kind, payload = results.get_nowait()
        except queue.Empty:
            pass
        else:
            finish(kind, payload)
        root.after(100, tick)

    # Signal handlers only run between bytecodes, and Tk's mainloop blocks in C,
    # so the handler just raises a flag that `tick` above notices.
    signal.signal(signal.SIGUSR1, lambda *_: asked.set())

    root.bind("<r>", lambda _: asked.set())
    root.bind("<Escape>", lambda _: root.destroy())
    root.bind("<q>", lambda _: root.destroy())
    if args.geometry:
        root.geometry(args.geometry)

    print(f"overlay running as pid {os.getpid()}", file=sys.stderr)
    print(f"refresh from anywhere:  kill -USR1 {os.getpid()}", file=sys.stderr)
    root.after(100, tick)
    if args.now:
        asked.set()
    root.mainloop()
    shutil.rmtree(tmp, ignore_errors=True)
    return 0
