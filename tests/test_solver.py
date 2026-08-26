import unittest

import conftest_path  # noqa: F401

from board import Board, House, Store
from solver import Grid, _assign, min_cost_assign, solve


class RoutingTests(unittest.TestCase):
    def test_adjacent_house_and_store_need_no_road(self):
        b = Board.from_ascii("r R")
        s = solve(b)
        self.assertEqual(s.road_tiles, 0)
        self.assertEqual(s.paths[b.houses[0]], [])

    def test_straight_run_uses_the_gap_cells(self):
        b = Board.from_ascii("r . . . R")
        s = solve(b)
        self.assertEqual(s.road_tiles, 3)
        self.assertEqual(s.paths[b.houses[0]], [(1, 0), (2, 0), (3, 0)])

    def test_road_length_matches_manhattan_distance_on_open_ground(self):
        b = Board.from_ascii("""
            r . . . .
            . . . . .
            . . . . R
        """)
        s = solve(b)
        self.assertEqual(s.road_tiles, 5)  # 6 steps, minus the store's own cell

    def test_roads_go_around_water(self):
        b = Board.from_ascii("""
            . . ~ . .
            r . ~ . R
            . . ~ . .
            . . . . .
        """)
        s = solve(b)
        self.assertFalse(s.roads & b.blocked)
        self.assertFalse(s.unreachable)

    def test_walled_off_house_is_reported_unreachable(self):
        b = Board.from_ascii("""
            . ~ . .
            r ~ . R
            . ~ . .
            . ~ . .
        """)
        s = solve(b)
        self.assertEqual(s.unreachable, b.houses)
        self.assertEqual(s.road_tiles, 0)

    def test_house_boxed_in_by_other_houses_is_unreachable(self):
        # (0,0) has no free neighbour: both are houses.
        b = Board.from_ascii("""
            r r . . R
            r . . . .
        """)
        s = solve(b)
        self.assertIn(b.houses[0], s.unreachable)
        self.assertEqual(len(s.paths), 2)

    def test_reusing_a_road_is_free_so_houses_share_a_trunk(self):
        b = Board.from_ascii("""
            r . . . . . .
            r . . . . . R
        """)
        s = solve(b)
        h1, h2 = b.houses
        self.assertTrue(set(s.paths[h1]) & set(s.paths[h2]), "expected a shared trunk")
        self.assertLess(s.road_tiles, sum(len(p) for p in s.paths.values()))

    def test_different_colours_still_share_tarmac(self):
        b = Board.from_ascii("""
            b . . . . . . B
            r . . . . . . R
        """)
        s = solve(b)
        blue, red = b.houses[0], b.houses[1]
        self.assertTrue(set(s.paths[blue]) & set(s.paths[red]))

    def test_a_row_of_houses_shares_one_trunk_road(self):
        # Eight houses hanging off one corridor should cost the corridor plus
        # almost nothing, not eight separate roads.
        b = Board.from_ascii("""
            r r r r r r r r
            . . . . . . . .
            . . . . . . . R
        """)
        s = solve(b)
        self.assertFalse(s.unreachable)
        self.assertLessEqual(s.road_tiles, 10)

    def test_every_road_tile_is_actually_used(self):
        b = Board.from_ascii("""
            r . . . . y
            . . ~ ~ . .
            R . . . . Y
        """)
        s = solve(b)
        used = set()
        for path in s.paths.values():
            used.update(path)
        self.assertEqual(used, s.roads)

    def test_paths_are_contiguous_from_house_to_store(self):
        b = Board.from_ascii("""
            r . . ~ . .
            . . . ~ . .
            . . . . . R
        """)
        s = solve(b)
        for house, path in s.paths.items():
            chain = [house.pos] + path + [s.assignment[house].pos]
            for a, c in zip(chain, chain[1:], strict=False):
                self.assertEqual(abs(a[0] - c[0]) + abs(a[1] - c[1]), 1,
                                 f"{a} and {c} are not adjacent")


class RipUpAndRerouteTests(unittest.TestCase):
    def test_rerouting_never_makes_a_layout_worse(self):
        b = Board.from_ascii("""
            r . . . . . . . b
            . . ~ ~ ~ ~ . . .
            . . . . . . . . .
            R . . . . . . . B
        """)
        blind = solve(b, attempts=1, rounds=0)
        polished = solve(b, attempts=1, rounds=6)
        self.assertLessEqual(polished.road_tiles, blind.road_tiles)

    def test_rip_up_pulls_a_stray_route_onto_the_trunk(self):
        # Routed in the wrong order, the lone house at the top lays its own
        # road; rerouting should fold it into the road below.
        b = Board.from_ascii("""
            r . . . . . . .
            . . . . . . . .
            r r r r . . . R
        """)
        blind = solve(b, attempts=1, rounds=0)
        polished = solve(b, attempts=1, rounds=8)
        self.assertLessEqual(polished.road_tiles, blind.road_tiles)
        self.assertFalse(polished.unreachable)


class AssignmentTests(unittest.TestCase):
    def test_load_is_spread_across_stores(self):
        b = Board.from_ascii("""
            r . R . . . . . . . .
            r . . . . . . . . . .
            r . . . . . . . . . R
            r . . . . . . . . . .
        """)
        s = solve(b)
        self.assertEqual(sorted(s.store_loads().values()), [2, 2])

    def test_assignment_is_minimum_cost_not_merely_greedy(self):
        # Greedy would let the top house take the near store first and push the
        # bottom house on a long detour; min-cost flow avoids that.
        b = Board.from_ascii("""
            r . . . . . . . R
            . . . . . . . . .
            . . . . . . . . .
            r . . . . . . . R
        """)
        s = solve(b)
        self.assertEqual(sorted(s.store_loads().values()), [1, 1])
        for house, store in s.assignment.items():
            self.assertEqual(house.y, store.y)  # each takes the store on its row

    def test_colours_never_cross_assign(self):
        b = Board.from_ascii("""
            r . . . . . . R
            . . . . . . . .
            b . . . . . . B
        """)
        s = solve(b)
        for house, store in s.assignment.items():
            self.assertEqual(house.color, store.color)

    def test_capacity_overrun_is_warned_about(self):
        b = Board.from_ascii("""
            r . . . . . .
            r . . . . . R
            r . . . . . .
            r . . . . . .
        """, capacity=2)
        s = solve(b)
        self.assertTrue(any("capacity" in w for w in s.warnings))
        self.assertEqual(len(s.paths), 4)  # still connected, just warned about

    def test_missing_store_colour_is_rejected(self):
        with self.assertRaises(ValueError):
            solve(Board.from_ascii("r . . . B"))

    def test_houses_of_a_colour_with_no_store_are_stranded_not_crashed(self):
        # solve() rejects this board, but _assign must still cope: vision can
        # hand it a colour whose store was missed.
        b = Board(6, 3, [House(0, 0, "red"), House(0, 2, "blue")],
                  [Store(5, 0, "red")])
        plan = _assign(b, Grid(b))
        self.assertEqual([h.color for h in plan.unreachable], ["blue"])
        self.assertEqual([h.color for h in plan.assignment], ["red"])
        self.assertTrue(any("no blue store" in w for w in plan.warnings))


class BudgetTests(unittest.TestCase):
    def test_budget_overrun_is_warned_about(self):
        b = Board.from_ascii("r . . . . . . . . . R", road_budget=5)
        s = solve(b)
        self.assertTrue(any("budget" in w for w in s.warnings))
        self.assertEqual(len(s.paths), 1)  # warned, but nothing dropped

    def test_fit_budget_drops_houses_until_the_layout_fits(self):
        b = Board.from_ascii("""
            r . . . . . . . . . .
            . . . . . . . . . . .
            R . . . . . . . . . r
        """, road_budget=6)
        s = solve(b, fit_budget=True)
        self.assertLessEqual(s.road_tiles, 6)
        self.assertEqual(len(s.dropped), 1)
        self.assertTrue(any("dropped" in w for w in s.warnings))

    def test_fit_budget_keeps_the_cheaper_house(self):
        b = Board.from_ascii("""
            r . R . . . . . . . r
        """, road_budget=2)
        s = solve(b, fit_budget=True)
        kept = list(s.paths)
        self.assertEqual([h.x for h in kept], [0])  # the far house is the one cut

    def test_fit_budget_does_nothing_when_already_within_budget(self):
        b = Board.from_ascii("r . . R", road_budget=50)
        s = solve(b, fit_budget=True)
        self.assertEqual(s.dropped, [])
        self.assertEqual(s.warnings, [])


class MetricsTests(unittest.TestCase):
    def test_trip_length_counts_both_driveways(self):
        b = Board.from_ascii("r . . R")  # two road tiles between them
        s = solve(b)
        self.assertEqual(s.total_trip_length, 3)
        self.assertEqual(s.average_trip_length, 3.0)

    def test_traffic_counts_routes_over_each_tile(self):
        b = Board.from_ascii("""
            r . . . . . R
            r . . . . . .
        """)
        s = solve(b)
        self.assertEqual(max(s.traffic.values()), 2)
        self.assertEqual(s.hotspots(1)[0][1], 2)

    def test_congestion_ignores_quiet_tiles(self):
        quiet = solve(Board.from_ascii("r . . R"))
        self.assertEqual(quiet.congestion, 0)

    def test_congestion_rises_when_routes_are_funnelled_together(self):
        # Three houses forced through the one gap in the wall.
        b = Board.from_ascii("""
            r . ~ . . .
            . . ~ . . .
            r . . . . R
            . . ~ . . .
            r . ~ . . .
        """)
        s = solve(b)
        self.assertEqual(s.traffic[(2, 2)], 3)  # every route uses the gap
        self.assertGreater(s.congestion, 0)

    def test_store_pressure_weights_load_by_distance(self):
        b = Board.from_ascii("""
            r R . . . . . . . .
            . . . . . . . . . .
            r . . . . . . . . R
        """)
        s = solve(b)
        pressure = s.store_pressure()
        self.assertLess(pressure[(1, 0)], pressure[(9, 2)])

    def test_summary_is_plain_data(self):
        s = solve(Board.from_ascii("r . . R"))
        summary = s.summary()
        self.assertEqual(summary["connected"], 1)
        self.assertEqual(summary["road_tiles"], 2)
        self.assertIsInstance(summary["warnings"], list)


class MinCostAssignTests(unittest.TestCase):
    def test_it_finds_the_optimum_not_the_greedy_answer(self):
        # Greedy picks (0,0) at cost 1, forcing (1,1) at 10, total 11.
        # The optimum is (0,1) + (1,0) = 2 + 3 = 5.
        costs = {(0, 0): 1, (0, 1): 2, (1, 0): 3, (1, 1): 10}
        result = min_cost_assign(costs, 2, [1, 1])
        self.assertEqual(result, {0: 1, 1: 0})

    def test_it_respects_capacity(self):
        costs = {(i, 0): 1 for i in range(3)} | {(i, 1): 5 for i in range(3)}
        result = min_cost_assign(costs, 3, [2, 1])
        self.assertEqual(sorted(result.values()), [0, 0, 1])

    def test_it_refuses_when_capacity_is_short(self):
        with self.assertRaises(ValueError):
            min_cost_assign({(0, 0): 1, (1, 0): 1}, 2, [1])

    def test_it_refuses_when_a_left_node_has_no_option(self):
        with self.assertRaises(ValueError):
            min_cost_assign({(0, 0): 1}, 2, [2])

    def test_matches_brute_force_on_random_instances(self):
        import itertools
        import random

        rng = random.Random(11)
        for _ in range(20):
            n = rng.randint(2, 5)
            costs = {(i, j): rng.randint(1, 20) for i in range(n) for j in range(n)}
            got = min_cost_assign(costs, n, [1] * n)
            mine = sum(costs[(i, got[i])] for i in range(n))
            best = min(
                sum(costs[(i, perm[i])] for i in range(n))
                for perm in itertools.permutations(range(n))
            )
            self.assertEqual(mine, best)


class GridTests(unittest.TestCase):
    def test_distance_field_counts_the_cell_itself(self):
        b = Board.from_ascii("R . . .")
        grid = Grid(b)
        field = grid.field_from((0, 0))
        self.assertEqual(field[(1, 0)], 1)
        self.assertEqual(field[(3, 0)], 3)

    def test_distance_field_stops_at_water(self):
        b = Board.from_ascii("R ~ . .")
        grid = Grid(b)
        field = grid.field_from((0, 0))
        self.assertNotIn((1, 0), field)  # the water itself
        self.assertNotIn((2, 0), field)  # and everything behind it

    def test_determinism(self):
        b = Board.from_ascii("""
            r . . . . y . .
            . . ~ ~ . . . .
            R . . . . . . Y
        """)
        first = solve(b, seed=3).summary()
        second = solve(b, seed=3).summary()
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()


class SpreadTests(unittest.TestCase):
    """`spread` trades road tiles for less congestion."""

    # Four houses far from one store.  Minimising tiles funnels them all down
    # one trunk; spreading pays for extra tarmac to keep the trunk quiet.
    board = """
        r . . . . . . .
        . . . . . . . .
        r . . . . . . .
        . . . . . . . R
        r . . . . . . .
        . . . . . . . .
        r . . . . . . .
    """

    def test_zero_spread_minimises_tiles(self):
        tight = solve(Board.from_ascii(self.board), spread=0.0)
        loose = solve(Board.from_ascii(self.board), spread=3.0)
        self.assertLessEqual(tight.road_tiles, loose.road_tiles)

    def test_raising_spread_thins_out_the_busiest_tile(self):
        tight = solve(Board.from_ascii(self.board), spread=0.0)
        loose = solve(Board.from_ascii(self.board), spread=3.0)
        self.assertLess(loose.hotspots(1)[0][1], tight.hotspots(1)[0][1])
        self.assertLess(loose.congestion, tight.congestion)

    def test_spread_still_connects_everyone(self):
        loose = solve(Board.from_ascii(self.board), spread=3.0)
        self.assertEqual(len(loose.paths), 4)
        self.assertEqual(loose.unreachable, [])

    def test_spread_pays_for_the_quiet_in_tiles(self):
        tight = solve(Board.from_ascii(self.board), spread=0.0)
        loose = solve(Board.from_ascii(self.board), spread=3.0)
        self.assertGreater(loose.road_tiles, tight.road_tiles)
        self.assertEqual(loose.congestion, 0)

    def test_spread_never_crosses_water(self):
        b = Board.from_ascii("""
            r . ~ . . .
            . . ~ . . .
            r . . . . R
            . . ~ . . .
            r . ~ . . .
        """)
        s = solve(b, spread=5.0)
        self.assertFalse(s.roads & b.blocked)

    def test_negative_spread_is_rejected(self):
        with self.assertRaises(ValueError):
            solve(Board.from_ascii("r . . R"), spread=-1.0)
