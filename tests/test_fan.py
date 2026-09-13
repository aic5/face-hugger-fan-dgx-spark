"""Desktop checks for control behavior; physical PWM is simulated."""

import unittest
from types import SimpleNamespace

from fan_control import FanControl, duty_value


class FanChecks(unittest.TestCase):
    def make_fan(self, remote=False, tach=None, **kwargs):
        self.now = 0
        self.pwm = SimpleNamespace(duty_cycle=0)
        return FanControl(self.pwm, tach, remote=remote, clock=lambda: self.now, **kwargs)

    def advance(self, fan, seconds):
        self.now += int(seconds * 1_000_000_000)
        fan.tick()

    def test_standalone_startup_then_sixty_percent(self):
        fan = self.make_fan()
        self.assertEqual(self.pwm.duty_cycle, 65535)
        self.advance(fan, 2)
        self.assertEqual(self.pwm.duty_cycle, 39321)

    def test_remote_waits_at_full_speed(self):
        fan = self.make_fan(remote=True)
        self.advance(fan, 40)
        self.assertEqual(fan.applied, 100)
        self.assertEqual(fan.state, "awaiting_command")

    def test_off_and_restart_boost(self):
        fan = self.make_fan(remote=True)
        fan.command(0)
        self.assertEqual(self.pwm.duty_cycle, 0)
        fan.command(40)
        self.assertEqual(fan.applied, 100)
        self.advance(fan, 1)
        fan.command(40)
        self.advance(fan, 1)
        self.assertEqual(fan.applied, 40)

    def test_zero_during_boost_stops_immediately(self):
        fan = self.make_fan(remote=True)
        fan.command(0)
        self.assertEqual(fan.applied, 0)
        self.assertIsNone(fan.boost_until)

    def test_timeout_recovers_even_from_off(self):
        fan = self.make_fan(remote=True)
        fan.command(0)
        self.advance(fan, 29)
        self.assertEqual(fan.applied, 0)
        self.advance(fan, 1)
        self.assertEqual(fan.applied, 100)
        self.assertEqual(fan.state, "command_timeout")

    def test_only_new_command_extends_timeout(self):
        fan = self.make_fan(remote=True)
        fan.command(0)
        self.advance(fan, 20)
        fan.status()
        self.advance(fan, 10)
        self.assertEqual(fan.state, "command_timeout")
        fan.command(40)
        self.advance(fan, 20)
        fan.command(40)
        self.advance(fan, 20)
        self.assertEqual(fan.applied, 40)

    def test_disconnect_cancels_old_command(self):
        fan = self.make_fan(remote=True)
        fan.command(0)
        fan.failsafe("wifi_disconnected")
        self.advance(fan, 3)
        self.assertEqual(fan.applied, 100)
        self.assertIsNone(fan.last_command)

    def test_duty_validation_does_not_change_output(self):
        fan = self.make_fan(remote=True)
        for invalid in (-1, 1, 19, 101, True, "60", None, float("nan"), float("inf")):
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                fan.command(invalid)
        self.assertIsNone(fan.last_command)
        self.assertEqual(fan.applied, 100)
        self.assertEqual(duty_value(0), 0)
        self.assertEqual(duty_value(20), 13107)
        self.assertEqual(duty_value(100), 65535)

    def test_rpm_and_counter_wrap(self):
        tach = SimpleNamespace(count=0xFFFFFFFF - 50)
        fan = self.make_fan(tach=tach)
        tach.count = (tach.count + 100) & 0xFFFFFFFF
        self.advance(fan, 2)
        self.assertEqual(fan.rpm, 1500)
        self.advance(fan, 2)
        self.assertEqual(fan.rpm, 0)

    def test_unconnected_tach_reports_unknown_not_stopped(self):
        fan = self.make_fan()
        self.advance(fan, 4)
        self.assertIsNone(fan.status()["rpm"])


if __name__ == "__main__":
    unittest.main()
