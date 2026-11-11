"""Button-window decisions. No GPIO, NetworkManager, or sound device."""

import importlib.util
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "wifi_provision_button",
    Path(__file__).resolve().parents[1] / "wifi-provision-button.py",
)
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)


class WindowTests(unittest.TestCase):
    def test_a_tap_inside_the_window_enters(self):
        action, streak, samples = MOD.next_action(1.0, False, 0, 0)
        self.assertEqual(action, "poll")
        action, streak, samples = MOD.next_action(1.2, True, streak, samples)
        self.assertEqual(action, "poll")
        action, _, _ = MOD.next_action(1.22, True, streak, samples)
        self.assertEqual(action, "enter")

    def test_one_low_sample_is_not_a_press(self):
        action, streak, samples = MOD.next_action(1.0, True, 0, 0)
        self.assertEqual(action, "poll")
        action, _, _ = MOD.next_action(1.1, False, streak, samples)
        self.assertEqual(action, "poll")

    def test_released_after_the_window_stops(self):
        action, _, _ = MOD.next_action(6.0, False, 0, 0)
        self.assertEqual(action, "stop")

    def test_a_button_still_held_after_a_late_start_enters(self):
        action, streak, samples = MOD.next_action(8.0, True, 0, 0)
        self.assertEqual(action, "poll")
        action, _, _ = MOD.next_action(8.02, True, streak, samples)
        self.assertEqual(action, "enter")

    def test_the_window_boundary_is_inclusive(self):
        action, _, _ = MOD.next_action(5.0, False, 0, 0)
        self.assertEqual(action, "poll")


class PageTests(unittest.TestCase):
    def test_page_uses_the_console_sticker_and_the_microduck_hotspot(self):
        body = MOD.page([("家里的网", "80", "WPA2")], "")
        self.assertIn("MicroDuck", body)
        self.assertIn("Microduck", body)
        self.assertNotIn("kissqy", body.lower())
        self.assertIn("#e8ff47", body)
        self.assertIn("家里的网", body)
        self.assertNotIn("<script", body.lower())

    def test_a_failure_and_a_success_look_different(self):
        failed = MOD.page([], "没有连上")
        joined = MOD.page([], "已连上 家里的网。热点会关闭。")
        self.assertIn('class="banner warn"', failed)
        self.assertIn('class="banner ok"', joined)


class ParseTests(unittest.TestCase):
    def test_libgpiod_v1_prints_the_level(self):
        self.assertEqual(MOD.parse_gpioget("0\n"), 0)
        self.assertEqual(MOD.parse_gpioget("1\n"), 1)

    def test_inactive_is_not_read_as_active(self):
        self.assertEqual(MOD.parse_gpioget('"20"=inactive\n'), 0)
        self.assertEqual(MOD.parse_gpioget('"20"=active\n'), 1)

    def test_chip_label(self):
        text = "gpiochip0 [gpio0] (32 lines)\ngpiochip3 [gpio3] (32 lines)\n"
        self.assertEqual(MOD.chip_from_detect(text), "gpiochip3")
        self.assertIsNone(MOD.chip_from_detect("gpiochip0 [gpio0] (32 lines)\n"))


if __name__ == "__main__":
    unittest.main()
