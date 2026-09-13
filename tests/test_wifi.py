"""Wi-Fi reconnection checks and actual HTTP parsing on the desktop."""

import contextlib
from errno import EAGAIN, ETIMEDOUT
import http.client
import io
import json
import socket
import sys
import threading
import types
import unittest
from unittest.mock import patch

from fan_control import FanControl
from wifi_control import send_bytes_bounded

try:
    import adafruit_httpserver
    from wifi_control import WiFiConfigurationError, WiFiControl, make_server
    HAS_HTTP_LIBRARY = True
except ImportError:
    HAS_HTTP_LIBRARY = False

WEB_USERNAME = "dashboard-user"
WEB_PASSWORD = "dashboard-password"


class BoundedSendChecks(unittest.TestCase):
    def test_partial_writes_send_the_complete_buffer(self):
        received = bytearray()

        class Connection:
            def send(self, data):
                count = min(2, len(data))
                received.extend(data[:count])
                return count

        ticks = iter(range(10))
        self.assertEqual(send_bytes_bounded(Connection(), b"abcdef", lambda: next(ticks)), 6)
        self.assertEqual(received, b"abcdef")

    def test_temporary_backpressure_can_recover(self):
        attempts = [0]

        class Connection:
            def send(self, data):
                attempts[0] += 1
                if attempts[0] == 1:
                    raise OSError(EAGAIN, "would block")
                return len(data)

        ticks = iter((0, 1, 2))
        self.assertEqual(send_bytes_bounded(Connection(), b"ok", lambda: next(ticks)), 2)

    def test_abandoned_client_times_out(self):
        class Connection:
            def send(self, data):
                return 0

        ticks = iter((0, 1_000_000_000, 3_000_000_000))
        with self.assertRaises(OSError) as caught:
            send_bytes_bounded(Connection(), b"stalled", lambda: next(ticks))
        self.assertEqual(caught.exception.errno, ETIMEDOUT)


@unittest.skipUnless(HAS_HTTP_LIBRARY, "install requirements-test.txt for HTTP/Wi-Fi checks")
class HttpChecks(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.fan = FanControl(types.SimpleNamespace(duty_cycle=0), remote=True,
                              clock=lambda: self.now)
        self.server = make_server(socket, self.fan, WEB_USERNAME, WEB_PASSWORD)
        self.server.start("127.0.0.1", port=0)
        self.port = self.server._sock.getsockname()[1]
        self.stop = threading.Event()
        self.errors = []

        def serve():
            while not self.stop.is_set():
                try:
                    self.server.poll()
                except Exception as error:
                    self.errors.append(error)
                    return
                self.stop.wait(0.001)

        self.thread = threading.Thread(target=serve)
        self.thread.start()
        self.cookie = None
        status, _ = self.login()
        self.assertEqual(status, 200)

    def tearDown(self):
        self.stop.set()
        self.thread.join(timeout=3)
        self.server.stop()
        self.assertFalse(self.thread.is_alive())
        self.assertEqual(self.errors, [])

    def request(self, method, path, body=None, authorization=None,
                content_type="application/json", use_cookie=True):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=2)
        headers = {"Content-Type": content_type} if content_type is not None else {}
        if authorization is not None:
            headers["Authorization"] = authorization
        if use_cookie and self.cookie is not None:
            headers["Cookie"] = self.cookie
        try:
            connection.request(method, path, body, headers)
            response = connection.getresponse()
            response_body = response.read().decode()
            set_cookie = response.getheader("Set-Cookie")
            if use_cookie and set_cookie is not None:
                cookie = set_cookie.split(";", 1)[0]
                self.cookie = None if cookie.endswith("=") else cookie
            return response.status, response_body
        finally:
            connection.close()

    def login(self, username=WEB_USERNAME, password=WEB_PASSWORD):
        return self.request("POST", "/api/login", json.dumps({
            "username": username, "password": password,
        }))

    def test_off_and_speed_commands_use_login_session(self):
        status, body = self.request("POST", "/api/fan", '{"duty":0}')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["applied_duty"], 0)
        status, body = self.request("POST", "/api/fan", '{"duty":60}')
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["startup_boost"])
        self.now = 3_000_000_000
        _, body = self.request("GET", "/api/status")
        self.assertEqual(json.loads(body)["applied_duty"], 60)

    def test_login_is_required_and_obsolete_bearer_is_rejected(self):
        self.cookie = None
        self.assertEqual(self.request("GET", "/api/status")[0], 401)
        self.assertEqual(self.request("POST", "/api/fan", '{"duty":0}')[0], 401)
        self.assertEqual(self.request(
            "POST", "/api/fan", '{"duty":0}', "Bearer obsolete-token"
        )[0], 401)
        self.assertEqual(self.fan.applied, 100)
        self.assertEqual(self.request("GET", "/")[0], 302)

    def test_login_session_and_logout(self):
        status, body = self.request("GET", "/api/session")
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["authenticated"])
        self.assertEqual(self.request("POST", "/api/logout", '{}')[0], 200)
        self.assertIsNone(self.cookie)
        self.assertFalse(json.loads(self.request("GET", "/api/session")[1])["authenticated"])
        self.assertEqual(self.request("GET", "/api/status")[0], 401)
        self.assertEqual(self.login(password="wrong-password")[0], 401)
        self.assertIsNone(self.cookie)
        self.assertEqual(self.login()[0], 200)
        self.assertIsNotNone(self.cookie)

    def test_bad_json_and_duty_do_not_refresh_command(self):
        for body in ('{', '[]', '{}', '{"duty":true}', '{"duty":10}',
                     '{"duty":101}', '{"duty":"60"}', '{"duty":0,"extra":1}'):
            with self.subTest(body=body):
                status, _ = self.request("POST", "/api/fan", body)
                self.assertEqual(status, 400)
        self.assertIsNone(self.fan.last_command)

    def test_writes_require_json_content_type(self):
        for path in ("/api/fan", "/api/release", "/api/telemetry", "/api/curve",
                     "/api/automatic"):
            with self.subTest(path=path):
                status, _ = self.request("POST", path, '{}', content_type="text/plain")
                self.assertEqual(status, 415)
        self.assertIsNone(self.fan.last_command)

    def test_status_does_not_extend_command_lease(self):
        self.request("POST", "/api/fan", '{"duty":0}')
        self.now = 30_000_000_000
        status, body = self.request("GET", "/api/status")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["state"], "command_timeout")

    def test_credentials_are_not_served_as_files(self):
        status, _ = self.request("GET", "/settings.toml")
        self.assertEqual(status, 404)

    def test_login_assets_are_public_but_dashboard_and_api_require_session(self):
        self.cookie = None
        for path in ("/login", "/dashboard.css", "/login.js", "/maximize-2.svg", "/x.svg"):
            with self.subTest(path=path):
                status, body = self.request("GET", path)
                self.assertEqual(status, 200)
        self.assertEqual(self.request("GET", "/")[0], 302)
        self.assertEqual(self.request("GET", "/api/dashboard")[0], 401)
        self.assertEqual(self.login()[0], 200)
        for path in ("/", "/dashboard-loader.js", "/dashboard.js",
                     "/api/dashboard", "/api/history"):
            self.assertEqual(self.request("GET", path)[0], 200)
        for path in ("/code.py", "/wifi_control.py", "/www/../settings.toml", "/lib/README.md"):
            self.assertEqual(self.request("GET", path)[0], 404)

    def test_telemetry_does_not_renew_fan_lease(self):
        body = '{"gpu_temperature_c":55.5,"cpu_temperature_c":48}'
        self.request("POST", "/api/fan", '{"duty":0}')
        self.now = 30_000_000_000
        self.assertEqual(self.request("POST", "/api/telemetry", body)[0], 200)
        _, response = self.request("GET", "/api/dashboard")
        data = json.loads(response)
        self.assertEqual(data["gpu_temperature_c"], 55.5)
        self.assertEqual(data["state"], "command_timeout")

    def test_invalid_telemetry_and_history_parameters(self):
        for body in ('{', '{}', '[]', '{"cpu_temperature_c":999}'):
            self.assertEqual(self.request("POST", "/api/telemetry", body)[0], 400)
        for query in ("limit=0", "limit=121", "before=-1", "before=nan"):
            self.assertEqual(self.request("GET", "/api/history?" + query)[0], 400)

    def test_release_requests_full_speed_with_session(self):
        self.request("POST", "/api/fan", '{"duty":0}')
        self.assertEqual(self.fan.applied, 0)
        status, body = self.request("POST", "/api/release", '{}')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["applied_duty"], 100)

    def test_public_reads_do_not_refresh_off_command(self):
        self.request("POST", "/api/fan", '{"duty":0}')
        self.now = 30_000_000_000
        self.request("GET", "/api/history")
        _, body = self.request("GET", "/api/dashboard")
        self.assertEqual(json.loads(body)["state"], "command_timeout")

    def test_curve_settings_do_not_immediately_control_fan(self):
        _, body = self.request("GET", "/api/curve")
        data = json.loads(body)["settings"]
        data["off_temp_c"] = 42
        body = json.dumps(data)
        self.request("POST", "/api/fan", '{"duty":0}')
        self.now = 5_000_000_000
        status, response = self.request("POST", "/api/curve", body)
        self.assertEqual(status, 200)
        result = json.loads(response)
        self.assertEqual(result["settings"]["off_temp_c"], 42)
        self.assertEqual(result["source"], "session")
        self.assertTrue(result["automatic_control_active"])
        self.assertEqual(self.fan.applied, 0)
        self.assertEqual(self.fan.last_command, 0)
        self.assertEqual(self.request("POST", "/api/curve", '{}')[0], 400)
        self.assertEqual(self.fan.curve.settings["off_temp_c"], 42)

    def test_automatic_control_toggle_defaults_on_and_uses_full_speed_transition(self):
        self.assertTrue(self.fan.curve.automatic_control_active)
        self.request("POST", "/api/fan", '{"duty":20}')
        status, body = self.request("POST", "/api/automatic", '{"active":false}')
        self.assertEqual(status, 200)
        self.assertFalse(json.loads(body)["automatic_control_active"])
        self.assertEqual(self.fan.state, "automatic_disabled")
        self.assertEqual(self.fan.applied, 100)
        status, body = self.request("POST", "/api/automatic", '{"active":true}')
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["automatic_control_active"])
        self.assertEqual(self.fan.state, "automatic_starting")
        for body in ('{}', '{"active":1}', '{"active":true,"extra":0}'):
            self.assertEqual(self.request("POST", "/api/automatic", body)[0], 400)


@unittest.skipUnless(HAS_HTTP_LIBRARY, "install requirements-test.txt for HTTP/Wi-Fi checks")
class ReconnectChecks(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.fan = FanControl(types.SimpleNamespace(duty_cycle=0), remote=True,
                              clock=lambda: self.now)
        self.radio = types.SimpleNamespace(connected=False, ipv4_address=None)
        self.attempts = 0
        self.fail_connect = False
        self.static_config = None

        def connect(ssid, password, *, timeout):
            self.attempts += 1
            self.assertEqual(timeout, 5)
            self.assertEqual(self.fan.applied, 100)
            if self.fail_connect:
                raise ConnectionError("test connection failed")
            self.radio.connected = True
            self.radio.ipv4_address = "192.0.2.10"

        self.radio.connect = connect

        def set_ipv4_address(**config):
            self.static_config = config

        self.radio.set_ipv4_address = set_ipv4_address
        self.server = types.SimpleNamespace(
            start=lambda *a, **k: None, stop=lambda: None, poll=lambda: None
        )
        modules = {
            "wifi": types.SimpleNamespace(radio=self.radio),
            "socketpool": types.SimpleNamespace(SocketPool=lambda radio: object()),
        }
        with patch.dict(sys.modules, modules), patch("wifi_control.make_server", return_value=self.server):
            self.network = WiFiControl(
                self.fan, ssid="test", password="test-password",
                web_username=WEB_USERNAME, web_password=WEB_PASSWORD,
            )
        self.network._advertise = lambda: None

    def poll(self):
        with patch("wifi_control.time.monotonic_ns", side_effect=lambda: self.now), contextlib.redirect_stdout(io.StringIO()):
            self.network.poll()

    def test_reconnect_requires_a_new_command(self):
        self.poll()
        self.assertEqual(self.network.listening_ip, "192.0.2.10")
        self.fan.command(0)
        self.radio.connected = False
        self.radio.ipv4_address = None
        self.poll()
        self.assertEqual(self.fan.applied, 100)
        self.assertIsNone(self.fan.last_command)
        self.assertEqual(self.attempts, 2)

    def test_failed_connections_are_retried_with_backoff(self):
        self.fail_connect = True
        self.poll()
        self.poll()
        self.assertEqual(self.attempts, 1)
        self.now = 10_000_000_000
        self.poll()
        self.assertEqual(self.attempts, 2)
        self.assertEqual(self.fan.applied, 100)

    def test_optional_static_ipv4_configuration_is_applied(self):
        modules = {
            "wifi": types.SimpleNamespace(radio=self.radio),
            "socketpool": types.SimpleNamespace(SocketPool=lambda radio: object()),
        }
        with patch.dict(sys.modules, modules), patch("wifi_control.make_server", return_value=self.server):
            WiFiControl(
                self.fan, ssid="test", password="test-password",
                web_username=WEB_USERNAME, web_password=WEB_PASSWORD,
                ipv4_address="192.168.2.77", ipv4_netmask="255.255.255.0",
                ipv4_gateway="192.168.2.1", ipv4_dns="192.168.2.8",
            )
        self.assertEqual(str(self.static_config["ipv4"]), "192.168.2.77")
        self.assertEqual(str(self.static_config["netmask"]), "255.255.255.0")
        self.assertEqual(str(self.static_config["gateway"]), "192.168.2.1")
        self.assertEqual(str(self.static_config["ipv4_dns"]), "192.168.2.8")

    def test_partial_static_ipv4_configuration_is_rejected(self):
        modules = {
            "wifi": types.SimpleNamespace(radio=self.radio),
            "socketpool": types.SimpleNamespace(SocketPool=lambda radio: object()),
        }
        with patch.dict(sys.modules, modules), patch("wifi_control.make_server", return_value=self.server):
            with self.assertRaises(WiFiConfigurationError):
                WiFiControl(
                    self.fan, ssid="test", password="test-password",
                    web_username=WEB_USERNAME, web_password=WEB_PASSWORD,
                    ipv4_address="192.168.2.77",
                )

    def test_server_error_forces_full_speed(self):
        self.poll()
        self.fan.command(0)

        def fail():
            raise OSError("test socket failed")

        self.server.poll = fail
        self.poll()
        self.assertEqual(self.fan.applied, 100)
        self.assertEqual(self.fan.state, "network_error")
        self.assertIsNone(self.network.listening_ip)

    def test_client_send_timeout_keeps_listener_and_fan_state(self):
        self.poll()
        self.fan.command(0)

        def timeout():
            raise OSError(ETIMEDOUT, "client send stalled")

        self.server.poll = timeout
        self.poll()
        self.assertEqual(self.fan.applied, 0)
        self.assertEqual(self.fan.state, "controlled")
        self.assertEqual(self.network.listening_ip, "192.0.2.10")
