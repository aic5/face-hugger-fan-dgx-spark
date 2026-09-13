"""Desktop-only dashboard fixture. Never deploy this file to the Pico."""

import math
from pathlib import Path
import socket
import sys
import time
import types

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fan_control import FanControl
from wifi_control import make_server

now = [0]
fan = FanControl(types.SimpleNamespace(duty_cycle=0), remote=True, clock=lambda: now[0])
for minute in range(1440):
    now[0] = minute * 60_000_000_000
    fan.history.update({"gpu_temperature_c": 50 + 12 * math.sin(minute / 95),
                        "cpu_temperature_c": 44 + 8 * math.sin(minute / 100 + 1)})
    fan.history.record(1000 + 200 * math.sin(minute / 80), 60 + 10 * math.sin(minute / 80))
fan.rpm = 1120
base = now[0]
started = time.monotonic_ns()
server = make_server(
    socket, fan, "dashboard-user", "dashboard-password",
    web_root=str(Path(__file__).resolve().parents[1] / "www"),
)
server.start("127.0.0.1", port=0)
print("http://127.0.0.1:" + str(server._sock.getsockname()[1]), flush=True)
try:
    while True:
        now[0] = base + time.monotonic_ns() - started
        fan.tick()
        server.poll()
        time.sleep(0.005)
finally:
    server.stop()
