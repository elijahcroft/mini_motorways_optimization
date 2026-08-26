import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import conftest_path  # noqa: F401

import main
from board import Board

HERE = Path(__file__).resolve().parent.parent


@contextlib.contextmanager
def captured():
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        yield out, err


class SolveCommandTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.board_path = Path(self.dir.name) / "b.json"
        Board.from_ascii("""
            r . . . . . R
            . . ~ ~ . . .
            b . . . . . B
        """, road_budget=40).save(self.board_path)

    def test_it_reports_and_writes_a_png(self):
        png = Path(self.dir.name) / "out.png"
        with captured() as (out, _):
            code = main.main(["solve", str(self.board_path), "-o", str(png)])
        self.assertEqual(code, 0)
        self.assertIn("road tiles", out.getvalue())
        self.assertIn("stores:", out.getvalue())
        self.assertTrue(png.exists() and png.stat().st_size > 0)

    def test_json_output_is_machine_readable(self):
        with captured() as (out, _):
            main.main(["solve", str(self.board_path), "--json", "-o", ""])
        data = json.loads(out.getvalue())
        self.assertEqual(data["connected"], 2)
        self.assertIn("congestion", data)

    def test_spread_flag_is_honoured(self):
        with captured() as (out, _):
            main.main(["solve", str(self.board_path), "--spread", "2", "-o", ""])
        self.assertIn("road tiles", out.getvalue())

    def test_fit_budget_flag_drops_houses(self):
        tight = Path(self.dir.name) / "tight.json"
        Board.from_ascii("r . . . . . . . . . R", road_budget=3).save(tight)
        with captured() as (out, _):
            main.main(["solve", str(tight), "--fit-budget", "-o", ""])
        self.assertIn("left unconnected", out.getvalue())

    def test_a_missing_file_gives_a_clean_message(self):
        with self.assertRaises(SystemExit) as cm, captured():
            main.main(["solve", "nope.json", "-o", ""])
        self.assertIn("no such board file", str(cm.exception))

    def test_malformed_json_gives_a_clean_message(self):
        bad = Path(self.dir.name) / "bad.json"
        bad.write_text("{not json")
        with self.assertRaises(SystemExit) as cm, captured():
            main.main(["solve", str(bad), "-o", ""])
        self.assertIn("not valid JSON", str(cm.exception))

    def test_an_unsolvable_board_is_explained_not_crashed(self):
        broken = Path(self.dir.name) / "broken.json"
        Board.from_ascii("r . . . B").save(broken)
        with self.assertRaises(SystemExit) as cm, captured():
            main.main(["solve", str(broken), "-o", ""])
        self.assertIn("no red store", str(cm.exception))


class DetectCommandTests(unittest.TestCase):
    image = HERE / "test_image.jpeg"

    def setUp(self):
        if not self.image.exists():
            self.skipTest("sample screenshot not present")
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

    def test_detect_writes_a_board_and_a_preview(self):
        out_json = Path(self.dir.name) / "b.json"
        preview = Path(self.dir.name) / "p.png"
        with captured() as (out, _):
            code = main.main(["detect", str(self.image), "-o", str(out_json),
                              "--preview", str(preview)])
        self.assertEqual(code, 0)
        self.assertIn("found", out.getvalue())
        self.assertTrue(out_json.exists())
        self.assertTrue(preview.exists())
        self.assertEqual(Board.load(out_json).validate(), [])

    def test_detect_can_solve_in_one_go(self):
        layout = Path(self.dir.name) / "l.png"
        with captured() as (out, _):
            code = main.main(["detect", str(self.image), "--solve",
                              "--preview", "", "--layout", str(layout),
                              "--attempts", "2", "--rounds", "1"])
        self.assertEqual(code, 0)
        self.assertIn("road tiles", out.getvalue())
        self.assertTrue(layout.exists())

    def test_a_missing_image_gives_a_clean_message(self):
        with self.assertRaises(SystemExit) as cm, captured():
            main.main(["detect", "nope.png", "--preview", ""])
        self.assertIn("no such image", str(cm.exception))

    def test_a_blank_image_is_reported_not_crashed(self):
        from PIL import Image

        blank = Path(self.dir.name) / "blank.png"
        Image.new("RGB", (60, 60), (247, 244, 236)).save(blank)
        with captured() as (_, err):
            code = main.main(["detect", str(blank), "--preview", ""])
        self.assertEqual(code, 1)
        self.assertIn("no buildings found", err.getvalue())


class BadInputTests(unittest.TestCase):
    """Every way of pointing the tool at something it cannot use should say so
    in one line, not unwind a traceback over the user."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

    def test_a_directory_given_as_a_board_is_reported(self):
        with self.assertRaises(SystemExit) as raised, captured():
            main.main(["solve", self.dir.name])
        self.assertIn("cannot read", str(raised.exception))

    def test_a_directory_given_as_an_image_is_reported(self):
        with self.assertRaises(SystemExit) as raised, captured():
            main.main(["detect", self.dir.name])
        self.assertIn("cannot read", str(raised.exception))

    def test_a_missing_board_is_reported(self):
        with self.assertRaises(SystemExit) as raised, captured():
            main.main(["solve", str(Path(self.dir.name) / "nope.json")])
        self.assertIn("no such board file", str(raised.exception))

    def test_negative_spread_is_rejected_by_the_parser(self):
        board = Path(self.dir.name) / "b.json"
        Board.from_ascii("r . R").save(board)
        with self.assertRaises(SystemExit), captured() as (_, err):
            main.main(["solve", str(board), "--spread", "-1"])
        self.assertIn("must not be negative", err.getvalue())

    def test_a_non_numeric_spread_is_rejected_by_the_parser(self):
        board = Path(self.dir.name) / "b.json"
        Board.from_ascii("r . R").save(board)
        with self.assertRaises(SystemExit), captured() as (_, err):
            main.main(["solve", str(board), "--spread", "banana"])
        self.assertIn("not a number", err.getvalue())


class ArgumentTests(unittest.TestCase):
    def test_no_subcommand_is_an_error(self):
        with self.assertRaises(SystemExit), captured():
            main.main([])

    def test_help_lists_the_commands(self):
        with self.assertRaises(SystemExit), captured() as (out, _):
            main.main(["--help"])
        text = out.getvalue()
        for cmd in ("solve", "detect", "capture"):
            self.assertIn(cmd, text)


if __name__ == "__main__":
    unittest.main()
