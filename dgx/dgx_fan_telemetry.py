#!/usr/bin/env python3
"""Read DGX temperatures and apply the Pico W fan curve."""

import argparse
import http.cookiejar
import json
import logging
import math
import os
from pathlib import Path
import shlex
import subprocess
import time
import urllib.error
import urllib.request

from fan_curve import FanCurve, validate_curve


LOG = logging.getLogger("dgx-fan-telemetry")
DEFAULT_GPU_COMMAND = (
    "nvidia-smi",
    "--query-gpu=temperature.gpu",
    "--format=csv,noheader,nounits",
)
CPU_ZONE_HINTS = ("cpu", "soc", "package", "pkg", "acpitz")
CPU_ZONE_EXCLUSIONS = ("gpu", "wifi", "iwl", "nvme", "ssd")


class TelemetryError(RuntimeError):
    """A sensor, configuration, or Pico communication error."""


def checked_temperature(value):
    try:
        temperature = float(value)
    except (TypeError, ValueError) as error:
        raise TelemetryError("temperature is not numeric") from error
    if not math.isfinite(temperature) or not -20 <= temperature <= 125:
        raise TelemetryError("temperature is outside -20 to 125 C")
    return round(temperature, 1)


def parse_nvidia_smi(output):
    readings = []
    for line in output.splitlines():
        value = line.strip()
        if not value:
            continue
        try:
            readings.append(checked_temperature(value))
        except TelemetryError:
            continue
    if not readings:
        raise TelemetryError("nvidia-smi returned no valid GPU temperature")
    return max(readings)


def read_gpu_temperature(command=DEFAULT_GPU_COMMAND):
    try:
        result = subprocess.run(
            command, check=True, capture_output=True, text=True, timeout=8,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise TelemetryError("unable to read GPU temperature with nvidia-smi") from error
    return parse_nvidia_smi(result.stdout), "nvidia-smi"


def thermal_zones(root=Path("/sys/class/thermal")):
    zones = []
    for zone in sorted(root.glob("thermal_zone*")):
        try:
            kind = (zone / "type").read_text(encoding="utf-8").strip()
            raw = (zone / "temp").read_text(encoding="utf-8").strip()
            value = float(raw)
            if abs(value) >= 1000:
                value /= 1000
            temperature = checked_temperature(value)
        except (OSError, ValueError, TelemetryError):
            continue
        zones.append((kind, temperature, zone))
    return zones


def read_cpu_temperature(root=Path("/sys/class/thermal"), override=None):
    zones = thermal_zones(root)
    if override:
        requested = Path(override).resolve()
        if requested.name == "temp":
            requested = requested.parent
        matches = [zone for zone in zones if zone[2].resolve() == requested]
        if not matches:
            raise TelemetryError("configured CPU thermal zone is unavailable")
    else:
        matches = [
            zone for zone in zones
            if any(hint in zone[0].lower() for hint in CPU_ZONE_HINTS)
            and not any(excluded in zone[0].lower() for excluded in CPU_ZONE_EXCLUSIONS)
        ]
        if not matches:
            raise TelemetryError("no CPU or SoC thermal zone was detected")
    kind, temperature, zone = max(matches, key=lambda item: item[1])
    return temperature, "{} ({})".format(kind, zone)


def read_temperatures(cpu_zone=None, gpu_command=DEFAULT_GPU_COMMAND):
    snapshot = {"gpu_temperature_c": None, "cpu_temperature_c": None}
    sources = {}
    errors = {}
    try:
        snapshot["gpu_temperature_c"], sources["gpu"] = read_gpu_temperature(gpu_command)
    except TelemetryError as error:
        errors["gpu"] = str(error)
    try:
        snapshot["cpu_temperature_c"], sources["cpu"] = read_cpu_temperature(override=cpu_zone)
    except TelemetryError as error:
        errors["cpu"] = str(error)
    if all(value is None for value in snapshot.values()):
        raise TelemetryError("no valid CPU or GPU temperature is available")
    return snapshot, sources, errors


def automatic_duty(snapshot, curve_status, was_running=False):
    """Return the curve duty, None when paused, or full speed on missing data."""
    if not isinstance(curve_status, dict):
        raise TelemetryError("Pico returned an invalid curve response")
    active = curve_status.get("automatic_control_active")
    if type(active) is not bool:
        raise TelemetryError("Pico returned an invalid automatic-control state")
    if not active:
        return None
    try:
        settings = validate_curve(curve_status.get("settings"))
    except (ValueError, TypeError) as error:
        raise TelemetryError("Pico returned invalid fan-curve settings") from error
    source = settings["temperature_source"]
    if source == "max":
        values = [snapshot.get("gpu_temperature_c"), snapshot.get("cpu_temperature_c")]
    else:
        values = [snapshot.get(source + "_temperature_c")]
    # An unknown selected sensor could be hotter than the available reading.
    if any(value is None for value in values):
        return 100
    curve = FanCurve()
    curve.settings = settings
    return curve.duty_for_temperature(max(values), was_running)


class PicoClient:
    def __init__(self, base_url, username, password, timeout=6, opener=None):
        if not base_url or not username or not password:
            raise TelemetryError(
                "DGX_FAN_PICO_URL, DGX_FAN_USERNAME, and DGX_FAN_PASSWORD are required"
            )
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.timeout = timeout
        if opener is None:
            jar = http.cookiejar.CookieJar()
            opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        self.opener = opener

    def _request(self, path, data=None):
        payload = None if data is None else (json.dumps(data) + "\n").encode("utf-8")
        request = urllib.request.Request(
            self.base_url + path,
            data=payload,
            headers={} if payload is None else {"Content-Type": "application/json"},
            method="GET" if payload is None else "POST",
        )
        with self.opener.open(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def _authenticated(self, path, data=None, action="contact the Pico"):
        try:
            return self._request(path, data)
        except urllib.error.HTTPError as error:
            if error.code != 401:
                raise TelemetryError(
                    "Pico rejected {} (HTTP {})".format(action, error.code)
                ) from error
        except (OSError, ValueError, urllib.error.URLError) as error:
            raise TelemetryError("unable to {}".format(action)) from error
        self.login()
        try:
            return self._request(path, data)
        except urllib.error.HTTPError as error:
            raise TelemetryError(
                "Pico rejected {} after login (HTTP {})".format(action, error.code)
            ) from error
        except (OSError, ValueError, urllib.error.URLError) as error:
            raise TelemetryError("unable to {} after Pico login".format(action)) from error

    def login(self):
        try:
            result = self._request("/api/login", {
                "username": self.username,
                "password": self.password,
            })
        except (OSError, ValueError, urllib.error.URLError) as error:
            raise TelemetryError("Pico login failed") from error
        if result.get("authenticated") is not True:
            raise TelemetryError("Pico login was not accepted")

    def send(self, snapshot):
        return self._authenticated(
            "/api/telemetry", snapshot, "send telemetry to the Pico"
        )

    def curve(self):
        return self._authenticated("/api/curve", action="read the fan curve")

    def set_automatic(self, active):
        if type(active) is not bool:
            raise TelemetryError("automatic-control state must be true or false")
        return self._authenticated(
            "/api/automatic", {"active": active}, "set automatic control"
        )

    def command(self, duty):
        if type(duty) not in (int, float) or (duty != 0 and not 20 <= duty <= 100):
            raise TelemetryError("calculated fan duty is invalid")
        return self._authenticated("/api/fan", {"duty": duty}, "command the fan")

    def release(self):
        return self._authenticated(
            "/api/release", {}, "release the automatic fan command"
        )


def configuration():
    command = os.environ.get("DGX_FAN_GPU_COMMAND")
    interval_text = os.environ.get("DGX_FAN_INTERVAL_SECONDS", "5")
    try:
        interval = float(interval_text)
    except ValueError as error:
        raise TelemetryError("DGX_FAN_INTERVAL_SECONDS must be numeric") from error
    if not 2 <= interval <= 10:
        raise TelemetryError("DGX_FAN_INTERVAL_SECONDS must be between 2 and 10")
    automatic_text = os.environ.get("DGX_FAN_AUTOMATIC_DEFAULT", "1")
    if automatic_text not in ("0", "1"):
        raise TelemetryError("DGX_FAN_AUTOMATIC_DEFAULT must be 0 or 1")
    gpu_command = DEFAULT_GPU_COMMAND if not command else tuple(shlex.split(command))
    if not gpu_command:
        raise TelemetryError("DGX_FAN_GPU_COMMAND must not be empty")
    return {
        "base_url": os.environ.get("DGX_FAN_PICO_URL", "http://dgx-fan.local"),
        "username": os.environ.get("DGX_FAN_USERNAME"),
        "password": os.environ.get("DGX_FAN_PASSWORD"),
        "interval": interval,
        "cpu_zone": os.environ.get("DGX_FAN_CPU_ZONE"),
        "gpu_command": gpu_command,
        "automatic_default": automatic_text == "1",
    }


def collect_and_send(client, cpu_zone=None, gpu_command=DEFAULT_GPU_COMMAND):
    snapshot, sources, errors = read_temperatures(cpu_zone, gpu_command)
    for sensor, error in errors.items():
        LOG.warning("%s temperature unavailable: %s", sensor.upper(), error)
    client.send(snapshot)
    LOG.info(
        "sent GPU=%s C CPU=%s C",
        snapshot["gpu_temperature_c"], snapshot["cpu_temperature_c"],
    )
    return snapshot, sources


def probe(cpu_zone=None, gpu_command=DEFAULT_GPU_COMMAND):
    snapshot, sources, errors = read_temperatures(cpu_zone, gpu_command)
    print(json.dumps({"temperatures": snapshot, "sources": sources, "errors": errors}, indent=2))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="send one snapshot and exit")
    parser.add_argument("--probe", action="store_true", help="show detected sensors without contacting the Pico")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        config = configuration()
        if args.probe:
            probe(config["cpu_zone"], config["gpu_command"])
            return 0
        client = PicoClient(
            config["base_url"], config["username"], config["password"],
        )
        startup_state_applied = False
        last_duty = None
        was_running = False
        while True:
            try:
                if not startup_state_applied:
                    client.set_automatic(config["automatic_default"])
                    startup_state_applied = True
                    LOG.info(
                        "automatic temperature control %s at service start",
                        "enabled" if config["automatic_default"] else "disabled",
                    )
                snapshot, _ = collect_and_send(
                    client, config["cpu_zone"], config["gpu_command"]
                )
                duty = automatic_duty(snapshot, client.curve(), was_running)
                if duty is None:
                    if last_duty is not None:
                        # Close the small race where a command calculated just
                        # before a dashboard pause could arrive after the Pico's
                        # full-speed transition.
                        client.release()
                        LOG.info("automatic temperature control paused")
                    last_duty = None
                    was_running = False
                else:
                    client.command(duty)
                    if duty != last_duty:
                        LOG.info("curve selected %s%% PWM", duty)
                    last_duty = duty
                    was_running = duty != 0
            except TelemetryError as error:
                LOG.error("%s", error)
                if args.once:
                    return 1
            if args.once:
                return 0
            time.sleep(config["interval"])
    except TelemetryError as error:
        LOG.error("%s", error)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
