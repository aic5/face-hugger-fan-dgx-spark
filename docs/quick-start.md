# Quick start

This guide takes the reference build from an empty Pico W to automatic control.
Read the [illustrated wiring guide](wiring.html) before assembling hardware.

## 1. Wire and bench-test the electronics

With all power disconnected:

| Connection | Destination |
| --- | --- |
| Fan black / pin 1 | Boost `OUT-` and Pico GND, physical pin 18 |
| Fan yellow / pin 2 | Boost `OUT+`, regulated **12 V only** |
| Fan green / pin 3 | Pico GP13, physical pin 17 |
| Fan blue / pin 4 | Pico GP15, physical pin 20 |
| 1 kΩ resistor | Pico 3V3(OUT), pin 36, to the GP13/green tach node |
| 1 µF non-polarized capacitor | GP13/green tach node to ground |

Power the Pico through its micro-USB socket for the simplest first build. Feed
the boost converter from a separately rated 5 V branch, join the grounds, and
test the converter at 12 V before connecting the fan. Never put 12 V on the Pico,
the blue PWM lead, or the green tach lead.

## 2. Install CircuitPython on the Pico W

1. Download the current stable UF2 from the
   [CircuitPython Pico W page](https://circuitpython.org/board/raspberry_pi_pico_w/).
   This repository was developed against CircuitPython 10.3.0.
2. Hold the Pico's `BOOTSEL` button while connecting USB.
3. Copy the UF2 to the `RPI-RP2` drive. The board restarts as `CIRCUITPY`.

## 3. Configure the Pico

Copy `settings.toml.example` to `settings.toml` and set:

```toml
WIFI_ENABLED = "1"
WIFI_SSID = "YOUR_2_4_GHZ_NETWORK"
WIFI_PASSWORD = "YOUR_WIFI_PASSWORD"
FAN_WEB_USERNAME = "YOUR_DASHBOARD_USERNAME"
FAN_WEB_PASSWORD = "A_LONG_UNIQUE_PASSWORD"
DEVICE_NAME = "dgx-fan"
FAN_COMMAND_TIMEOUT = 30
```

Do not commit `settings.toml`; it is ignored by Git.

Copy these items to the root of `CIRCUITPY`:

```text
code.py
fan_control.py
fan_curve.py
fan_curve.json
fan_history.py
wifi_control.py
settings.toml
lib/
www/
```

Replace old copies as a set. CircuitPython reloads automatically. The serial
console prints the board's IP address and, when mDNS works on the network, the
default name `http://dgx-fan.local`.

## 4. First fan test

1. Keep the fan power off and let the Pico finish booting.
2. Apply the regulated 12 V fan supply.
3. Open the Pico address from a browser on the same trusted LAN and sign in.
4. Pause automatic control, request full speed, request a middle duty, then
   request off. Watch for blade clearance, stable 12 V output, Pico resets, heat,
   or abnormal noise.
5. Release manual control. Until the DGX service is running, the fail-safe may
   restore full speed after the command timeout; this is expected.

## 5. Install the DGX Spark service

From the cloned repository on the DGX, first verify sensor discovery:

```sh
python3 dgx/dgx_fan_telemetry.py --probe
```

Then install the service:

```sh
sudo install -d -m 755 /opt/dgx-fan
sudo install -m 755 dgx/dgx_fan_telemetry.py fan_curve.py /opt/dgx-fan/
sudo install -m 600 dgx/dgx-fan-telemetry.env.example /etc/dgx-fan-telemetry.env
sudo install -m 644 dgx/dgx-fan-telemetry.service /etc/systemd/system/
sudoedit /etc/dgx-fan-telemetry.env
sudo systemctl daemon-reload
sudo systemctl enable --now dgx-fan-telemetry.service
```

Set the Pico URL and the same dashboard username/password in
`/etc/dgx-fan-telemetry.env`. Check operation with:

```sh
systemctl status dgx-fan-telemetry.service
journalctl -u dgx-fan-telemetry.service -n 30 --no-pager
```

The service sends a fresh command every five seconds by default. The Pico holds
full speed if no valid command has arrived or if the command age reaches the
30-second default timeout.

## 6. Tune carefully

The included curve is an illustrative starting point, not an NVIDIA thermal
recommendation:

| Selected CPU/GPU temperature | Requested fan output |
| --- | ---: |
| At or below 45 °C | Off |
| At or above 50 °C | 30% |
| At or above 60 °C | 60% |
| At or above 75 °C | 100% |

Use the dashboard to test a curve, then download its JSON and replace
`CIRCUITPY/fan_curve.json` if you want it to survive a reboot. Confirm the fan's
minimum reliable duty and collect your own before/after data under matched
workloads.

## Troubleshooting

| Symptom | First checks |
| --- | --- |
| Fan does not run | Measured 12 V and polarity at the fan, requested duty, blade clearance |
| Fan runs but RPM is zero | Green lead on GP13, shared ground, 1 kΩ pull-up, 1 µF capacitor |
| Pico resets as fan starts | 5 V source, cable loss, converter continuous/startup rating, loose connections |
| Dashboard unavailable | 2.4 GHz network, serial-console IP, credentials, complete `www/` and `lib/` copies |
| Service holds full speed | Pico reachability, `/etc/dgx-fan-telemetry.env`, discovered CPU/GPU sensors, service logs |

For API details and failure behavior, continue to the
[software reference](software-reference.md).
