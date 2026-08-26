import json
import tempfile
import unittest
from pathlib import Path

import conftest_path  # noqa: F401

from board import Board, House, Store


class AsciiTests(unittest.TestCase):
    def test_letters_become_buildings(self):
        b = Board.from_ascii("""
            r . . R
            . ~ . .
        """)
        self.assertEqual((b.width, b.height), (4, 2))
        self.assertEqual([(h.x, h.y, h.color) for h in b.houses], [(0, 0, "red")])
        self.assertEqual([(s.x, s.y, s.color) for s in b.stores], [(3, 0, "red")])
        self.assertEqual(b.blocked, {(1, 1)})

    def test_tight_and_spaced_layouts_agree(self):
        spaced = Board.from_ascii("r . ~ R")
        tight = Board.from_ascii("r.~R")
        self.assertEqual(spaced.to_dict(), tight.to_dict())

    def test_round_trips_through_ascii(self):
        art = "r..R\n.~b.\n..B."
        self.assertEqual(Board.from_ascii(art).to_ascii(), art)

    def test_purple_is_u_because_p_is_pink(self):
        b = Board.from_ascii("u U p P")
        self.assertEqual([h.color for h in b.houses], ["purple", "pink"])
        self.assertEqual([s.color for s in b.stores], ["purple", "pink"])

    def test_unknown_character_is_rejected(self):
        with self.assertRaises(ValueError):
            Board.from_ascii("r . z R")

    def test_empty_board_is_rejected(self):
        with self.assertRaises(ValueError):
            Board.from_ascii("   \n  \n")


class SerialisationTests(unittest.TestCase):
    def test_json_round_trip(self):
        b = Board(9, 7, [House(1, 1, "teal")], [Store(5, 5, "teal", 4)], {(2, 2)}, 33)
        self.assertEqual(Board.from_dict(b.to_dict()).to_dict(), b.to_dict())

    def test_save_and_load(self):
        b = Board.from_ascii("r.~.R", road_budget=12)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "b.json"
            b.save(p)
            self.assertEqual(Board.load(p).to_dict(), b.to_dict())

    def test_malformed_json_is_rejected_clearly(self):
        with self.assertRaises(ValueError):
            Board.from_dict({"width": 5})
        with self.assertRaises(ValueError):
            Board.from_dict(json.loads('{"width": "wide", "height": 3}'))

    def test_capacity_defaults_when_absent(self):
        b = Board.from_dict({"width": 3, "height": 3,
                             "stores": [{"x": 1, "y": 1, "color": "red"}]})
        self.assertEqual(b.stores[0].capacity, 6)


class GeometryTests(unittest.TestCase):
    def test_buildable_excludes_buildings_and_water(self):
        b = Board.from_ascii("r.~\n..R")
        self.assertEqual(b.buildable(), {(1, 0), (0, 1), (1, 1), (2, 1)} - {(2, 1)})

    def test_in_bounds(self):
        b = Board(3, 2)
        self.assertTrue(b.in_bounds(2, 1))
        self.assertFalse(b.in_bounds(3, 1))
        self.assertFalse(b.in_bounds(-1, 0))


class ValidationTests(unittest.TestCase):
    def test_a_good_board_has_no_problems(self):
        self.assertEqual(Board.from_ascii("r . . R").validate(), [])

    def test_overlapping_buildings(self):
        b = Board(5, 5, [House(1, 1, "red")], [Store(1, 1, "red")])
        self.assertTrue(any("overlaps" in p for p in b.validate()))

    def test_building_off_the_grid(self):
        b = Board(3, 3, [House(9, 1, "red")], [Store(1, 1, "red")])
        self.assertTrue(any("outside" in p for p in b.validate()))

    def test_building_on_water(self):
        b = Board(3, 3, [House(1, 1, "red")], [Store(2, 2, "red")], {(1, 1)})
        self.assertTrue(any("blocked" in p for p in b.validate()))

    def test_house_with_no_matching_store(self):
        b = Board.from_ascii("r . . B")
        self.assertTrue(any("no red store" in p for p in b.validate()))

    def test_unknown_colour(self):
        b = Board(3, 3, [House(0, 0, "chartreuse")], [Store(2, 2, "chartreuse")])
        self.assertTrue(any("unknown colour" in p for p in b.validate()))

    def test_nonsense_capacity(self):
        b = Board(3, 3, [House(0, 0, "red")], [Store(2, 2, "red", capacity=0)])
        self.assertTrue(any("capacity" in p for p in b.validate()))


if __name__ == "__main__":
    unittest.main()
