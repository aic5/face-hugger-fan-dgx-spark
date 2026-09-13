# Software reference

CircuitPython firmware for a Raspberry Pi Pico W controlling a 12 V Noctua NF-A14
PWM fan. The board can join a 2.4 GHz Wi-Fi network and accept local HTTP commands
to turn the fan off or set its PWM duty. The DGX Linux service collects CPU/GPU
temperatures, applies the configured temperature curve, and sends renewed PWM
commands to the Pico. USB currently supplies power and a serial console; there is not yet a
USB serial command protocol.

This project targets CircuitPython 10.3.0 for Raspberry Pi Pico W. Wi-Fi control
uses Adafruit HTTPServer (desktop integration verified with 4.8.2). A settings-backed
login creates an in-memory browser session; no control token is used.
The hardware is experimental; validate each assembly before unattended use.

## Project files

| File | Role |
| --- | --- |
| `code.py` | Board entry point, hardware setup, main loop |
| `fan_control.py` | Duty, startup boost, RPM and command timeout |
| `fan_history.py` | Bounded minute history and DGX telemetry freshness |
| `fan_curve.py` | Shared validated stepped policy and automatic-control state |
| `fan_curve.json` | Non-secret, editable temperature and PWM thresholds |
| `wifi_control.py` | Wi-Fi reconnect, optional mDNS and HTTP API |
| `www/` | Self-contained browser dashboard, styles and charts |
| `dgx/dgx_fan_telemetry.py` | DGX temperature probe and Pico telemetry sender |
| `dgx/dgx-fan-telemetry.service` | Hardened systemd service definition |
| `dgx/dgx-fan-telemetry.env.example` | DGX-side service configuration template |
| `settings.toml.example` | Configuration template, with no credentials |
| `settings.toml` | Local configuration, ignored by Git |
| `lib/adafruit_httpserver/` | Included CircuitPython 10.x HTTPServer 4.8.2 library |
| `tests/` | Simulated hardware and real localhost HTTP checks |

## Wiring

See the [illustrated wiring reference](docs/wiring.html) for connection diagrams,
Pico physical pin locations, shared USB power precautions and a first-power-up
checklist. It also documents the proposed USB-C breakout variant: verified 5 V
from `V` through an added Schottky diode to VSYS (pin 39), common GND (pin 38),
and optional USB `D+`/`D-` to TP3/TP2. The supplied product image identifies an
ANMBEST JRC-B008 breakout (`G`, `D+`, `D-`, `V`); its independent CC pull-downs
and 5 V operation still need verification before connection to the Pico. Open
the HTML file directly in a browser; no server is required.

Disconnect power before wiring. The fan uses a keyed 4-pin PC fan plug.
Use a mating 4-pin PC PWM fan header/breakout or extension with accessible wires.
Verify pin numbering against Noctua's connector diagram. Do not assume left-to-right
order: viewing the plug from the wire side reverses it. The plug is not USB.

| Fan pin | Typical colour | Connection |
| --- | --- | --- |
| 1, ground | Black | 12 V supply negative AND Pico GND, physical pin 18 |
| 2, motor supply | Yellow | Regulated +12 V supply only |
| 3, tachometer | Green | GP13, physical pin 17, with the pull-up/filter below |
| 4, PWM control | Blue | GP15, physical pin 20 |

For the simple USB-cable setup, power the Pico through its micro-USB socket.
For the VSYS/USB-C breakout variant, follow the illustrated guide instead; never
connect two USB hosts to the socket and test pads simultaneously. The motor requires a separate
regulated 12 V source, such as an adapter rated for at least 0.5 A or a suitable
USB 5 V-to-12 V boost converter. Never connect 12 V to the Pico or to fan pin 4.
Fan ground, supply negative and Pico ground must be joined. Do not pulse the fan's
motor supply: speed control uses only the blue wire.

A shared USB-C source can supply the Pico's 5 V/data branch and a separate
5 V-to-12 V boost branch for the fan. Verify the converter, cable/hub and USB
source current ratings, including startup margin. The NF-A14 PWM is rated up to
1.56 W (0.13 A at 12 V); at an illustrative 85% boost efficiency, that is about
0.37 A drawn from 5 V for the fan alone, plus the Pico's consumption. The boost
output must never connect to the Pico's USB/VSYS/3V3/GPIO pins or backfeed USB VBUS.
A USB-C PD trigger selecting a voltage above 5 V is not equivalent to this split
5 V arrangement. Keep USB data connected to the Pico, and verify the actual wiring
and negotiated/advertised USB current before relying on one source for both loads.

Noctua supports a direct 3.3 V GPIO PWM signal. This program assumes that direct
connection, without an inverting transistor. No external PWM pull-up is needed.
For this wiring, power the Pico before the fan and turn the fan supply off before
unplugging the Pico. The software cannot guarantee full speed during power loss,
firmware flashing, resets or a processor freeze.

RPM monitoring is always enabled: connect green to GP13.
This changes the earlier MicroPython wiring: move green from GP14 (physical pin 19)
to GP13 (physical pin 17), and move its pull-up/filter components with it.
CircuitPython's RP2040 pulse counter needs a PWM channel B pin (an odd GPIO).
GP13 uses a different PWM slice from GP15, allowing counting and speed control
to operate together. Leave both GP12 and GP13 free of other PWM uses when counting.

The fan tachometer is an open-collector output and does not produce a HIGH voltage
by itself. Fit a **1 kΩ resistor from GP13 to 3V3(OUT), physical pin 36**, and a
**1 µF non-polarized capacitor from GP13 to ground**. These values follow Noctua's
current microcontroller guidance and provide a stronger, cleaner signal than the
Pico's internal pull-up alone. Never pull GP13 up to 5 V or 12 V. The fan emits
two pulses per revolution. Zero pulses do not distinguish a stopped fan, missing
fan power, a disconnected tach wire, or an incomplete pull-up/ground circuit.

## Install on the Pico

1. Install the [CircuitPython Pico W firmware](https://circuitpython.org/board/raspberry_pi_pico_w/).
   Preserve existing board files first when changing firmware. Hold BOOTSEL while
   connecting USB, then transfer the UF2 to RPI-RP2. The board reappears as CIRCUITPY.
2. Transfer this project's included `lib/` folder to `CIRCUITPY/lib/`.
   It contains the official CircuitPython 10.x build of HTTPServer 4.8.2;
   no separate library download is needed.
   Standalone mode does not require this library.
3. Set your network details in the local `settings.toml`. A blank file is provided
   in this workspace; when cloning the repository, start from `settings.toml.example`.
   Enter `WIFI_SSID`, `WIFI_PASSWORD`, `FAN_WEB_USERNAME`, and
   `FAN_WEB_PASSWORD`. Keep `WIFI_ENABLED = "1"`.
4. Transfer `code.py`, `fan_control.py`, `fan_history.py`, `fan_curve.py`,
   `fan_curve.json`, `wifi_control.py` and
   `settings.toml` to the root of CIRCUITPY, and replace `CIRCUITPY/www/` with
   this project's complete `www/` folder. If the old control-token field still
   appears, the board is serving an earlier web bundle; restart the Pico and
   hard-refresh the browser after transferring all of these files together.
   Preserve your existing board settings when updating code. Do not transfer Git metadata or the tests. Remove the
   old MicroPython `main.py` if it is still present, after preserving needed changes.
5. CircuitPython reloads after file changes. In Thonny's CircuitPython serial
   console, the board prints its IP address and, when available, its mDNS name.
   By default the API is at `http://dgx-fan.local`; use the printed IP if name
   resolution is unavailable on the board, network or DGX.
6. With wiring checked and Pico power present, apply the fan's 12 V supply.
   Wi-Fi mode holds full speed until the DGX service sends its first curve command.

Open the board's IP address in a browser for the dashboard, or use the HTTP API
below. There is no remote firmware upload endpoint. An ordinary USB data cable can still provide power and
access to CIRCUITPY and the console; Wi-Fi does not supply electrical power.

The login and API use plain HTTP, so credentials and session cookies are not
encrypted in transit. Use the controller only on an isolated, trusted LAN; do not
expose it to guest Wi-Fi or the internet. Writes require
`Content-Type: application/json`, and cross-origin browser access is not enabled. Neither
credentials nor firmware files are served.

## Dashboard and history

Opening `/` redirects to the login page until the configured username and password
are accepted. The Pico then sets an HttpOnly, SameSite session cookie, so the
dashboard does not ask again while that browser session and controller boot remain
active. Logging out, closing the browser session, or restarting the Pico requires
a new login. The dashboard shows estimated fan RPM, applied PWM, controller state,
and DGX GPU/CPU temperatures. No control token or CORS access is used.

The dashboard estimates the NF-A14 speed linearly from its applied PWM using the
fan's rated 1,500 RPM maximum: 0% displays 0 RPM, 60% displays 900 RPM, and 100%
displays 1,500 RPM. The 24-hour RPM chart applies the same calculation to retained
PWM samples. This is a display estimate, not proof that the fan is rotating. The
API and USB diagnostics retain the separate physical tachometer reading for later
troubleshooting.

The three history charts share one row on desktop and stack on narrow screens.
Each expand icon opens a larger modal chart with temperature/RPM/PWM tabs. The
expanded chart uses the same live, minute-sampled history without extra API calls.
Its time-range controls show all retained data or fixed windows of 24 hours,
12 hours, 3 hours, 1 hour, 30 minutes or 15 minutes. The selection remains active
when switching chart tabs. Export CSV downloads the selected chart's timestamped
samples within the chosen range, with separate GPU/CPU columns for temperature.
Close it with the close button, Escape, or a click outside; keyboard focus returns
to the original expand button. Arrow keys switch the chart tabs.

Automatic temperature control starts enabled after a Pico or DGX service restart.
The Temperature / speed curve section has a button to pause or reactivate it.
While it is active, manual fan controls are disabled to avoid competing commands.
Pausing automatic control immediately selects the full-speed fallback; a manual
command can then be applied.

Apply speed, Full speed, and Off start a browser-held command. While visible and
connected, the page refreshes that command at most every five seconds (sooner for
short configured timeouts). Release hold requests full speed. Closing/hiding the
page or losing connectivity stops renewal; the existing command timeout then
requests full speed. A restart or observed conflicting command cancels the page's
hold. Status reads never renew commands.

The Pico stores one instantaneous sample per minute for at most 1,440 minutes,
including when no browser is open. Four packed arrays use 11,520 bytes for RPM,
GPU temperature, CPU temperature and PWM. History is RAM-only: reboot/reload
clears it and no flash writes occur. Charts always span 24 hours, leaving missing
data as gaps. Temperatures retain 0.1 C precision; PWM retains 0.01% precision.
Chart times are mapped from Pico monotonic time to the viewing browser's clock.
History is downloaded in pages of at most 120 samples to bound response memory.
Each row is `[minute, rpm, gpu_temperature_c, cpu_temperature_c, applied_duty]`.
Use `next_before` as the next request's `before` parameter until it is null.

DGX temperatures require the included sender; the Pico does not measure them.
The service sends a complete sensor snapshot and refreshes the curve command every
five seconds by default.
Omitted/null sensors are unavailable, and readings expire after 120 seconds.
The telemetry API alone does not renew the fan command timeout:

```sh
curl --fail-with-body http://dgx-fan.local/api/telemetry \
  -b fan-cookie.txt \
  -H "Content-Type: application/json" \
  -d '{"gpu_temperature_c":55.5,"cpu_temperature_c":48.2}'
```

The above values illustrate the schema, not measured DGX temperatures. The DGX
service reads the current curve after each snapshot and sends the selected duty.

## Temperature steps

The dashboard's Temperature / speed curve editor defines explicit Celsius
thresholds and stepped PWM output, not a continuous ramp or exact RPM targets.
Actual RPM remains a separate tachometer reading. The built-in draft and
`fan_curve.json` start with these **illustrative values, not recommended DGX
thermal limits**:

| Temperature | Requested output |
| --- | --- |
| At or below 45 C | Off (0%) |
| At or above 50 C | 30% PWM |
| At or above 60 C | 60% PWM |
| At or above 75 C | Full speed (100%) |

Between 45 and 50 C, a stopped fan stays off; an already running fan stays at
the first running step. This is the stop/restart hysteresis band. Between other
thresholds, the previous step is held: 59.9 C selects 30%, exactly 60 C selects
60%, and 74.9 C remains 60%. No interpolation is performed. On cooling below an
intermediate threshold, output returns to the preceding step.

You can select CPU, GPU, or the higher of both, set the stop temperature, edit
2-8 running steps, and add/remove intermediate steps. Temperatures must increase;
running PWM must not decrease, starts at 20% or higher, and only the final step
is 100%. The final temperature is the full-speed threshold. Confirm the lowest
usable PWM with your actual fan and power supply; PWM percentage is not a fixed
fraction of rated RPM. Startup boost and command-timeout protection remain unchanged.

`GET /api/curve` returns the current non-secret configuration and automatic-control
state. `POST /api/curve` replaces the curve for this running session only. Applying
a curve does not itself command the fan; the DGX service observes it on its next
five-second cycle. `POST /api/automatic` pauses or activates automatic control.
Transitions use full speed until a new valid curve or manual command arrives.
The DGX service retains running/off state for hysteresis and commands full speed
when a selected temperature is unavailable.

On boot the Pico loads `fan_curve.json`. Missing/invalid files use draft defaults
and log a warning. Automatic control defaults to enabled; the fan remains at the
full-speed fallback until the DGX service supplies a valid renewed command.
Curve downloads contain only the curve, never `settings.toml` credentials.
To retain web edits across restarts, use Download curve file and replace
`CIRCUITPY/fan_curve.json` with that file (also keep the development copy updated).
The web UI deliberately does not write the host-owned USB filesystem or silently
change USB storage permissions. Apply for session therefore does not persist.

If the page reports `Curve API missing (404)`, it is reaching a server without
the new curve route. Updating files on CIRCUITPY can update the served HTML/JS
before the running Python server reloads, especially while using Thonny. Confirm
the firmware modules have been copied, restart the Pico, then use Retry or refresh
the page. A missing/invalid `fan_curve.json` alone does not cause a 404: the current
firmware returns its draft defaults. Other malformed responses and connection
failures are reported separately and do not block the live fan status display.

## Settings

| Setting | Default / meaning |
| --- | --- |
| `WIFI_ENABLED` | `"1"` in template; absent settings defaults to standalone |
| `WIFI_SSID`, `WIFI_PASSWORD` | Your 2.4 GHz network; required in Wi-Fi mode |
| `FAN_WEB_USERNAME`, `FAN_WEB_PASSWORD` | Dashboard/API login; both required in Wi-Fi mode |
| `DEVICE_NAME` | `"dgx-fan"`; lowercase hostname, no `.local` suffix |
| `FAN_HTTP_PORT` | `80` |
| `WIFI_IPV4_ADDRESS`, `WIFI_IPV4_NETMASK`, `WIFI_IPV4_GATEWAY`, `WIFI_IPV4_DNS` | Optional static network configuration; omit all four to use DHCP |
| `FAN_COMMAND_TIMEOUT` | `30` seconds; allowed 5-300 |
| `FAN_DUTY_PERCENT` | `60`; standalone setting only |

For a local test without networking, set `WIFI_ENABLED = "0"`. The fan starts
at full speed for two seconds and then runs at `FAN_DUTY_PERCENT`.
That value, and all API duty values, must be `0` (off) or `20` through `100`.
PWM percentage is a command, not an exact percentage of maximum RPM.

## Control from the DGX

### Temperature tracking service

The telemetry service uses `nvidia-smi` for GPU temperature and selects the
hottest Linux thermal zone whose name identifies a CPU, SoC or package sensor.
It accepts a zone override for platforms with unusual sensor names. Run its
read-only probe on the DGX before installation:

```sh
python3 dgx/dgx_fan_telemetry.py --probe
```

Install the script, environment template and service:

```sh
sudo install -d -m 755 /opt/dgx-fan
sudo install -m 755 dgx/dgx_fan_telemetry.py fan_curve.py /opt/dgx-fan/
sudo install -m 600 dgx/dgx-fan-telemetry.env.example /etc/dgx-fan-telemetry.env
sudo install -m 644 dgx/dgx-fan-telemetry.service /etc/systemd/system/
sudoedit /etc/dgx-fan-telemetry.env
sudo systemctl daemon-reload
sudo systemctl enable --now dgx-fan-telemetry.service
```

Set the Pico URL and dashboard username/password in the environment file. The
service never logs credentials. It automatically logs in again when its session
is missing or the Pico has restarted. Confirm delivery with:

```sh
systemctl status dgx-fan-telemetry.service
journalctl -u dgx-fan-telemetry.service -n 30 --no-pager
```

`DGX_FAN_AUTOMATIC_DEFAULT=1` makes each service start activate the curve. The
dashboard can pause it for the current run; restarting the service or DGX restores
the configured default. The service polls every five seconds so its commands remain
well inside the Pico's 30-second timeout. The Pico's timeout and full-speed fallback
remain authoritative if the service or network fails.

### Manual API control

The control and telemetry APIs use the same login session as the dashboard.
Command-line clients can log in once and reuse the returned cookie. Replace the
hostname with the printed IP when needed.

Log in and store the session cookie:

```sh
curl --fail-with-body http://dgx-fan.local/api/login \
  -c fan-cookie.txt \
  -H "Content-Type: application/json" \
  -d '{"username":"YOUR_USERNAME","password":"YOUR_PASSWORD"}'
```

Read status:

```sh
curl --fail-with-body http://dgx-fan.local/api/status -b fan-cookie.txt
```

Set 60% PWM:

```sh
curl --fail-with-body http://dgx-fan.local/api/fan \
  -b fan-cookie.txt \
  -H "Content-Type: application/json" \
  -d '{"duty":60}'
```

Use `{"duty":0}` to turn off, or `{"duty":100}` for maximum airflow.
A command response includes the requested duty, applied duty, state and measured
tachometer RPM. RPM is `null` when the counter is unavailable or no sample has been collected.
An RPM of zero with a nonzero command could mean a stopped fan, missing power
or disconnected tach wire; it does not uniquely identify the cause.

**Commands expire after 30 seconds by default, including off commands.**
The automatic controller resends its selected duty every 5 seconds, even
when temperature and speed have not changed. Status reads and invalid commands
do not renew this timeout.

When restarting from off, the Pico applies full speed for two seconds before
settling at the requested duty. Resending the same command during startup does
not keep extending the boost. An off command takes effect immediately.

## Connection and error behavior

- Wi-Fi disconnect or an expired command requests full speed.
- Static assets are cached by the browser for one hour. Versioned asset URLs make
  firmware updates take effect without serving CSS and JavaScript on every visit.
- The dashboard loads its stylesheet, program and live requests in sequence to
  avoid the Pico W networking slowdown caused by parallel browser connections.
- A browser that abandons a static-file download is disconnected after three
  seconds instead of being allowed to freeze the Pico's single HTTP loop.
- The board retries Wi-Fi connections and rebinds the HTTP listener after reconnection.
  Each connection attempt has a 5-second timeout and failed attempts wait 10 seconds.
- Reconnection does not restore an old off/slow command. The DGX must issue a new one.
- No fan or wires are needed to boot. An unwired tach input reports zero after
  its first sample. PWM output alone cannot detect whether a fan is spinning.
- The console prints the initial PWM/RPM/state status, then only when one of those
  values changes. Unchanged status is not repeated; startup and error messages remain.
- Tach debugging additionally prints `TACH GP13 (pin 17)` about every five seconds,
  including when there are zero pulses. It reports the raw cumulative falling-edge
  count, pulses during the actual elapsed window, window RPM (two pulses/revolution)
  and applied PWM. It observes the existing counter without resetting it or taking
  over GP13. This is a pulse count, not an instantaneous HIGH/LOW or voltage reading.
  For example: `total=250 | pulses=250 / 5.00s | window_RPM=1500 | PWM=60%`.
  If counter initialization failed, the diagnostic says unavailable.
- Invalid settings or unavailable Wi-Fi libraries finish boot with a 100% PWM
  fallback. The console identifies invalid settings
  without printing credentials. Fix the reported setting/library and reload.
  Set `WIFI_ENABLED = "0"` to test standalone operation without network configuration.
- RPM counter initialization failure disables RPM sensing, not the controller.
  An unwired tach input with its pull-up enabled will read zero after sampling;
  unavailable sensing reports `None` in the console (`null` in the API).
- Unexpected application exceptions still hold full PWM until reload.
- No settings file selects standalone mode; an installed file that enables Wi-Fi
  but lacks credentials does not silently fall back to a slower standalone speed.
- A powered, running controller is required for these software fallbacks. They do
  not cover failed imports before hardware setup, PWM initialization failure,
  firmware flashing, resets, power loss or a frozen processor.
- Ctrl+C stops the program and releases PWM. CircuitPython resets outputs on
  program exit/reload. Check actual fan behavior in those states on the assembled unit.

These rules control only the external fan. They do not replace the DGX's internal
thermal management. Temperature bands and hysteresis belong in the later Linux service.

## Verification

Core state tests need only desktop Python:

```sh
python3 -m unittest discover -s tests -v
```

HTTP tests skip when their desktop dependency is absent. To run all checks,
including real HTTP requests against a localhost listener:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-test.txt
.venv/bin/python -m unittest discover -s tests -v
```

The tests cover startup, off/on, RPM, counter wrap, stale commands, login sessions,
bad requests, Wi-Fi reconnect, socket failures, history rollover, telemetry expiry,
DGX sensor selection, DGX reauthentication, and public dashboard isolation from
credentials. They do not test RF reception, electrical signals, memory usage on
the board, or the physical fan.

For optional browser checks, install Playwright in your desktop Node environment
and Chrome, then run `FAN_TEST_PYTHON=.venv/bin/python node tests/test_dashboard.cjs`.
This starts a temporary localhost fixture, verifies controls and desktop/mobile
charts, modal keyboard/focus behavior, and curve-error recovery, writes screenshots
under `/private/tmp/dgx-fan-dashboard`, and stops it.
The synthetic 24-hour readings exist only in `tests/serve_dashboard.py`, never
in the firmware or production dashboard.

## References

- [Noctua microcontroller guide](https://www.noctua.at/en/support/faqs/microcontroller-guide-pwm-setup-and-rpm-monitoring)
- [Noctua connector and PWM specification](https://cdn.noctua.at/media/Noctua_PWM_specifications_white_paper.pdf)
- [NF-A14 PWM electrical specifications](https://www.noctua.at/en/products/nf-a14-pwm/specifications)
- [Pico W physical pinout](https://datasheets.raspberrypi.com/picow/PicoW-A4-Pinout.pdf)
- [CircuitPython for Pico W](https://circuitpython.org/board/raspberry_pi_pico_w/)
- [CircuitPython PWM output](https://docs.circuitpython.org/en/latest/shared-bindings/pwmio/)
- [CircuitPython pulse counter restrictions](https://docs.circuitpython.org/en/latest/shared-bindings/countio/)
- [CircuitPython Wi-Fi API](https://docs.circuitpython.org/en/latest/shared-bindings/wifi/)
- [Adafruit HTTPServer examples](https://docs.circuitpython.org/projects/httpserver/en/latest/examples.html)
- Chart expand/close icons: Lucide 0.468.0, bundled locally with `www/LUCIDE-LICENSE`.
