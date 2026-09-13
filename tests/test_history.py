"""Minute retention, missing data, validation and telemetry expiry."""

import unittest

from fan_history import FanHistory, CAPACITY


class HistoryChecks(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.history = FanHistory(lambda: self.now)

    def test_minute_samples_are_bounded_and_paginated(self):
        for minute in range(1500):
            self.now = minute * 60_000_000_000
            self.history.record(1000 + minute, 60)
        page = self.history.page()
        rows = page["rows"]
        while page["next_before"] is not None:
            page = self.history.page(page["next_before"])
            rows = page["rows"] + rows
        self.assertEqual(len(rows), CAPACITY)
        self.assertEqual(rows[0], [60, 1060, None, None, 60])
        self.assertEqual(rows[-1], [1499, 2499, None, None, 60])
        self.assertEqual(sum(len(s) * s.itemsize for s in self.history.samples), 11520)

    def test_only_one_sample_per_minute(self):
        self.history.record(None, 100)
        self.history.record(1200, 60)
        self.assertEqual(self.history.page()["rows"], [[0, None, None, None, 100]])

    def test_pause_creates_gaps_not_fabricated_samples(self):
        self.history.record(1200, 60)
        self.now = 180_000_000_000
        self.history.record(1000, 50)
        self.assertEqual(self.history.page()["rows"], [
            [0, 1200, None, None, 60], [1, None, None, None, None],
            [2, None, None, None, None], [3, 1000, None, None, 50]])

    def test_long_pause_discards_old_samples(self):
        self.history.record(1200, 60)
        self.now = 3000 * 60_000_000_000
        self.history.record(1000, 50)
        self.assertEqual(self.history.first_minute, 1561)
        self.assertEqual(self.history.page(1681)["rows"][0], [1561, None, None, None, None])

    def test_temperature_expiry_and_precision(self):
        self.history.update({"gpu_temperature_c": 52.34, "cpu_temperature_c": -5})
        self.history.record(1000, 60.25)
        self.assertEqual(self.history.page()["rows"], [[0, 1000, 52.3, -5, 60.25]])
        self.now = 120_000_000_000
        self.assertEqual(self.history.telemetry()["telemetry_state"], "stale")
        self.history.record(1000, 60)
        self.assertIsNone(self.history.page()["rows"][-1][2])

    def test_bad_telemetry_does_not_refresh_or_partially_update(self):
        self.history.update({"gpu_temperature_c": 50})
        self.now = 20_000_000_000
        for data in ({}, [], {"other": 30}, {"cpu_temperature_c": True},
                     {"gpu_temperature_c": 40, "cpu_temperature_c": 126},
                     {"cpu_temperature_c": float("nan")}, {"cpu_temperature_c": "50"}):
            with self.subTest(data=data), self.assertRaises(ValueError):
                self.history.update(data)
        self.assertEqual(self.history.gpu, 50)
        self.assertEqual(self.history.updated, 0)

    def test_bad_page_parameters(self):
        for before, limit in ((None, 121), (None, 0), (-1, 120), (0, True)):
            with self.assertRaises(ValueError):
                self.history.page(before, limit)

    def test_empty_history_and_omitted_sensor(self):
        self.assertEqual(self.history.page()["rows"], [])
        self.history.update({"gpu_temperature_c": 50, "cpu_temperature_c": 40})
        self.history.update({"cpu_temperature_c": 42})
        self.assertIsNone(self.history.telemetry()["gpu_temperature_c"])
