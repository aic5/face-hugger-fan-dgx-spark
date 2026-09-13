"""CircuitPython entry point for the DGX Spark external fan controller."""

import os
import time

import board
import pwmio

from fan_control import FanControl

PWM_PIN = board.GP15  # Physical pin 20 -> fan pin 4 (blue).
TACH_PIN = board.GP13  # Physical pin 17 -> fan pin 3 (green), optional.


class TachDebug:
    """Observe the existing counter without resetting or reclaiming its pin."""

    def __init__(self, tach):
        self.tach = tach
        self.last_time = time.monotonic_ns()
        self.last_count = None
        if tach is not None:
            try:
                self.last_count = tach.count
            except Exception:
                pass

    def report(self, pwm):
        now = time.monotonic_ns()
        elapsed = now - self.last_time
        if elapsed < 5_000_000_000:
            return
        self.last_time = now
        if self.tach is None:
            print("TACH GP13 (pin 17): unavailable; check boot warnings")
            return
        try:
            count = self.tach.count
        except Exception as error:
            self.last_count = None
            print("TACH GP13 (pin 17): counter read failed ({})".format(type(error).__name__))
            return
        pulses = None if self.last_count is None else (count - self.last_count) & 0xFFFFFFFF
        rpm = None if pulses is None else round(pulses * 60_000_000_000 / (2 * elapsed))
        self.last_count = count
        print("TACH GP13 (pin 17): total={} | pulses={} / {:.2f}s | window_RPM={} | PWM={}%".format(
            count, pulses, elapsed / 1_000_000_000, rpm, pwm,
        ))


class ConfigurationError(ValueError):
    """A settings error that is safe to print without exposing its value."""


def setting(name, default=None):
    try:
        return os.getenv(name, default)
    except (ValueError, TypeError, OSError):
        raise ConfigurationError("Cannot read " + name + "; check settings.toml syntax")


def flag(name, default="0"):
    value = setting(name, default)
    if str(value) not in ("0", "1"):
        raise ConfigurationError(name + " must be 0 or 1")
    return str(value) == "1"


def integer(name, default, minimum, maximum, allow_zero=False):
    value = setting(name, default)
    try:
        if type(value) not in (str, int):
            raise ValueError()
        value = int(value)
        if not minimum <= value <= maximum and not (allow_zero and value == 0):
            raise ValueError()
    except (ValueError, TypeError):
        message = name + " must be an integer from {} to {}".format(minimum, maximum)
        raise ConfigurationError(message + (", or 0" if allow_zero else ""))
    return value


def run():
    pwm = pwmio.PWMOut(PWM_PIN, frequency=25_000, duty_cycle=65535)
    tach = None
    network = None
    try:
        try:
            import countio
            import digitalio
            tach = countio.Counter(
                TACH_PIN, edge=countio.Edge.FALL, pull=digitalio.Pull.UP
            )
        except Exception as error:
            print("RPM unavailable: GP13 counter initialization failed ({})".format(
                type(error).__name__
            ))

        configuration_ok = False
        try:
            remote = flag("WIFI_ENABLED")
            default_duty = 100 if remote else integer("FAN_DUTY_PERCENT", 60, 20, 100, True)
            timeout = integer("FAN_COMMAND_TIMEOUT", 30, 5, 300) if remote else 30
            controller = FanControl(
                pwm, tach, remote=remote, default_duty=default_duty, timeout=timeout,
            )
            configuration_ok = True
        except ConfigurationError as error:
            print("Configuration warning:", str(error))
            controller = FanControl(pwm, tach, remote=True)
            controller.failsafe("configuration_error")

        try:
            controller.curve.load()
        except (OSError, ValueError, TypeError):
            print("Curve settings unavailable/invalid; using draft defaults with automatic control enabled.")

        if configuration_ok and remote:
            try:
                from wifi_control import WiFiControl, WiFiConfigurationError
            except ImportError:
                controller.failsafe("wifi_unavailable")
                print("Wi-Fi disabled: check wifi_control.py and lib/adafruit_httpserver")
            else:
                try:
                    network = WiFiControl(
                        controller,
                        ssid=setting("WIFI_SSID"),
                        password=setting("WIFI_PASSWORD"),
                        web_username=setting("FAN_WEB_USERNAME"),
                        web_password=setting("FAN_WEB_PASSWORD"),
                        hostname=setting("DEVICE_NAME", "dgx-fan"),
                        port=integer("FAN_HTTP_PORT", 80, 1, 65535),
                        ipv4_address=setting("WIFI_IPV4_ADDRESS"),
                        ipv4_netmask=setting("WIFI_IPV4_NETMASK"),
                        ipv4_gateway=setting("WIFI_IPV4_GATEWAY"),
                        ipv4_dns=setting("WIFI_IPV4_DNS"),
                    )
                    print("Wi-Fi control enabled; full speed until a valid command arrives")
                except (ConfigurationError, WiFiConfigurationError) as error:
                    controller.failsafe("configuration_error")
                    print("Wi-Fi disabled:", str(error))
                except Exception as error:
                    controller.failsafe("wifi_unavailable")
                    print("Wi-Fi initialization failed ({}); check Wi-Fi and lib/adafruit_httpserver".format(
                        type(error).__name__
                    ))
        elif configuration_ok:
            print("Standalone mode: startup boost, then configured duty")
        if controller.state in ("configuration_error", "wifi_unavailable"):
            print("Holding 100% PWM; correct settings/libraries and reload code.py")
        print("Boot complete; fan wiring is not required. PWM output does not confirm fan rotation.")
        print("Tach sensing is automatic; diagnostics every 5 seconds show falling-edge counts")
        tach_debug = TachDebug(tach)
        last_report = None
        while True:
            controller.tick()
            if network is not None:
                network.poll()
            status = controller.status()
            # Compare displayed values only; command age changes even when idle.
            report = (status["applied_duty"], status["rpm"], status["state"])
            if report != last_report:
                print("PWM: {}% | RPM: {} | {}".format(*report))
                last_report = report
            tach_debug.report(status["applied_duty"])
            time.sleep(0.05)
    except Exception as error:
        pwm.duty_cycle = 65535
        # Do not print exception messages that could include network credentials.
        print("Controller error:", type(error).__name__)
        print("Holding 100% PWM; check settings/libraries and reload code.py")
        while True:
            time.sleep(1)
    finally:
        try:
            if network is not None:
                network.close()
        finally:
            if tach is not None:
                tach.deinit()
            pwm.deinit()


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        print("Controller stopped; PWM released. Reload code.py to restart.")
