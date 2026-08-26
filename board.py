"""Board model for Mini Motorways layouts.

A board is a rectangular grid.  Cells are either buildable (roads may be laid
on them) or blocked (water, scenery).  Houses and stores sit on their own cells
and are never buildable; cars enter and leave them from adjacent road tiles.

Boards come from JSON, from `Board.from_ascii` for small hand-written cases, or
from `vision.detect` for a screenshot of the running game.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

Cell = tuple[int, int]

# The palette the game uses, and the RGB we draw each colour with.
COLORS: dict[str, tuple[int, int, int]] = {
    "red": (231, 106, 84),
    "pink": (226, 90, 162),
    "yellow": (245, 191, 66),
    "purple": (139, 126, 214),
    "teal": (73, 176, 173),
    "blue": (79, 121, 190),
    "green": (108, 183, 118),
    "orange": (240, 148, 71),
}

# Single letters for the ASCII board format.  Upper case is a store, lower case
# the matching house, '~' is water, '.' is open ground.
ASCII_COLORS: dict[str, str] = {
    "r": "red",
    "p": "pink",
    "y": "yellow",
    "u": "purple",
    "t": "teal",
    "b": "blue",
    "g": "green",
    "o": "orange",
}
WATER_CHAR = "~"
EMPTY_CHARS = ". "


@dataclass(eq=False)  # each building is a distinct entity, compared by identity
class House:
    """One house.  It emits deliveries for a store of its own colour."""

    x: int
    y: int
    color: str

    @property
    def pos(self) -> Cell:
        return (self.x, self.y)

    def __repr__(self) -> str:
        return f"House({self.x},{self.y},{self.color})"


@dataclass(eq=False)  # ditto
class Store:
    """One store.  `capacity` is how many houses it can comfortably serve."""

    x: int
    y: int
    color: str
    capacity: int = 6

    @property
    def pos(self) -> Cell:
        return (self.x, self.y)

    def __repr__(self) -> str:
        return f"Store({self.x},{self.y},{self.color},cap={self.capacity})"


Building = House | Store


@dataclass
class Board:
    """A grid with houses, stores and impassable terrain."""

    width: int
    height: int
    houses: list[House] = field(default_factory=list)
    stores: list[Store] = field(default_factory=list)
    blocked: set[Cell] = field(default_factory=set)
    road_budget: int = 100

    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height

    def buildings(self) -> Iterator[Building]:
        yield from self.houses
        yield from self.stores

    def occupied(self) -> set[Cell]:
        """Cells taken by buildings -- roads cannot be laid here."""
        return {b.pos for b in self.buildings()}

    def buildable(self) -> set[Cell]:
        """Cells a road tile may occupy."""
        taken = self.occupied() | self.blocked
        return {
            (x, y)
            for x in range(self.width)
            for y in range(self.height)
            if (x, y) not in taken
        }

    def colors(self) -> list[str]:
        return sorted({b.color for b in self.buildings()})

    def validate(self) -> list[str]:
        """Problems with this board.  Empty means it is sane and solvable."""
        problems: list[str] = []
        if self.width <= 0 or self.height <= 0:
            problems.append(f"grid is {self.width}x{self.height}")
        seen: dict[Cell, Building] = {}
        for b in self.buildings():
            if not self.in_bounds(b.x, b.y):
                problems.append(f"{b} is outside the {self.width}x{self.height} grid")
            if b.pos in self.blocked:
                problems.append(f"{b} sits on a blocked cell")
            if b.pos in seen:
                problems.append(f"{b} overlaps {seen[b.pos]}")
            if b.color not in COLORS:
                problems.append(f"{b} has unknown colour {b.color!r}")
            seen[b.pos] = b
        for s in self.stores:
            if s.capacity < 1:
                problems.append(f"{s} has a capacity below one")
        store_colors = {s.color for s in self.stores}
        for c in sorted({h.color for h in self.houses} - store_colors):
            problems.append(f"no {c} store for the {c} houses")
        return problems

    # -- serialisation ----------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "width": self.width,
            "height": self.height,
            "road_budget": self.road_budget,
            "blocked": sorted([list(c) for c in self.blocked]),
            "houses": [{"x": h.x, "y": h.y, "color": h.color} for h in self.houses],
            "stores": [
                {"x": s.x, "y": s.y, "color": s.color, "capacity": s.capacity}
                for s in self.stores
            ],
        }

    @classmethod
    def from_dict(cls, d: dict) -> Board:
        try:
            return cls(
                width=int(d["width"]),
                height=int(d["height"]),
                road_budget=int(d.get("road_budget", 100)),
                blocked={(int(c[0]), int(c[1])) for c in d.get("blocked", [])},
                houses=[
                    House(int(h["x"]), int(h["y"]), h["color"])
                    for h in d.get("houses", [])
                ],
                stores=[
                    Store(int(s["x"]), int(s["y"]), s["color"], int(s.get("capacity", 6)))
                    for s in d.get("stores", [])
                ],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"malformed board: {exc}") from exc

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2) + "\n")

    @classmethod
    def load(cls, path: str | Path) -> Board:
        return cls.from_dict(json.loads(Path(path).read_text()))

    # -- ascii ------------------------------------------------------------

    @classmethod
    def from_ascii(cls, text: str, road_budget: int = 100, capacity: int = 6) -> Board:
        """Build a board from a picture of it.

        Lower case is a house, upper case a store, `~` water, `.` open ground::

            Board.from_ascii('''
                r . . ~ . R
                r . . ~ . .
            ''')

        Whitespace between cells is ignored, so both spaced and tight layouts
        work.  Letters are the initials in `ASCII_COLORS` (`u` is purple, since
        `p` is taken by pink).
        """
        rows = [line.strip() for line in text.strip("\n").splitlines()]
        rows = [r for r in rows if r.strip()]
        grid = [[c for c in row if c not in " \t"] for row in rows]
        if not grid:
            raise ValueError("empty ascii board")
        width = max(len(r) for r in grid)
        board = cls(width, len(grid), road_budget=road_budget)
        for y, row in enumerate(grid):
            for x, ch in enumerate(row):
                if ch in EMPTY_CHARS:
                    continue
                if ch == WATER_CHAR:
                    board.blocked.add((x, y))
                elif ch.lower() in ASCII_COLORS:
                    color = ASCII_COLORS[ch.lower()]
                    if ch.isupper():
                        board.stores.append(Store(x, y, color, capacity))
                    else:
                        board.houses.append(House(x, y, color))
                else:
                    raise ValueError(f"unknown ascii board character {ch!r} at {x},{y}")
        return board

    def to_ascii(self) -> str:
        """Render the board back to the `from_ascii` format."""
        letters = {v: k for k, v in ASCII_COLORS.items()}
        grid = [["." for _ in range(self.width)] for _ in range(self.height)]
        for x, y in self.blocked:
            if self.in_bounds(x, y):
                grid[y][x] = WATER_CHAR
        for h in self.houses:
            if self.in_bounds(h.x, h.y):
                grid[h.y][h.x] = letters.get(h.color, "?")
        for s in self.stores:
            if self.in_bounds(s.x, s.y):
                grid[s.y][s.x] = letters.get(s.color, "?").upper()
        return "\n".join("".join(row) for row in grid)
