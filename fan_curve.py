"""Validated temperature policy and automatic-control state."""

import json

DEFAULTS = {
    "temperature_source": "max",
    "off_temp_c": 45,
    "steps": [{"temperature_c": 50, "pwm_percent": 30},
              {"temperature_c": 60, "pwm_percent": 60},
              {"temperature_c": 75, "pwm_percent": 100}],
}


def validate_curve(data):
    if not isinstance(data, dict) or set(data) != set(DEFAULTS):
        raise ValueError("send temperature_source, off_temp_c, and steps only")
    if data["temperature_source"] not in ("max", "gpu", "cpu"):
        raise ValueError("temperature_source must be max, gpu, or cpu")
    off = data["off_temp_c"]
    if type(off) not in (int, float) or not 0 <= off <= 125:
        raise ValueError("stop temperature must be a finite number from 0 to 125")
    steps = data["steps"]
    if not isinstance(steps, list) or not 2 <= len(steps) <= 8:
        raise ValueError("use 2 to 8 running steps, ending at 100%")
    previous_temperature, previous_pwm = off, 20
    for index, step in enumerate(steps):
        if not isinstance(step, dict) or set(step) != {"temperature_c", "pwm_percent"}:
            raise ValueError("each step requires temperature_c and pwm_percent")
        temperature, pwm = step["temperature_c"], step["pwm_percent"]
        if type(temperature) not in (int, float) or not previous_temperature < temperature <= 125:
            raise ValueError("step temperatures must increase above the stop temperature, up to 125 C")
        if type(pwm) not in (int, float) or not previous_pwm <= pwm <= 100:
            raise ValueError("PWM steps must be nondecreasing, between 20 and 100%")
        if (index == len(steps) - 1 and pwm != 100) or (index < len(steps) - 1 and pwm >= 100):
            raise ValueError("only the final step must be 100%")
        previous_temperature, previous_pwm = temperature, pwm
    return {"temperature_source": data["temperature_source"], "off_temp_c": off,
            "steps": [dict(step) for step in steps]}


class FanCurve:
    def __init__(self):
        self.settings = validate_curve(DEFAULTS)
        self.source = "defaults"
        self.revision = 0
        # Cooling should resume automatically after a Pico or DGX restart. The
        # DGX service also reapplies its configured default when it starts.
        self.automatic_control_active = True

    def load(self, path="fan_curve.json"):
        with open(path, "r") as handle:
            settings = validate_curve(json.load(handle))
        self.settings = settings
        self.source = "file"
        self.revision += 1

    def update(self, data):
        self.settings = validate_curve(data)
        self.source = "session"
        self.revision += 1

    def set_automatic(self, active):
        if type(active) is not bool:
            raise ValueError("active must be true or false")
        self.automatic_control_active = active

    def status(self):
        return {"settings": validate_curve(self.settings), "source": self.source,
                "revision": self.revision,
                "automatic_control_active": self.automatic_control_active}

    def duty_for_temperature(self, temperature, was_running=False):
        """Pure policy calculation; caller must supply fresh, selected telemetry."""
        if type(temperature) not in (int, float) or not -20 <= temperature <= 125:
            return 100
        curve = self.settings
        if temperature <= curve["off_temp_c"]:
            return 0
        first = curve["steps"][0]
        if temperature < first["temperature_c"]:
            return first["pwm_percent"] if was_running else 0
        duty = first["pwm_percent"]
        for step in curve["steps"]:
            if temperature < step["temperature_c"]:
                break
            duty = step["pwm_percent"]
        return duty
