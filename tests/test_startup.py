"""Run the board entry point with simulated hardware and configuration."""

import contextlib
import importlib.util
import io
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

from fan_control import FanControl


class StartupChecks(unittest.TestCase):
    def exercise(self, settings, fail_sleep=False, counter_error=False,
                 network_error=None, unreadable=None, duration=2.1,
                 pulse_rate=0, counter_start=0):
        clock = [0]
        writes = []

        class PWM:
            def __init__(self, pin, *, frequency, duty_cycle):
                self._duty = duty_cycle
                writes.append(duty_cycle)

            @property
            def duty_cycle(self):
                return self._duty

            @duty_cycle.setter
            def duty_cycle(self, value):
                self._duty = value
                writes.append(value)

            def deinit(self):
                writes.append("released")

        def sleep(seconds):
            clock[0] += int(seconds * 1_000_000_000)
            if fail_sleep and clock[0] == 50_000_000:
                raise RuntimeError("simulated loop error")
            if clock[0] >= int(duration * 1_000_000_000):
                raise KeyboardInterrupt()

        class Counter:
            def __init__(self, *args, **kwargs):
                if counter_error:
                    raise ValueError("simulated counter error")

            @property
            def count(self):
                return (counter_start + clock[0] * pulse_rate // 1_000_000_000) & 0xFFFFFFFF

            def deinit(self):
                pass

        def getenv(name, default=None):
            if name == unreadable:
                raise ValueError("parser error containing a secret")
            return settings.get(name, default)

        server = types.SimpleNamespace(
            start=lambda *a, **k: None, stop=lambda: None, poll=lambda: None
        )
        modules = {
            "board": types.SimpleNamespace(GP15=15, GP13=13),
            "countio": types.SimpleNamespace(Counter=Counter, Edge=types.SimpleNamespace(FALL=1)),
            "digitalio": types.SimpleNamespace(Pull=types.SimpleNamespace(UP=1)),
            "pwmio": types.SimpleNamespace(PWMOut=PWM),
            "wifi": types.SimpleNamespace(radio=types.SimpleNamespace(
                connected=True, ipv4_address="192.0.2.10"
            )),
            "socketpool": types.SimpleNamespace(SocketPool=lambda radio: object()),
            "mdns": None,
        }
        spec = importlib.util.spec_from_file_location(
            "fan_entrypoint", Path(__file__).resolve().parents[1] / "code.py"
        )
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, modules):
            spec.loader.exec_module(module)
        module.FanControl = lambda *args, **kwargs: FanControl(
            *args, clock=lambda: clock[0], **kwargs
        )
        output = io.StringIO()
        with patch.dict(sys.modules, modules), \
                patch("wifi_control.make_server", return_value=server, side_effect=network_error), \
                patch.object(module.os, "getenv", side_effect=getenv), \
                patch.object(module.time, "sleep", side_effect=sleep), \
                patch.object(module.time, "monotonic_ns", side_effect=lambda: clock[0]), \
                contextlib.redirect_stdout(output):
            with self.assertRaises(KeyboardInterrupt):
                module.run()
        self.assertIn("Boot complete", output.getvalue())
        return writes, output.getvalue()

    def test_no_settings_runs_standalone(self):
        writes, output = self.exercise({})
        self.assertIn(39321, writes)
        self.assertEqual(writes[-1], "released")
        self.assertIn("Standalone mode", output)

    def test_invalid_setting_holds_full_speed(self):
        writes, output = self.exercise({"WIFI_ENABLED": "invalid"})
        self.assertNotIn(39321, writes)
        self.assertIn("Holding 100% PWM", output)
        self.assertIn("WIFI_ENABLED must be 0 or 1", output)
        self.assertIn("PWM: 100% | RPM: None | configuration_error", output)

    def wifi_settings(self):
        return {"WIFI_ENABLED": "1", "WIFI_SSID": "private-network",
                "WIFI_PASSWORD": "private-password",
                "FAN_WEB_USERNAME": "dashboard-user",
                "FAN_WEB_PASSWORD": "dashboard-password"}

    def test_unwired_board_boots_with_wifi(self):
        writes, output = self.exercise(self.wifi_settings())
        self.assertTrue(all(value == 65535 for value in writes[:-1]))
        self.assertIn("Wi-Fi control enabled", output)
        self.assertIn("Fan API:", output)

    def test_unchanged_wifi_status_prints_only_once(self):
        _, output = self.exercise(self.wifi_settings(), duration=8.1)
        reports = [line for line in output.splitlines() if line.startswith("PWM:")]
        self.assertEqual(reports, [
            "PWM: 100% | RPM: None | awaiting_command",
            "PWM: 100% | RPM: 0 | awaiting_command",
        ])

    def test_startup_duty_change_is_reported_without_repeats(self):
        _, output = self.exercise({}, duration=8.1)
        reports = [line for line in output.splitlines() if line.startswith("PWM:")]
        self.assertEqual(reports, [
            "PWM: 100% | RPM: None | startup",
            "PWM: 60% | RPM: 0 | standalone",
        ])

    def test_rpm_and_state_changes_are_reported_at_constant_pwm(self):
        _, output = self.exercise({"FAN_DUTY_PERCENT": 100}, duration=8.1)
        reports = [line for line in output.splitlines() if line.startswith("PWM:")]
        self.assertEqual(reports, [
            "PWM: 100% | RPM: None | startup",
            "PWM: 100% | RPM: 0 | standalone",
        ])

    def test_obsolete_token_setting_does_not_block_wifi(self):
        settings = self.wifi_settings()
        settings["FAN_API_TOKEN"] = "old-value-is-ignored"
        writes, output = self.exercise(settings)
        self.assertIn("Fan API:", output)
        self.assertNotIn("old-value-is-ignored", output)
        self.assertTrue(all(value == 65535 for value in writes[:-1]))

    def test_missing_credentials_finish_boot(self):
        _, output = self.exercise({"WIFI_ENABLED": "1"})
        self.assertIn("WIFI_SSID and WIFI_PASSWORD are required", output)

    def test_missing_web_login_finishes_boot_at_full_speed(self):
        settings = {"WIFI_ENABLED": "1", "WIFI_SSID": "private-network",
                    "WIFI_PASSWORD": "private-password"}
        writes, output = self.exercise(settings)
        self.assertIn("FAN_WEB_USERNAME and FAN_WEB_PASSWORD are required", output)
        self.assertNotIn("Fan API:", output)
        self.assertTrue(all(value == 65535 for value in writes[:-1]))

    def test_bad_numeric_settings_finish_boot_at_full_speed(self):
        for name, value in (("FAN_DUTY_PERCENT", "bad"), ("FAN_DUTY_PERCENT", 10),
                            ("FAN_COMMAND_TIMEOUT", 0), ("FAN_HTTP_PORT", 70000)):
            with self.subTest(name=name, value=value):
                settings = {} if name == "FAN_DUTY_PERCENT" else self.wifi_settings()
                settings[name] = value
                writes, output = self.exercise(settings)
                self.assertIn(name + " must be an integer", output)
                self.assertIn("configuration_error", output)
                self.assertTrue(all(value == 65535 for value in writes[:-1]))

    def test_unused_standalone_duty_does_not_block_wifi(self):
        settings = self.wifi_settings()
        settings["FAN_DUTY_PERCENT"] = "invalid"
        _, output = self.exercise(settings)
        self.assertIn("Fan API:", output)

    def test_unreadable_settings_do_not_expose_values(self):
        _, output = self.exercise({}, unreadable="WIFI_ENABLED")
        self.assertIn("Cannot read WIFI_ENABLED", output)
        self.assertNotIn("parser error containing a secret", output)

    def test_counter_failure_does_not_block_boot(self):
        writes, output = self.exercise({}, counter_error=True)
        self.assertIn("RPM unavailable: GP13 counter initialization failed (ValueError)", output)
        self.assertIn(39321, writes)

    def test_unwired_tach_reads_zero(self):
        _, output = self.exercise({})
        self.assertIn("RPM: 0", output)

    def test_tach_debug_repeats_zero_every_five_seconds(self):
        _, output = self.exercise({}, duration=10.1)
        reports = [line for line in output.splitlines() if line.startswith("TACH GP13")]
        self.assertEqual(reports, [
            "TACH GP13 (pin 17): total=0 | pulses=0 / 5.00s | window_RPM=0 | PWM=60%",
        ] * 2)

    def test_tach_debug_reports_raw_counts_without_disturbing_rpm(self):
        _, output = self.exercise({}, duration=10.1, pulse_rate=50)
        reports = [line for line in output.splitlines() if line.startswith("TACH GP13")]
        self.assertEqual(reports, [
            "TACH GP13 (pin 17): total=250 | pulses=250 / 5.00s | window_RPM=1500 | PWM=60%",
            "TACH GP13 (pin 17): total=500 | pulses=250 / 5.00s | window_RPM=1500 | PWM=60%",
        ])
        normal = [line for line in output.splitlines() if line.startswith("PWM:")]
        self.assertEqual(normal, [
            "PWM: 100% | RPM: None | startup",
            "PWM: 60% | RPM: 1500 | standalone",
        ])

    def test_tach_debug_handles_counter_wrap(self):
        _, output = self.exercise({}, duration=5.1,
                                  pulse_rate=50, counter_start=0xFFFFFFF0)
        self.assertIn("total=234 | pulses=250 / 5.00s | window_RPM=1500", output)

    def test_tach_debug_explains_unavailable_counter(self):
        _, output = self.exercise({}, counter_error=True, duration=10.1)
        reports = [line for line in output.splitlines() if line.startswith("TACH GP13")]
        self.assertEqual(reports, [
            "TACH GP13 (pin 17): unavailable; check boot warnings",
        ] * 2)

    def test_network_initialization_errors_finish_boot(self):
        for error in (ImportError("missing library"), ValueError("secret connection detail")):
            with self.subTest(error=type(error).__name__):
                writes, output = self.exercise(self.wifi_settings(), network_error=error)
                self.assertIn("wifi_unavailable", output)
                self.assertNotIn("secret connection detail", output)
                self.assertTrue(all(value == 65535 for value in writes[:-1]))

    def test_loop_error_holds_full_speed(self):
        writes, output = self.exercise({}, fail_sleep=True)
        self.assertEqual(writes[-2:], [65535, "released"])
        self.assertIn("Controller error: RuntimeError", output)
