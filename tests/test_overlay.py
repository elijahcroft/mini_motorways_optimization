import unittest
from unittest import mock

import conftest_path  # noqa: F401

import overlay


class GrabTests(unittest.TestCase):
    """`overlay.grab` picks the right capture tool for the session and says
    clearly when it is missing, instead of crashing mid-grab."""

    def test_wayland_without_grim_raises_a_clear_error(self):
        with mock.patch.dict("os.environ", {"WAYLAND_DISPLAY": "wayland-1"},
                             clear=True), \
             mock.patch("shutil.which", return_value=None), \
             self.assertRaises(RuntimeError) as raised:
            overlay.grab("shot.png")
        self.assertIn("grim", str(raised.exception))

    def test_wayland_runs_grim(self):
        with mock.patch.dict("os.environ", {"WAYLAND_DISPLAY": "wayland-1"},
                             clear=True), \
             mock.patch("shutil.which", return_value="/usr/bin/grim"), \
             mock.patch("subprocess.run") as run:
            overlay.grab("shot.png")
        run.assert_called_once_with(["grim", "shot.png"],
                                    check=True, capture_output=True)

    def test_x11_without_pyautogui_raises_a_clear_error(self):
        # A module that is None in sys.modules makes `import` raise ImportError,
        # which is exactly what an absent pyautogui does.
        with mock.patch.dict("os.environ", {}, clear=True), \
             mock.patch.dict("sys.modules", {"pyautogui": None}), \
             self.assertRaises(RuntimeError) as raised:
            overlay.grab("shot.png")
        self.assertIn("pyautogui", str(raised.exception))

    def test_x11_saves_via_pyautogui(self):
        pyautogui = mock.Mock()
        with mock.patch.dict("os.environ", {}, clear=True), \
             mock.patch.dict("sys.modules", {"pyautogui": pyautogui}):
            overlay.grab("shot.png")
        pyautogui.screenshot.assert_called_once()
        pyautogui.screenshot.return_value.save.assert_called_once_with("shot.png")


if __name__ == "__main__":
    unittest.main()
