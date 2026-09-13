"""DGX sensor discovery and authenticated Pico telemetry tests."""

from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from urllib.error import HTTPError

from dgx.dgx_fan_telemetry import (
    PicoClient,
    TelemetryError,
    automatic_duty,
    checked_temperature,
    parse_nvidia_smi,
    read_cpu_temperature,
)


class FakeResponse:
    def __init__(self, data):
        self.data = json.dumps(data).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.data


class FakeOpener:
    def __init__(self):
        self.calls = []

    def open(self, request, timeout):
        path = request.full_url.rsplit("/api/", 1)[-1]
        data = None if request.data is None else json.loads(request.data)
        self.calls.append((path, data, timeout))
        if len(self.calls) == 1:
            raise HTTPError(request.full_url, 401, "Unauthorized", {}, BytesIO(b"{}"))
        if path == "login":
            return FakeResponse({"authenticated": True})
        if path == "curve":
            return FakeResponse({
                "settings": {
                    "temperature_source": "max", "off_temp_c": 45,
                    "steps": [
                        {"temperature_c": 50, "pwm_percent": 30},
                        {"temperature_c": 75, "pwm_percent": 100},
                    ],
                },
                "automatic_control_active": True,
            })
        return FakeResponse({"telemetry_state": "live"})


class DgxTelemetryChecks(unittest.TestCase):
    def test_temperature_validation_and_gpu_output(self):
        self.assertEqual(checked_temperature("48.26"), 48.3)
        self.assertEqual(parse_nvidia_smi("41\n47\n"), 47)
        for value in ("bad", "nan", -21, 126):
            with self.subTest(value=value), self.assertRaises(TelemetryError):
                checked_temperature(value)

    def test_cpu_zone_discovery_uses_hottest_cpu_or_soc_zone(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for index, (kind, value) in enumerate((
                ("iwlwifi", "80000"), ("CPU-therm", "51250"), ("soc_thermal", "54000"),
                ("acpitz", "52700")
            )):
                zone = root / ("thermal_zone" + str(index))
                zone.mkdir()
                (zone / "type").write_text(kind)
                (zone / "temp").write_text(value)
            value, source = read_cpu_temperature(root)
            self.assertEqual(value, 54)
            self.assertIn("soc_thermal", source)
            value, source = read_cpu_temperature(root, root / "thermal_zone1")
            self.assertEqual(value, 51.2)
            self.assertIn("CPU-therm", source)

    def test_missing_cpu_zone_is_reported(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(TelemetryError):
                read_cpu_temperature(Path(folder))

    def test_client_reauthenticates_and_retries_after_401(self):
        opener = FakeOpener()
        client = PicoClient("http://pico", "user", "password", opener=opener)
        snapshot = {"gpu_temperature_c": 51, "cpu_temperature_c": 46}
        result = client.send(snapshot)
        self.assertEqual(result["telemetry_state"], "live")
        self.assertEqual([call[0] for call in opener.calls], ["telemetry", "login", "telemetry"])
        self.assertEqual(opener.calls[0][1], snapshot)
        self.assertEqual(set(opener.calls[1][1]), {"username", "password"})

    def test_client_requires_configuration(self):
        for values in (("", "user", "pass"), ("http://pico", "", "pass"),
                       ("http://pico", "user", "")):
            with self.subTest(values=values), self.assertRaises(TelemetryError):
                PicoClient(*values)

    def test_client_commands_and_releases_the_fan(self):
        opener = FakeOpener()
        client = PicoClient("http://pico", "user", "password", opener=opener)
        client.command(30)
        client.release()
        self.assertEqual(
            [call[0] for call in opener.calls],
            ["fan", "login", "fan", "release"],
        )
        self.assertEqual(opener.calls[-1][1], {})

    def test_curve_selects_hottest_temperature_and_hysteresis(self):
        status = {
            "settings": {
                "temperature_source": "max", "off_temp_c": 45,
                "steps": [
                    {"temperature_c": 50, "pwm_percent": 30},
                    {"temperature_c": 60, "pwm_percent": 60},
                    {"temperature_c": 75, "pwm_percent": 100},
                ],
            },
            "automatic_control_active": True,
        }
        self.assertEqual(automatic_duty(
            {"gpu_temperature_c": 49, "cpu_temperature_c": 50}, status
        ), 30)
        self.assertEqual(automatic_duty(
            {"gpu_temperature_c": 47, "cpu_temperature_c": 46}, status, True
        ), 30)
        self.assertEqual(automatic_duty(
            {"gpu_temperature_c": 47, "cpu_temperature_c": 46}, status, False
        ), 0)
        status["automatic_control_active"] = False
        self.assertIsNone(automatic_duty(
            {"gpu_temperature_c": 80, "cpu_temperature_c": 80}, status
        ))

    def test_missing_selected_temperature_requests_full_speed(self):
        status = {
            "settings": {
                "temperature_source": "max", "off_temp_c": 45,
                "steps": [
                    {"temperature_c": 50, "pwm_percent": 30},
                    {"temperature_c": 75, "pwm_percent": 100},
                ],
            },
            "automatic_control_active": True,
        }
        self.assertEqual(automatic_duty(
            {"gpu_temperature_c": 50, "cpu_temperature_c": None}, status
        ), 100)


if __name__ == "__main__":
    unittest.main()
