"""Fan state, startup boost, RPM sampling and remote-command timeout."""

import time

from fan_history import FanHistory
from fan_curve import FanCurve


def duty_value(percent):
    if type(percent) not in (int, float) or (percent != 0 and not 20 <= percent <= 100):
        raise ValueError("duty must be 0 (off), or a number from 20 to 100")
    return round(percent * 65535 / 100)


class FanControl:
    def __init__(self, pwm, tach=None, *, remote=False, default_duty=60,
                 timeout=30, clock=time.monotonic_ns):
        duty_value(default_duty)
        if not 5 <= timeout <= 300:
            raise ValueError("command timeout must be between 5 and 300 seconds")
        self.pwm = pwm
        self.tach = tach
        self.remote = remote
        self.clock = clock
        self.history = FanHistory(clock)
        self.curve = FanCurve()
        self.timeout_ns = timeout * 1_000_000_000
        self.last_command = None
        self.target = 100 if remote else default_duty
        self.applied = 100
        self.state = "awaiting_command" if remote else "startup"
        now = clock()
        self.boost_until = now + 2_000_000_000
        self.sample_time = now
        self.sample_count = tach.count if tach is not None else 0
        self.rpm = None
        self.pwm.duty_cycle = 65535

    def _apply(self, duty):
        if duty != self.applied:
            self.pwm.duty_cycle = duty_value(duty)
            self.applied = duty

    def command(self, duty):
        duty_value(duty)
        now = self.clock()
        if duty == 0:
            self.boost_until = None
        elif self.applied == 0:
            self.boost_until = now + 2_000_000_000
        self.target = duty
        self.last_command = now
        self.state = "controlled"
        self.tick()

    def failsafe(self, reason):
        self.last_command = None
        self.boost_until = None
        self.target = 100
        self.state = reason
        self._apply(100)

    def tick(self):
        now = self.clock()
        if (self.remote and self.last_command is not None
                and now - self.last_command >= self.timeout_ns):
            self.failsafe("command_timeout")
        if self.boost_until is not None and now >= self.boost_until:
            self.boost_until = None
            if self.state == "startup":
                self.state = "standalone"
        self._apply(100 if self.boost_until is not None else self.target)

        elapsed = now - self.sample_time
        if self.tach is not None and elapsed >= 2_000_000_000:
            count = self.tach.count
            pulses = (count - self.sample_count) & 0xFFFFFFFF
            self.rpm = round(pulses * 60_000_000_000 / (2 * elapsed))
            self.sample_count, self.sample_time = count, now
        self.history.record(self.rpm, self.applied)

    def status(self):
        age = None if self.last_command is None else (
            self.clock() - self.last_command
        ) // 1_000_000_000
        result = {
            "mode": "wifi" if self.remote else "standalone",
            "state": self.state,
            "requested_duty": self.target,
            "applied_duty": self.applied,
            "startup_boost": self.boost_until is not None,
            "rpm": self.rpm,
            "command_age_seconds": age,
            "command_timeout_seconds": self.timeout_ns // 1_000_000_000,
            "automatic_control_active": self.curve.automatic_control_active,
        }
        result.update(self.history.status())
        return result
