"""Stepped temperature policy, validation and non-secret file configuration."""

import json
from pathlib import Path
import tempfile
import unittest

from fan_curve import FanCurve, DEFAULTS, validate_curve


class CurveChecks(unittest.TestCase):
    def test_exact_thresholds_are_steps_not_interpolation(self):
        curve = FanCurve()
        for temperature, expected in ((40, 0), (45, 0), (49.9, 0), (50, 30),
                                      (55, 30), (59.9, 30), (60, 60),
                                      (74.9, 60), (75, 100), (100, 100)):
            with self.subTest(temperature=temperature):
                self.assertEqual(curve.duty_for_temperature(temperature), expected)

    def test_running_fan_stops_at_lower_threshold(self):
        curve = FanCurve()
        self.assertEqual(curve.duty_for_temperature(47, was_running=True), 30)
        self.assertEqual(curve.duty_for_temperature(45, was_running=True), 0)
        self.assertEqual(curve.duty_for_temperature(47, was_running=False), 0)

    def test_unavailable_or_invalid_temperature_requests_full_speed(self):
        for temperature in (None, "50", True, float("nan"), float("inf"), 126):
            self.assertEqual(FanCurve().duty_for_temperature(temperature), 100)

    def test_invalid_curves_do_not_replace_valid_settings(self):
        curve = FanCurve()
        cases = [{}, [], {**DEFAULTS, "extra": 0}, {**DEFAULTS, "off_temp_c": True},
                 {**DEFAULTS, "off_temp_c": 51}, {**DEFAULTS, "temperature_source": "ambient"},
                 {**DEFAULTS, "steps": []}]
        for t, pwm in ((50, 0), (50, 101), (50, 100), (float("nan"), 30), (130, 30)):
            data = validate_curve(DEFAULTS)
            data["steps"][0] = {"temperature_c": t, "pwm_percent": pwm}
            cases.append(data)
        for data in cases:
            with self.subTest(data=data), self.assertRaises(ValueError):
                curve.update(data)
        self.assertEqual(curve.settings, DEFAULTS)
        self.assertEqual(curve.revision, 0)

    def test_requires_ordered_steps_and_final_full_speed(self):
        for steps in ([{"temperature_c": 55, "pwm_percent": 100}],
                      [{"temperature_c": 55, "pwm_percent": 30}, {"temperature_c": 55, "pwm_percent": 100}],
                      [{"temperature_c": 55, "pwm_percent": 70}, {"temperature_c": 60, "pwm_percent": 60}],
                      [{"temperature_c": 55, "pwm_percent": 30}, {"temperature_c": 60, "pwm_percent": 90}],
                      [{"temperature_c": 50 + i, "pwm_percent": 30 + i} for i in range(9)]):
            with self.assertRaises(ValueError):
                validate_curve({**DEFAULTS, "steps": steps})

    def test_changes_are_deep_copied_and_session_only(self):
        curve = FanCurve()
        data = validate_curve(DEFAULTS)
        data["steps"][1]["pwm_percent"] = 70
        curve.update(data)
        data["steps"][1]["pwm_percent"] = 20
        self.assertEqual(curve.duty_for_temperature(65), 70)
        status = curve.status()
        self.assertTrue(status["automatic_control_active"])
        self.assertEqual(status["source"], "session")
        status["settings"]["steps"][0]["pwm_percent"] = 99
        self.assertEqual(curve.settings["steps"][0]["pwm_percent"], 30)

    def test_automatic_control_defaults_on_and_requires_a_boolean(self):
        curve = FanCurve()
        self.assertTrue(curve.status()["automatic_control_active"])
        curve.set_automatic(False)
        self.assertFalse(curve.status()["automatic_control_active"])
        for value in (0, 1, None, "true"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                curve.set_automatic(value)

    def test_file_roundtrip_and_session_reset(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fan_curve.json"
            path.write_text(json.dumps(DEFAULTS))
            curve = FanCurve()
            curve.load(str(path))
            self.assertEqual(curve.source, "file")
            data = validate_curve(DEFAULTS)
            data["off_temp_c"] = 42
            curve.update(data)
            self.assertEqual(json.loads(path.read_text()), DEFAULTS)
            curve.load(str(path))
            self.assertEqual(curve.settings, DEFAULTS)
