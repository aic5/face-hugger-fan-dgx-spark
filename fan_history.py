"""Bounded, RAM-only minute samples and DGX telemetry freshness."""

from array import array
import os

CAPACITY = 1440
MISSING = 65535
TELEMETRY_TTL = 120


class FanHistory:
    def __init__(self, clock):
        self.clock = clock
        self.boot_id = "".join("{:02x}".format(b) for b in os.urandom(4))
        self.started = clock()
        self.last_minute = None
        self.first_minute = None
        self.samples = [array("H", (MISSING for _ in range(CAPACITY))) for _ in range(4)]
        self.updated = None
        self.gpu = None
        self.cpu = None

    def update(self, data):
        keys = ("gpu_temperature_c", "cpu_temperature_c")
        if not isinstance(data, dict) or not data or any(k not in keys for k in data):
            raise ValueError("expected gpu_temperature_c and/or cpu_temperature_c")
        for value in data.values():
            if value is not None and (type(value) not in (int, float) or not -20 <= value <= 125):
                raise ValueError("temperature must be null or a number between -20 and 125 C")
        # Each update is a complete snapshot; omitted sensors are unavailable.
        self.gpu = data.get(keys[0])
        self.cpu = data.get(keys[1])
        self.updated = self.clock()

    def telemetry(self):
        age = None if self.updated is None else (self.clock() - self.updated) // 1_000_000_000
        fresh = age is not None and age < TELEMETRY_TTL
        return {
            "gpu_temperature_c": self.gpu if fresh else None,
            "cpu_temperature_c": self.cpu if fresh else None,
            "telemetry_age_seconds": age,
            "telemetry_state": "live" if fresh else "missing" if age is None else "stale",
        }

    def record(self, rpm, duty):
        minute = self.clock() // 60_000_000_000
        if minute == self.last_minute:
            return
        if self.first_minute is None:
            self.first_minute = minute
        if self.last_minute is not None:
            # Missing minutes stay gaps, including after a long pause.
            for skipped in range(max(self.last_minute + 1, minute - CAPACITY + 1), minute):
                for series in self.samples:
                    series[skipped % CAPACITY] = MISSING
        telemetry = self.telemetry()
        values = (None if rpm is None else min(max(round(rpm), 0), MISSING - 1),
                  telemetry["gpu_temperature_c"], telemetry["cpu_temperature_c"], duty)
        for index, value in enumerate(values):
            if value is not None and index in (1, 2):
                value = round((value + 20) * 10)
            elif value is not None and index == 3:
                value = round(value * 100)
            self.samples[index][minute % CAPACITY] = MISSING if value is None else value
        self.last_minute = minute
        self.first_minute = max(self.first_minute, minute - CAPACITY + 1)

    def page(self, before=None, limit=120):
        if type(limit) is not int or not 1 <= limit <= 120:
            raise ValueError("limit must be between 1 and 120")
        if before is not None and (type(before) is not int or before < 0):
            raise ValueError("before must be a nonnegative minute")
        end = 0 if self.last_minute is None else self.last_minute + 1
        if before is not None:
            end = min(end, before)
        first = end if self.first_minute is None else self.first_minute
        start = max(first, end - limit)
        rows = []
        for minute in range(start, end):
            row = [minute]
            for index, series in enumerate(self.samples):
                value = series[minute % CAPACITY]
                row.append(None if value == MISSING else
                           value / 10 - 20 if index in (1, 2) else
                           value / 100 if index == 3 else value)
            rows.append(row)
        return {"boot_id": self.boot_id, "now_seconds": self.clock() // 1_000_000_000,
                "interval_seconds": 60, "rows": rows,
                "next_before": start if start > first and rows else None}

    def status(self):
        result = self.telemetry()
        result.update({"boot_id": self.boot_id,
                       "uptime_seconds": (self.clock() - self.started) // 1_000_000_000,
                       "now_seconds": self.clock() // 1_000_000_000,
                       "history_minutes": 0 if self.last_minute is None else
                       self.last_minute - self.first_minute + 1})
        return result
