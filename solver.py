"""Works out where the roads should go.

The objective, in priority order:

1.  Every house must reach a store of its own colour.  A house that cannot
    deliver is what eventually ends a run, so this is a hard requirement.
2.  Spread houses evenly over the stores of their colour, so no single store's
    queue overflows.
3.  Use as few road tiles as possible -- roads are the scarce resource.
4.  Keep trips short, which is what actually raises the score.

Roads in Mini Motorways are colour-agnostic: any car drives any road.  So the
whole map shares one road network and re-using a tile that already exists is
free.  That is the single fact that makes trunk roads fall out of the routing.

Two stages:

*   **Assignment** decides which store each house delivers to.  Costs come from
    one Dijkstra sweep per store, and the matching itself is a min-cost flow,
    so given those costs the assignment is optimal rather than merely good.
*   **Routing** lays the tiles.  Houses are routed one at a time into the
    network built so far, then the layout is improved by rip-up-and-reroute:
    each house's road is torn out and re-laid against everyone else's, over and
    over, until nothing more can be saved.

Minimum-tile connection is a Steiner forest problem and NP-hard, so this gets
close quickly without claiming optimality.
"""

from __future__ import annotations

import heapq
import math
import random
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field

from board import Board, Building, House, Store

Cell = tuple[int, int]

NEIGHBOURS: tuple[Cell, ...] = ((1, 0), (-1, 0), (0, 1), (0, -1))


class Grid:
    """Immutable routing topology for a board.

    The buildable set and the building lookup are worked out once here, because
    routing hits them tens of thousands of times.
    """

    __slots__ = ("board", "buildable", "tile")

    def __init__(self, board: Board) -> None:
        self.board = board
        self.buildable = board.buildable()
        # Price of one fresh tile, chosen so it always outweighs path length.
        self.tile = board.width * board.height + 1

    def neighbours(self, cell: Cell) -> Iterator[Cell]:
        x, y = cell
        for dx, dy in NEIGHBOURS:
            yield (x + dx, y + dy)

    def field_from(self, origin: Cell) -> dict[Cell, int]:
        """Tiles needed to link each buildable cell back to `origin`.

        `origin` is a building.  The returned cost for a cell counts that cell
        itself, so a cell touching the building costs 1.
        """
        dist: dict[Cell, int] = {origin: 0}
        queue: list[tuple[int, Cell]] = [(0, origin)]
        buildable = self.buildable
        while queue:
            d, cell = heapq.heappop(queue)
            if d > dist.get(cell, math.inf):
                continue
            for nxt in self.neighbours(cell):
                if nxt not in buildable:
                    continue
                nd = d + 1
                if nd < dist.get(nxt, math.inf):
                    dist[nxt] = nd
                    heapq.heappush(queue, (nd, nxt))
        return dist

    def cost_between(self, field: dict[Cell, int], building: Building) -> int | None:
        """Read a house's connection cost out of a store's distance field."""
        best: int | None = None
        for nxt in self.neighbours(building.pos):
            if nxt in field and (nxt in self.buildable or field[nxt] == 0):
                cost = field[nxt]
                if best is None or cost < best:
                    best = cost
        return best

    def route(
        self,
        start: Cell,
        goal: Cell,
        roads: Iterable[Cell],
        usage: Counter[Cell] | None = None,
        spread: float = 0.0,
    ) -> list[Cell] | None:
        """Cheapest road path between two buildings.

        Cells already carrying a road cost nothing, fresh cells cost one tile.
        Returns the cells the path runs through, excluding the two buildings,
        or None when no route exists.

        Ties on tile count are broken by path length.  A fresh tile is priced at
        `self.tile` and every step at 1, and since no path can be longer than
        `self.tile`, the sum orders paths by (new tiles, length) exactly.  Without
        this a route that costs nothing extra is free to wander, which is how you
        end up with a cheap-looking layout full of scenic detours.

        With `spread` above zero, driving onto a tile that would push it over
        the two-route congestion threshold is charged `spread` whole tiles --
        the same units the objective in `_cost` uses, so routing and scoring
        agree about what a jam is worth.  At zero the behaviour is exactly the
        tile-minimising one described above.
        """
        roads = roads if isinstance(roads, (set, frozenset)) else set(roads)
        buildable = self.buildable
        tile = self.tile
        busy = usage if (spread and usage is not None) else None
        dist: dict[Cell, float] = {start: 0.0}
        prev: dict[Cell, Cell] = {}
        queue: list[tuple[float, Cell]] = [(0.0, start)]
        while queue:
            d, cell = heapq.heappop(queue)
            if d > dist.get(cell, math.inf):
                continue
            if cell == goal:
                break
            for nxt in self.neighbours(cell):
                if nxt == goal:
                    cost = 0.0
                elif nxt in buildable:
                    cost = 1.0 if nxt in roads else tile + 1.0
                    # One more route over an already-busy tile adds exactly one
                    # to the congestion measure; anything quieter adds nothing.
                    if busy is not None and busy[nxt] >= 2:
                        cost += spread * tile
                else:
                    continue
                nd = d + cost
                if nd < dist.get(nxt, math.inf):
                    dist[nxt] = nd
                    prev[nxt] = cell
                    heapq.heappush(queue, (nd, nxt))

        if goal not in dist:
            return None
        path: list[Cell] = []
        step: Cell | None = prev.get(goal)
        while step is not None and step != start:
            path.append(step)
            step = prev.get(step)
        path.reverse()
        return path


# ---------------------------------------------------------------------------
# assignment


def min_cost_assign(
    costs: dict[tuple[int, int], int], n_left: int, capacity: Sequence[int]
) -> dict[int, int]:
    """Match every left node to a right node at minimum total cost.

    A successive-shortest-path min-cost flow with Johnson potentials, so
    Dijkstra can be used throughout.  `costs` is keyed by (left, right); pairs
    that are absent are simply not connectable.  Returns left -> right.

    Raises ValueError if the capacities cannot absorb every left node.
    """
    n_right = len(capacity)
    if sum(capacity) < n_left:
        raise ValueError("capacities cannot absorb every left node")

    source = n_left + n_right
    sink = source + 1
    n_nodes = sink + 1

    # Adjacency as parallel arrays: to, capacity, cost, and the paired reverse.
    head: list[list[int]] = [[] for _ in range(n_nodes)]
    to_: list[int] = []
    cap_: list[int] = []
    cost_: list[int] = []

    def add(u: int, v: int, cap: int, cost: int) -> None:
        head[u].append(len(to_))
        to_.append(v)
        cap_.append(cap)
        cost_.append(cost)
        head[v].append(len(to_))
        to_.append(u)
        cap_.append(0)
        cost_.append(-cost)

    for i in range(n_left):
        add(source, i, 1, 0)
    for j, cap in enumerate(capacity):
        add(n_left + j, sink, cap, 0)
    for (i, j), c in costs.items():
        add(i, n_left + j, 1, c)

    potential: list[float] = [0.0] * n_nodes  # source-side costs start non-negative
    result: dict[int, int] = {}

    for _ in range(n_left):
        dist = [math.inf] * n_nodes
        dist[source] = 0
        arc_in: list[int] = [-1] * n_nodes
        visited = [False] * n_nodes
        queue: list[tuple[float, int]] = [(0.0, source)]
        while queue:
            d, u = heapq.heappop(queue)
            if visited[u]:
                continue
            visited[u] = True
            for e in head[u]:
                if cap_[e] <= 0:
                    continue
                v = to_[e]
                nd = d + cost_[e] + potential[u] - potential[v]
                if nd < dist[v] - 1e-12:
                    dist[v] = nd
                    arc_in[v] = e
                    heapq.heappush(queue, (nd, v))
        if dist[sink] == math.inf:
            raise ValueError("no augmenting path: left nodes cannot all be matched")
        for v in range(n_nodes):
            if dist[v] < math.inf:
                potential[v] += dist[v]

        v = sink  # push one unit back along the path
        while v != source:
            e = arc_in[v]
            cap_[e] -= 1
            cap_[e ^ 1] += 1
            u = to_[e ^ 1]
            if u < n_left and n_left <= v < n_left + n_right:
                result[u] = v - n_left
            v = u

    return result


@dataclass
class _Plan:
    """The output of the assignment stage."""

    assignment: dict[House, Store] = field(default_factory=dict)
    costs: dict[tuple[House, Store], int] = field(default_factory=dict)
    capacity: dict[Store, int] = field(default_factory=dict)
    unreachable: list[House] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _assign(board: Board, grid: Grid) -> _Plan:
    """Match houses to same-colour stores, balancing the load between them."""
    assignment: dict[House, Store] = {}
    all_costs: dict[tuple[House, Store], int] = {}
    all_caps: dict[Store, int] = {}
    unreachable: list[House] = []
    warnings: list[str] = []

    fields = {s: grid.field_from(s.pos) for s in board.stores}

    for color in board.colors():
        houses = [h for h in board.houses if h.color == color]
        stores = [s for s in board.stores if s.color == color]
        if not houses:
            continue
        if not stores:
            unreachable.extend(houses)
            warnings.append(f"no {color} store exists, {len(houses)} houses stranded")
            continue

        costs: dict[tuple[int, int], int] = {}
        reachable: list[House] = []
        for h in houses:
            options = {
                j: c
                for j, s in enumerate(stores)
                if (c := grid.cost_between(fields[s], h)) is not None
            }
            if not options:
                unreachable.append(h)
                continue
            i = len(reachable)
            reachable.append(h)
            for j, c in options.items():
                costs[(i, j)] = c
                all_costs[(h, stores[j])] = c
        if not reachable:
            continue

        # An even split first; only exceed a store's stated capacity if the
        # houses simply will not fit otherwise.
        share = max(math.ceil(len(reachable) / len(stores)), 1)
        caps = [min(share, s.capacity) for s in stores]
        if sum(caps) < len(reachable):
            warnings.append(
                f"{len(reachable)} {color} houses over {len(stores)} store(s) "
                f"means ~{share} each, above capacity -- expect queues to build"
            )
            caps = [max(share, s.capacity) for s in stores]
            while sum(caps) < len(reachable):  # last resort, let one overflow
                caps[0] += 1

        try:
            matched = min_cost_assign(costs, len(reachable), caps)
        except ValueError:  # pragma: no cover - guarded by the capacity fix-up
            warnings.append(f"could not balance the {color} houses; using nearest store")
            matched = {
                i: min(
                    (j for j in range(len(stores)) if (i, j) in costs),
                    key=lambda j: costs[(i, j)],
                )
                for i in range(len(reachable))
            }
        for i, j in matched.items():
            assignment[reachable[i]] = stores[j]
        all_caps.update(zip(stores, caps, strict=True))

    return _Plan(assignment, all_costs, all_caps, unreachable, warnings)


# ---------------------------------------------------------------------------
# routing


class _Network:
    """The tiles laid so far, with a use count per tile.

    Counting uses is what makes rip-up-and-reroute cheap: pulling one house's
    road out is a decrement, not a rebuild of everyone else's routes.
    """

    __slots__ = ("usage", "paths", "roads")

    def __init__(self) -> None:
        self.usage: Counter[Cell] = Counter()
        self.paths: dict[House, list[Cell]] = {}
        self.roads: set[Cell] = set()

    def add(self, house: House, path: Sequence[Cell]) -> None:
        self.paths[house] = list(path)
        self.usage.update(path)
        self.roads.update(path)

    def remove(self, house: House) -> list[Cell]:
        path = self.paths.pop(house, [])
        for cell in path:
            self.usage[cell] -= 1
            if self.usage[cell] <= 0:
                del self.usage[cell]
                self.roads.discard(cell)
        return path

    def tiles(self) -> int:
        return len(self.roads)


def _lay(
    grid: Grid,
    assignment: dict[House, Store],
    order: Sequence[House],
    spread: float = 0.0,
) -> tuple[_Network, list[House]]:
    net = _Network()
    stranded: list[House] = []
    for house in order:
        path = grid.route(house.pos, assignment[house].pos, net.roads, net.usage, spread)
        if path is None:
            stranded.append(house)
        else:
            net.add(house, path)
    return net, stranded


def _congestion(usage: Counter[Cell]) -> int:
    """Traffic sitting on tiles that carry more than two routes.

    Junctions are where Mini Motorways actually jams, so a layout that saves
    tiles by funnelling everything through one crossing is not the bargain its
    tile count makes it look.
    """
    return sum(max(0, n - 2) for n in usage.values())


def _cost(net: _Network, spread: float = 0.0) -> tuple[float, int]:
    """What a layout is worth: tiles, then how far the cars drive.

    `spread` prices congestion in tiles -- at 2.0, one car-worth of jam is worth
    giving up two road tiles to avoid.  At zero, congestion is ignored and the
    ordering is exactly (tiles, trip length).
    """
    trips = sum(len(p) + 1 for p in net.paths.values())
    score = net.tiles() + spread * _congestion(net.usage)
    return (score, trips)


def _rip_up_and_reroute(
    grid: Grid,
    assignment: dict[House, Store],
    net: _Network,
    rounds: int,
    spread: float = 0.0,
) -> _Network:
    """Re-lay each house's road against everyone else's, until nothing improves.

    Routing one house at a time means early routes are laid blind to the ones
    that follow.  Tearing each one out and re-routing it against the finished
    network lets it move onto trunks that did not exist when it was first laid.
    """
    for _ in range(rounds):
        saved = 0
        # Longest roads first: they have the most to gain from a trunk.
        houses = sorted(net.paths, key=lambda h: -len(net.paths[h]))
        for house in houses:
            before = _cost(net, spread)
            old = net.remove(house)
            path = grid.route(
                house.pos, assignment[house].pos, net.roads, net.usage, spread
            )
            if path is None:  # cannot happen -- it routed once already
                net.add(house, old)
                continue
            net.add(house, path)
            if _cost(net, spread) >= before:
                net.remove(house)  # no better, put the original road back
                net.add(house, old)
            else:
                saved += 1
        if saved == 0:
            break
    return net


def _reassign(
    grid: Grid, plan: _Plan, net: _Network, rounds: int, spread: float = 0.0
) -> _Network:
    """Move houses between stores when the roads say it is worth it.

    The matching stage minimises distance, which is the right thing to do before
    any tarmac exists.  Once it does, the picture changes: a store that is
    further away can be the cheaper choice if the road to it is already there
    and paid for.  So each house is offered every other store of its colour, and
    keeps the move if the layout as a whole gets better.  Capacity is respected
    throughout, so this cannot undo the load balancing.
    """
    by_color: dict[str, list[Store]] = {}
    for store in plan.capacity:
        by_color.setdefault(store.color, []).append(store)

    for _ in range(rounds):
        moved = 0
        loads = Counter(plan.assignment.values())
        for house in list(net.paths):
            current = plan.assignment[house]
            alternatives = [
                s
                for s in by_color.get(house.color, ())
                if s is not current and loads[s] < plan.capacity.get(s, 0)
            ]
            if not alternatives:
                continue
            before = _cost(net, spread)
            old_path = net.remove(house)
            best: tuple[tuple[float, int], Store, list[Cell]] | None = None
            for store in alternatives:
                path = grid.route(house.pos, store.pos, net.roads, net.usage, spread)
                if path is None:
                    continue
                net.add(house, path)
                score = _cost(net, spread)
                net.remove(house)
                if best is None or score < best[0]:
                    best = (score, store, path)
            if best is not None and best[0] < before:
                _, store, path = best
                loads[current] -= 1
                loads[store] += 1
                plan.assignment[house] = store
                net.add(house, path)
                moved += 1
            else:
                net.add(house, old_path)
        if moved == 0:
            break
    return net


# ---------------------------------------------------------------------------
# results


@dataclass
class Solution:
    """A planned road network and everything worth knowing about it."""

    roads: set[Cell] = field(default_factory=set)
    assignment: dict[House, Store] = field(default_factory=dict)
    paths: dict[House, list[Cell]] = field(default_factory=dict)
    traffic: Counter = field(default_factory=Counter)
    unreachable: list[House] = field(default_factory=list)
    dropped: list[House] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def road_tiles(self) -> int:
        return len(self.roads)

    @property
    def total_trip_length(self) -> int:
        # +1 for pulling out of the house, +1 for pulling into the store
        return sum(len(p) + 1 for p in self.paths.values())

    @property
    def average_trip_length(self) -> float:
        return self.total_trip_length / len(self.paths) if self.paths else 0.0

    def store_loads(self) -> dict[Cell, int]:
        loads: Counter[Cell] = Counter()
        for store in self.assignment.values():
            loads[store.pos] += 1
        return dict(loads)

    def store_pressure(self) -> dict[Cell, int]:
        """Car-time each store demands: its houses weighted by trip length.

        Two houses next door to a store are far easier to serve than two houses
        across the map, even though the load count is the same.
        """
        pressure: Counter[Cell] = Counter()
        for house, store in self.assignment.items():
            pressure[store.pos] += len(self.paths.get(house, [])) + 1
        return dict(pressure)

    def hotspots(self, limit: int = 5) -> list[tuple[Cell, int]]:
        """Busiest tiles: where cars from many houses are funnelled together."""
        return self.traffic.most_common(limit)

    @property
    def congestion(self) -> int:
        """How much traffic sits on tiles carrying more than two routes."""
        return _congestion(self.traffic)

    def summary(self) -> dict[str, object]:
        """Everything a caller might want to log or diff, as plain data."""
        return {
            "road_tiles": self.road_tiles,
            "connected": len(self.paths),
            "unreachable": len(self.unreachable),
            "dropped": len(self.dropped),
            "total_trip_length": self.total_trip_length,
            "average_trip_length": round(self.average_trip_length, 2),
            "congestion": self.congestion,
            "busiest_tile": self.hotspots(1)[0][1] if self.traffic else 0,
            "warnings": list(self.warnings),
        }


# ---------------------------------------------------------------------------
# entry point


def solve(
    board: Board,
    attempts: int = 6,
    rounds: int = 4,
    seed: int = 0,
    spread: float = 0.0,
    fit_budget: bool = False,
) -> Solution:
    """Plan a road network for `board`.

    `attempts` routing orders are tried and the tightest kept, then each is
    polished by up to `rounds` of rip-up-and-reroute and store reassignment.

    `spread` prices congestion in road tiles.  At 0 the plan is as small as it
    can be, chokepoints and all.  Raise it and traffic fans out over more tarmac,
    which is usually the better trade in a real game, where a tile carrying
    twenty routes is a jam waiting to happen.

    With `fit_budget`, houses are dropped cheapest-saving-last until the layout
    fits the board's budget -- "what is the best I can do with the roads I have?"
    """
    if spread < 0:
        raise ValueError("spread must not be negative")
    problems = board.validate()
    if problems:
        raise ValueError("board is not valid: " + "; ".join(problems))

    grid = Grid(board)
    plan = _assign(board, grid)
    assignment, warnings = plan.assignment, plan.warnings
    houses = list(assignment)

    spans = {h: plan.costs.get((h, assignment[h]), 0) for h in houses}
    orders: list[list[House]] = [
        sorted(houses, key=lambda h: -spans[h]),
        sorted(houses, key=lambda h: spans[h]),
    ]
    rng = random.Random(seed)
    while len(orders) < max(attempts, 2):
        shuffled = list(houses)
        rng.shuffle(shuffled)
        orders.append(shuffled)

    best: tuple[tuple[int, float, int], _Network, list[House], dict[House, Store]] | None
    best = None
    for order in orders:
        trial = _Plan(dict(assignment), plan.costs, plan.capacity)
        net, stranded = _lay(grid, trial.assignment, order, spread)
        for _ in range(max(rounds, 1)):
            before = _cost(net, spread)
            net = _rip_up_and_reroute(grid, trial.assignment, net, rounds, spread)
            net = _reassign(grid, trial, net, rounds, spread)
            if _cost(net, spread) >= before:
                break
        score, trips = _cost(net, spread)
        key = (len(stranded), score, trips)
        if best is None or key < best[0]:
            best = (key, net, stranded, trial.assignment)
    assert best is not None
    _, net, stranded, assignment = best

    dropped: list[House] = []
    if fit_budget and net.tiles() > board.road_budget:
        net, dropped = _fit_budget(net, board.road_budget)
        warnings.append(
            f"dropped {len(dropped)} house(s) to fit the {board.road_budget}-tile budget"
        )
    elif net.tiles() > board.road_budget:
        warnings.append(
            f"layout needs {net.tiles()} road tiles but the budget is "
            f"{board.road_budget}"
        )

    traffic: Counter[Cell] = Counter()
    for path in net.paths.values():
        traffic.update(path)

    for house in dropped:
        assignment.pop(house, None)

    return Solution(
        roads=set(net.roads),
        assignment=assignment,
        paths=dict(net.paths),
        traffic=traffic,
        unreachable=plan.unreachable + stranded,
        dropped=dropped,
        warnings=warnings,
    )


def _fit_budget(net: _Network, budget: int) -> tuple[_Network, list[House]]:
    """Drop houses until the layout fits, giving up the least connection first.

    A house whose road is shared with its neighbours costs almost nothing to
    keep, so the ones worth cutting are those holding up a long spur of their
    own.  Each round re-measures, because cutting one house can strand a spur
    that then becomes worth cutting too.
    """
    dropped: list[House] = []
    while net.tiles() > budget and net.paths:
        best_house, best_saving = None, -1
        for house in list(net.paths):
            path = net.remove(house)
            saving = sum(1 for cell in path if cell not in net.roads)
            net.add(house, path)
            if saving > best_saving:
                best_house, best_saving = house, saving
        if best_house is None or best_saving <= 0:
            break  # nothing left to reclaim, every road is shared
        net.remove(best_house)
        dropped.append(best_house)
    return net, dropped
