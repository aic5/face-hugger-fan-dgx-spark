"""Local Wi-Fi API with settings-backed login and browser sessions."""

import binascii
from errno import EAGAIN, ECONNRESET, ETIMEDOUT
import os
import time

class WiFiConfigurationError(ValueError):
    """A configuration error whose message contains no credential values."""


def validate_login(web_username, web_password):
    if (not isinstance(web_username, str) or not web_username
            or not isinstance(web_password, str) or not web_password):
        raise WiFiConfigurationError(
            "FAN_WEB_USERNAME and FAN_WEB_PASSWORD are required in settings.toml"
        )


def send_bytes_bounded(connection, buffer, clock=time.monotonic_ns,
                       stall_ns=3_000_000_000):
    """Send a buffer without allowing an abandoned client to freeze the server."""
    sent = 0
    stalled_at = clock()
    view = memoryview(buffer)
    while sent < len(buffer):
        try:
            count = connection.send(view[sent:])
        except OSError as error:
            if error.errno == ECONNRESET:
                raise
            if error.errno != EAGAIN:
                raise
            count = 0
        now = clock()
        if count:
            sent += count
            stalled_at = now
        elif now - stalled_at >= stall_ns:
            raise OSError(ETIMEDOUT, "client send stalled")
    return sent


def make_server(pool, controller, web_username, web_password, *, web_root="www"):
    validate_login(web_username, web_password)
    from adafruit_httpserver import GET, POST, FileResponse, JSONResponse, Redirect, Server

    class BoundedFileResponse(FileResponse):
        def _send_bytes(self, connection, buffer):
            self._size += send_bytes_bounded(connection, buffer)

    def asset(request, filename):
        return BoundedFileResponse(
            request, filename, root_path=web_root,
            headers={"Cache-Control": "public, max-age=3600"},
        )

    # Explicit asset routes only: settings and firmware are never served.
    server = Server(pool, debug=False)
    server.socket_timeout = 0.5
    server.headers = {"Connection": "close", "Cache-Control": "no-store",
                      "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
                      "Referrer-Policy": "no-referrer",
                      "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"}
    sessions = []
    cookie_name = "fan_session"

    def require_json(request):
        content_type = request.headers.get("Content-Type", "")
        if content_type.split(";", 1)[0].strip().lower() != "application/json":
            return JSONResponse(request, {"error": "Content-Type must be application/json"},
                                status=(415, "Unsupported Media Type"))
        return None

    def new_session():
        token = binascii.hexlify(os.urandom(24)).decode("ascii")
        sessions.append(token)
        if len(sessions) > 4:
            sessions.pop(0)
        return token

    def authorized(request):
        return request.cookies.get(cookie_name) in sessions

    def deny(request):
        return JSONResponse(request, {"error": "login required"},
                            status=(401, "Unauthorized"))

    @server.route("/", GET)
    def dashboard(request):
        if not authorized(request):
            return Redirect(request, "/login")
        return BoundedFileResponse(request, "index.html", root_path=web_root)

    @server.route("/login", GET)
    def login_page(request):
        if authorized(request):
            return Redirect(request, "/")
        return BoundedFileResponse(request, "login.html", root_path=web_root)

    @server.route("/dashboard.css", GET)
    def stylesheet(request):
        return asset(request, "dashboard.css")

    @server.route("/dashboard.js", GET)
    def javascript(request):
        return asset(request, "dashboard.js")

    @server.route("/dashboard-loader.js", GET)
    def dashboard_loader(request):
        return asset(request, "dashboard-loader.js")

    @server.route("/login.js", GET)
    def login_javascript(request):
        return asset(request, "login.js")

    @server.route("/maximize-2.svg", GET)
    def expand_icon(request):
        return asset(request, "maximize-2.svg")

    @server.route("/x.svg", GET)
    def close_icon(request):
        return asset(request, "x.svg")

    @server.route("/api/session", GET)
    def session_status(request):
        return JSONResponse(request, {"authenticated": authorized(request)})

    @server.route("/api/login", POST)
    def login(request):
        error = require_json(request)
        if error is not None:
            return error
        try:
            data = request.json()
            valid = (isinstance(data, dict) and len(data) == 2
                     and data.get("username") == web_username
                     and data.get("password") == web_password)
        except (ValueError, TypeError):
            valid = False
        if not valid:
            return JSONResponse(request, {"error": "invalid username or password"},
                                status=(401, "Unauthorized"))
        token = new_session()
        return JSONResponse(
            request, {"authenticated": True},
            cookies={cookie_name: token + "; Path=/; HttpOnly; SameSite=Strict"},
        )

    @server.route("/api/logout", POST)
    def logout(request):
        error = require_json(request)
        if error is not None:
            return error
        token = request.cookies.get(cookie_name)
        if token in sessions:
            sessions.remove(token)
        return JSONResponse(
            request, {"authenticated": False},
            cookies={cookie_name: "; Path=/; HttpOnly; SameSite=Strict; Max-Age=0"},
        )

    @server.route("/api/dashboard", GET)
    def dashboard_status(request):
        if not authorized(request):
            return deny(request)
        controller.tick()
        return JSONResponse(request, controller.status())

    @server.route("/api/history", GET)
    def history(request):
        if not authorized(request):
            return deny(request)
        controller.tick()
        try:
            before = request.query_params.get("before")
            before = None if before is None else int(before)
            limit = int(request.query_params.get("limit", "120"))
            data = controller.history.page(before, limit)
        except (ValueError, TypeError):
            return JSONResponse(request, {"error": "invalid history page; limit 1-120, before >= 0"},
                                status=(400, "Bad Request"))
        return JSONResponse(request, data)

    @server.route("/api/curve", GET)
    def get_curve(request):
        if not authorized(request):
            return deny(request)
        return JSONResponse(request, controller.curve.status())

    @server.route("/api/curve", POST)
    def set_curve(request):
        if not authorized(request):
            return deny(request)
        error = require_json(request)
        if error is not None:
            return error
        try:
            controller.curve.update(request.json())
        except (ValueError, TypeError):
            return JSONResponse(request, {"error": "invalid curve: check ordered temperatures and PWM percentages"},
                                status=(400, "Bad Request"))
        return JSONResponse(request, controller.curve.status())

    @server.route("/api/automatic", POST)
    def set_automatic(request):
        if not authorized(request):
            return deny(request)
        error = require_json(request)
        if error is not None:
            return error
        try:
            data = request.json()
            if not isinstance(data, dict) or set(data) != {"active"}:
                raise ValueError("expected an active field")
            controller.curve.set_automatic(data["active"])
        except (ValueError, TypeError) as error:
            return JSONResponse(request, {"error": str(error)},
                                status=(400, "Bad Request"))
        # A transition never leaves a stale low-speed lease in force. The DGX
        # service will issue the first curve command after activation.
        controller.failsafe(
            "automatic_starting" if data["active"] else "automatic_disabled"
        )
        return JSONResponse(request, controller.curve.status())

    @server.route("/api/status", GET)
    def status(request):
        if not authorized(request):
            return deny(request)
        controller.tick()
        return JSONResponse(request, controller.status())

    @server.route("/api/fan", POST)
    def set_fan(request):
        if not authorized(request):
            return deny(request)
        error = require_json(request)
        if error is not None:
            return error
        try:
            data = request.json()
            if not isinstance(data, dict) or len(data) != 1 or "duty" not in data:
                raise ValueError("expected a JSON object with only a duty field")
            controller.command(data["duty"])
        except (ValueError, TypeError) as error:
            return JSONResponse(request, {"error": str(error)},
                                status=(400, "Bad Request"))
        return JSONResponse(request, controller.status())

    @server.route("/api/release", POST)
    def release(request):
        if not authorized(request):
            return deny(request)
        error = require_json(request)
        if error is not None:
            return error
        controller.failsafe("awaiting_command")
        return JSONResponse(request, controller.status())

    @server.route("/api/telemetry", POST)
    def telemetry(request):
        if not authorized(request):
            return deny(request)
        error = require_json(request)
        if error is not None:
            return error
        try:
            controller.history.update(request.json())
        except (ValueError, TypeError):
            return JSONResponse(request, {"error": "send CPU/GPU temperature fields as numbers (-20 to 125 C) or null"},
                                status=(400, "Bad Request"))
        return JSONResponse(request, controller.status())

    return server


class WiFiControl:
    def __init__(self, controller, *, ssid, password, web_username, web_password,
                 hostname="dgx-fan", port=80, ipv4_address=None,
                 ipv4_netmask=None, ipv4_gateway=None, ipv4_dns=None):
        if not isinstance(ssid, str) or not ssid or not isinstance(password, str):
            raise WiFiConfigurationError("WIFI_SSID and WIFI_PASSWORD are required in settings.toml")
        validate_login(web_username, web_password)
        if type(port) is not int or not 1 <= port <= 65535:
            raise WiFiConfigurationError("FAN_HTTP_PORT must be between 1 and 65535")
        if (not isinstance(hostname, str) or not hostname or len(hostname) > 63 or hostname.startswith("-")
                or hostname.endswith("-")
                or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in hostname)):
            raise WiFiConfigurationError("DEVICE_NAME must be a lowercase hostname, without .local")
        import socketpool
        import wifi
        self.controller = controller
        self.radio = wifi.radio
        self.radio.hostname = hostname
        static_values = (ipv4_address, ipv4_netmask, ipv4_gateway)
        if any(static_values) and not all(static_values):
            raise WiFiConfigurationError(
                "WIFI_IPV4_ADDRESS, WIFI_IPV4_NETMASK and WIFI_IPV4_GATEWAY must be set together"
            )
        if not ipv4_address and ipv4_dns:
            raise WiFiConfigurationError("WIFI_IPV4_DNS requires a static IPv4 address")
        if ipv4_address:
            try:
                import ipaddress
                static_config = {
                    "ipv4": ipaddress.ip_address(ipv4_address),
                    "netmask": ipaddress.ip_address(ipv4_netmask),
                    "gateway": ipaddress.ip_address(ipv4_gateway),
                    "ipv4_dns": ipaddress.ip_address(ipv4_dns) if ipv4_dns else None,
                }
                self.radio.set_ipv4_address(**static_config)
            except (AttributeError, TypeError, ValueError, OSError, RuntimeError):
                raise WiFiConfigurationError("Static IPv4 settings are invalid or unavailable")
        self.ssid, self.password = ssid, password
        self.hostname, self.port = hostname, port
        self.server = make_server(
            socketpool.SocketPool(self.radio), controller, web_username, web_password
        )
        self.listening_ip = None
        self.next_attempt = 0
        self.mdns = None

    def _stop(self):
        try:
            self.server.stop()
        except OSError:
            pass
        self.listening_ip = None

    def _advertise(self):
        try:
            if self.mdns is None:
                import mdns
                self.mdns = mdns.Server(self.radio)
            self.mdns.hostname = self.hostname
            self.mdns.advertise_service(service_type="_http", protocol="_tcp", port=self.port)
            print("Fan hostname: http://{}.local:{}".format(self.hostname, self.port))
        except (ImportError, OSError, RuntimeError):
            print("mDNS unavailable; use the printed IP address")

    def poll(self):
        self.controller.tick()
        now = time.monotonic_ns()
        connected = self.radio.connected and self.radio.ipv4_address is not None
        if not connected:
            self.controller.failsafe("wifi_disconnected")
            if self.listening_ip is not None:
                self._stop()
            if now < self.next_attempt:
                return
            try:
                # Cooling is already at full speed during this bounded blocking call.
                self.radio.connect(self.ssid, self.password, timeout=5)
            except (OSError, ConnectionError):
                print("Wi-Fi connection failed; retrying in 10 seconds")
            self.next_attempt = time.monotonic_ns() + 10_000_000_000
            if not self.radio.connected or self.radio.ipv4_address is None:
                return
            now = time.monotonic_ns()
            self.next_attempt = now

        ip = str(self.radio.ipv4_address)
        if ip != self.listening_ip:
            self.controller.failsafe("awaiting_command")
            if self.listening_ip is not None:
                self._stop()
            if now < self.next_attempt:
                return
            try:
                self.server.start(ip, port=self.port)
            except OSError:
                self._stop()
                self.next_attempt = now + 10_000_000_000
                print("HTTP listener unavailable; retrying in 10 seconds")
                return
            self.listening_ip = ip
            print("Fan API: http://{}:{}/api/status".format(ip, self.port))
            self._advertise()

        try:
            self.server.poll()
        except OSError as error:
            if error.errno != ETIMEDOUT:
                self.controller.failsafe("network_error")
                self._stop()
                self.next_attempt = time.monotonic_ns() + 10_000_000_000
        except ValueError:
            self.controller.failsafe("network_error")
            self._stop()
            self.next_attempt = time.monotonic_ns() + 10_000_000_000
        self.controller.tick()

    def close(self):
        self._stop()
        if self.mdns is not None:
            self.mdns.deinit()
