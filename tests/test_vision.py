import tempfile
import unittest
from pathlib import Path

import conftest_path  # noqa: F401
import numpy as np
from PIL import Image, ImageDraw

import vision
from board import COLORS, Board
from render import render

HERE = Path(__file__).resolve().parent.parent


def draw(size, shapes, bg=(247, 244, 236)):
    """A synthetic screenshot: shapes are (x, y, w, h, rgb) rounded squares."""
    img = Image.new("RGB", size, bg)
    d = ImageDraw.Draw(img)
    for x, y, w, h, rgb in shapes:
        d.rounded_rectangle((x, y, x + w, y + h), radius=max(w // 5, 1), fill=rgb)
    return img


class BlobTests(unittest.TestCase):
    def test_a_lone_square_is_one_house(self):
        img = draw((200, 200), [(20, 20, 20, 20, COLORS["red"]),
                                (120, 20, 20, 20, COLORS["red"])])
        _board, blobs = vision.detect(img, detect_water=False)
        self.assertEqual([b["kind"] for b in blobs], ["house", "house"])
        self.assertEqual({b["color"] for b in blobs}, {"red"})

    def test_a_big_square_is_a_store(self):
        img = draw((240, 200), [(20, 20, 20, 20, COLORS["blue"]),
                                (120, 20, 20, 20, COLORS["blue"]),
                                (60, 100, 40, 40, COLORS["blue"])])
        _board, blobs = vision.detect(img, detect_water=False)
        self.assertEqual(sorted(b["kind"] for b in blobs),
                         ["house", "house", "store"])

    def test_lettering_is_not_mistaken_for_a_building(self):
        # A hollow ring is square and solid-ish but empty through the middle,
        # which is how text and outlines behave.
        img = Image.new("RGB", (200, 200), (247, 244, 236))
        d = ImageDraw.Draw(img)
        d.rectangle((20, 20, 40, 40), fill=COLORS["red"])       # a real house
        d.rectangle((100, 100, 160, 160), outline=COLORS["red"], width=4)
        _board, blobs = vision.detect(img, detect_water=False)
        self.assertEqual(len(blobs), 1)

    def test_specks_are_ignored(self):
        img = draw((200, 200), [(20, 20, 20, 20, COLORS["teal"]),
                                (120, 20, 20, 20, COLORS["teal"]),
                                (60, 120, 3, 3, COLORS["teal"])])
        _board, blobs = vision.detect(img, detect_water=False)
        self.assertEqual(len(blobs), 2)

    def test_an_empty_image_yields_an_empty_board(self):
        board, blobs = vision.detect(draw((100, 100), []))
        self.assertEqual(blobs, [])
        self.assertEqual(len(board.houses), 0)


class TerraceTests(unittest.TestCase):
    def test_touching_houses_are_split_back_apart(self):
        # Three 20px houses in a row with no gap: one 60x20 blob.
        img = draw((300, 200), [(20, 20, 60, 20, COLORS["pink"]),
                                (20, 120, 20, 20, COLORS["pink"]),
                                (120, 120, 20, 20, COLORS["pink"])])
        _board, blobs = vision.detect(img, detect_water=False)
        split = [b for b in blobs if b.get("split")]
        self.assertEqual(len(split), 3)
        self.assertEqual(len(blobs), 5)

    def test_split_pieces_land_on_separate_grid_cells(self):
        img = draw((300, 200), [(20, 20, 60, 20, COLORS["pink"]),
                                (20, 120, 20, 20, COLORS["pink"]),
                                (200, 20, 40, 40, COLORS["pink"])])
        board, _blobs = vision.detect(img, detect_water=False)
        cells = [(h.x, h.y) for h in board.houses]
        self.assertEqual(len(cells), len(set(cells)), "houses collided on a cell")


class WaterTests(unittest.TestCase):
    def test_blue_is_water(self):
        patch = np.full((6, 6, 3), (198, 230, 244), dtype=np.uint8)
        self.assertTrue(vision._is_water(patch))

    def test_cream_ground_is_not_water(self):
        patch = np.full((6, 6, 3), (247, 244, 236), dtype=np.uint8)
        self.assertFalse(vision._is_water(patch))

    def test_mint_land_shading_is_not_water(self):
        # Greener than it is blue -- the maps wash whole districts in this, and
        # counting it as water walls the board into islands.
        patch = np.full((6, 6, 3), (200, 232, 228), dtype=np.uint8)
        self.assertFalse(vision._is_water(patch))

    def test_a_saturated_building_colour_is_not_water(self):
        patch = np.full((6, 6, 3), COLORS["blue"], dtype=np.uint8)
        self.assertFalse(vision._is_water(patch))

    def test_water_can_be_turned_off(self):
        img = draw((300, 200), [(20, 20, 20, 20, COLORS["red"]),
                                (200, 20, 40, 40, COLORS["red"])],
                   bg=(198, 230, 244))
        wet, _ = vision.detect(img)
        dry, _ = vision.detect(img, detect_water=False)
        self.assertGreater(len(wet.blocked), 0)
        self.assertEqual(dry.blocked, set())


class RoundTripTests(unittest.TestCase):
    """Render a known board, read it back, and check it survived the trip."""

    def test_a_rendered_board_is_detected_again(self):
        board = Board.from_ascii("""
            r . . . . . t
            . . . . . . .
            . . . . . . .
            R . . . . . T
        """)
        with tempfile.TemporaryDirectory() as d:
            path = render(board, None, Path(d) / "b.png", cell=40)
            seen, blobs = vision.detect(path, detect_water=False)
        self.assertEqual(len(seen.houses), 2)
        self.assertEqual(len(seen.stores), 2)
        self.assertEqual({h.color for h in seen.houses}, {"red", "teal"})
        self.assertEqual({s.color for s in seen.stores}, {"red", "teal"})

    def test_water_survives_the_round_trip(self):
        board = Board.from_ascii("""
            r . ~ ~ . . R
            . . ~ ~ . . .
        """)
        with tempfile.TemporaryDirectory() as d:
            path = render(board, None, Path(d) / "b.png", cell=40)
            seen, _ = vision.detect(path)
        self.assertGreater(len(seen.blocked), 0)


class RealScreenshotTests(unittest.TestCase):
    """The one real screenshot in the repo, as a regression guard."""

    image = HERE / "test_image.jpeg"

    def setUp(self):
        if not self.image.exists():
            self.skipTest("sample screenshot not present")

    def test_it_finds_a_plausible_city(self):
        board, blobs = vision.detect(self.image)
        self.assertGreater(len(board.houses), 30)
        self.assertGreaterEqual(len(board.stores), 5)
        self.assertEqual(board.validate(), [])

    def test_the_city_name_is_not_read_as_buildings(self):
        # "Mumbai" sits at roughly y=630-670 in the sample, in orange.
        _board, blobs = vision.detect(self.image)
        in_title = [b for b in blobs if 600 < b["cy"] < 690 and 550 < b["cx"] < 800]
        self.assertEqual(in_title, [])

    def test_water_is_found_but_does_not_swallow_the_map(self):
        board, _ = vision.detect(self.image)
        share = len(board.blocked) / (board.width * board.height)
        self.assertGreater(share, 0.05, "no water found at all")
        self.assertLess(share, 0.35, "water is eating the map")

    def test_the_detected_board_can_be_solved_end_to_end(self):
        from solver import solve

        board, _ = vision.detect(self.image)
        solution = solve(board, attempts=2, rounds=1)
        self.assertEqual(len(solution.unreachable), 0)
        self.assertGreater(solution.road_tiles, 0)


if __name__ == "__main__":
    unittest.main()
