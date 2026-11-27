"""The web server: the app's pages from web/ and its data under /api/. Standard library only.

By default it listens on this computer only (127.0.0.1), over plain HTTP, exactly as before. Network mode
(python -m landplanner --host 0.0.0.0 --https) lets other computers sign in: HTTPS with TLS 1.2 or newer, HSTS,
Secure cookies, and every /api route except /api/health and the sign-in routes under /api/districts needs a
signed-in district user (changes to lands, plans and forecasts: an administrator or analyst). The pages and
scripts under web/ hold no data and stay open, so the sign-in page can load. A non-local address without HTTPS is
refused unless allow_plain_http is given.

On every request, in both modes: the Host header must be one of this server's own names or addresses (a web page
elsewhere cannot point a made-up host name at it: DNS rebinding), and a POST or DELETE whose Origin or Referer is
sent must come from this server's own address (scheme, host and port). Each connection has its own thread and a
time limit, and request bodies have a size limit, so one slow or greedy client cannot hold up the others.

    GET    /api/health
    GET    /api/cities                                  the cities and how each is described
    GET    /api/cities/<city>/summary                   live count of large parcels (the city card)
    GET    /api/cities/<city>/lands                     the large parcels: ?min_acres= &max_acres= &zoning= &kind=
                                                        &vacant=1 &q= &sort=acres|apn|zoning|vacant|land_value &dir=asc|desc
    GET    /api/cities/<city>/shapes                    outlines of the listed parcels, for the map: ?min_acres=
    GET    /api/cities/<city>/parcels                   every parcel in a map view: ?west= &south= &east= &north=
    GET    /api/cities/<city>/updated                   when the records and the aerial photo date from: ?lat= &lon=
    GET    /api/cities/<city>/lands/<apn>               one land: ?group=quick (default) or ground
    GET    /api/cities/<city>/lands/<apn>/plan          the suggested land-use plan, with the owner's kept changes
    POST   /api/cities/<city>/lands/<apn>/plan          the plan with these changes (they are kept): {"mode", "acres",
                                                        "assumptions", "extra_costs", "land_cost"}
    DELETE /api/cities/<city>/lands/<apn>/plan          forget the changes: back to the suggested plan
    GET    /api/cities/<city>/forecast?apns=a,b,c       the year-by-year forecast for one parcel or several as one site
    POST   /api/cities/<city>/forecast?apns=a,b,c       the forecast with the owner's own figures (kept): {"assumptions"}
    DELETE /api/cities/<city>/forecast?apns=a,b,c       back to the starting figures
    GET    /api/cities/<city>/outlook?apns=a,b,c        the wider picture for the same site: economy, weather, hazards,
                                                        what is close by, the typical resident, the steps to take
    GET    /api/cities/<city>/ground?apns=a,b,c         the ground heights under the site and the plan on it (3D view)
    GET    /api/my-lands
    GET    /api/my-lands/compare                        My lands side by side: each one's plan in a few numbers
    POST   /api/my-lands            {"city": "menifee", "apn": "372100001"}
    DELETE /api/my-lands/<city>/<apn>

Everything under /api/districts (district projects: sign-in, roles, datasets, imports, exports) is answered by
landplanner/district/api.py; see docs/district-data-contract.md. The routes above stay open without signing in on 127.0.0.1;
in network mode they need a signed-in district user.

Add &fresh=1 to a GET to ask the public service again instead of using the saved copy.
HEAD on an /api route answers like GET without the body. Any other method (PUT, PATCH, OPTIONS, ...) is a JSON 405,
and every error, including the library's own, is JSON. A parcel number is digits with dashes or spaces: a letter is
refused ("not a parcel number"), and a number of the wrong length is a 400.
"""
import ipaddress
import json
import mimetypes
import re
import socket
import ssl
import sys
import threading
import time
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import APP, VERSION
from .planner import Problem

WEB = Path(__file__).resolve().parent.parent / "web"
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
         ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon", ".json": "application/json"}
SECURITY = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data: blob: https://basemap.nationalmap.gov "
                               "https://imagery.nationalmap.gov; "
                               "style-src 'self' 'unsafe-inline'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
}


def _number(query, name):
    text = (query.get(name) or [""])[0].strip()
    if not text:
        return None
    try:
        value = float(text)
    except ValueError:
        raise Problem(400, "bad-request", f"“{text}” is not a number of acres.") from None
    if value != value or abs(value) > 1e7:
        raise Problem(400, "bad-request", f"“{text}” is not a number of acres.")
    if value < 0:
        raise Problem(400, "bad-request", f"Acres cannot be negative (“{text}”).")
    return value


def _degrees(query, name):
    """A latitude or longitude from the address, or None when it is missing or not a number."""
    try:
        value = float((query.get(name) or [""])[0])
    except ValueError:
        return None
    return value if -180 <= value <= 180 else None


def _flag(query, name):
    return (query.get(name) or [""])[0].lower() in ("1", "true", "yes", "on")


def _text(query, name, limit=60):
    return (query.get(name) or [""])[0].strip()[:limit]


def _apns(query):
    return [a for a in re.split(r"[\s,+]+", (query.get("apns") or [""])[0].strip()[:400]) if a]


def route(planner, method, path, query=None, body=None):
    """(status, answer) for one request to /api/. Raises Problem for anything the person should be told."""
    query = query or {}
    parts = [urllib.parse.unquote(p) for p in path.strip("/").split("/")]
    if parts[:1] != ["api"]:
        raise Problem(404, "not-found", "Nothing here.")
    parts = parts[1:]
    fresh = _flag(query, "fresh")
    if len(parts) == 3 and parts[0] == "cities" and parts[2] == "forecast" and method in ("GET", "POST", "DELETE"):
        if method == "POST" and not isinstance(body, dict):
            raise Problem(400, "bad-request", "Send the forecast's figures as JSON.")
        return 200, planner.forecast(parts[1], _apns(query), settings=body if method == "POST" else None,
                                     forget=method == "DELETE")
    if method == "GET" and len(parts) == 3 and parts[0] == "cities" and parts[2] == "outlook":
        return 200, planner.outlook(parts[1], _apns(query), fresh)
    if method == "GET" and len(parts) == 3 and parts[0] == "cities" and parts[2] == "ground":
        return 200, planner.ground(parts[1], _apns(query), fresh)
    if method == "GET":
        if parts == ["health"]:
            return 200, {"app": APP, "version": VERSION}
        if parts == ["cities"]:
            return 200, planner.city_list()
        if len(parts) == 3 and parts[0] == "cities" and parts[2] == "summary":
            return 200, planner.summary(parts[1], fresh)
        if len(parts) == 3 and parts[0] == "cities" and parts[2] == "shapes":
            return 200, planner.shapes(parts[1], _number(query, "min_acres"))
        if len(parts) == 3 and parts[0] == "cities" and parts[2] == "parcels":
            return 200, planner.parcels_in_view(parts[1], *(_degrees(query, k) for k in ("west", "south", "east", "north")))
        if len(parts) == 3 and parts[0] == "cities" and parts[2] == "updated":
            return 200, planner.updated(parts[1], _degrees(query, "lat"), _degrees(query, "lon"))
        if len(parts) == 3 and parts[0] == "cities" and parts[2] == "lands":
            return 200, planner.lands(
                parts[1], min_acres=_number(query, "min_acres"), max_acres=_number(query, "max_acres"),
                zoning=_text(query, "zoning"), kind=_text(query, "kind"), vacant=_flag(query, "vacant"),
                q=_text(query, "q"), sort=_text(query, "sort") or "acres",
                descending=_text(query, "dir").lower() != "asc", fresh=fresh)
        if len(parts) == 4 and parts[0] == "cities" and parts[2] == "lands":
            return 200, planner.land(parts[1], parts[3], _text(query, "group") or "quick", fresh)
        if len(parts) == 5 and parts[0] == "cities" and parts[2] == "lands" and parts[4] == "plan":
            return 200, planner.plan(parts[1], parts[3])
        if parts == ["my-lands"]:
            return 200, planner.my_lands()
        if parts == ["my-lands", "compare"]:
            return 200, planner.compare()
    elif method in ("POST", "DELETE") and len(parts) == 5 and parts[0] == "cities" and parts[2] == "lands" and parts[4] == "plan":
        if method == "DELETE":
            return 200, planner.plan(parts[1], parts[3], forget=True)
        if not isinstance(body, dict):
            raise Problem(400, "bad-request", "Send the plan's settings as JSON.")
        return 200, planner.plan(parts[1], parts[3], settings=body)
    elif method == "POST" and parts == ["my-lands"]:
        if not isinstance(body, dict) or not body.get("city") or not body.get("apn"):
            raise Problem(400, "bad-request", "Saving a land needs its city and parcel number.")
        return 200, planner.save(str(body["city"]), str(body["apn"]))
    elif method == "DELETE" and len(parts) == 3 and parts[0] == "my-lands":
        return 200, planner.remove(parts[1], parts[2])
    raise Problem(404, "not-found", "Nothing here.")


DISTRICT_JSON_LIMIT = 2 * 1024 * 1024
DISTRICT_FILE_LIMIT = 64 * 1024 * 1024
JSON_LIMIT = 65536                  # the app's own routes (plans, forecasts, My lands)
REQUEST_TIMEOUT = 30                # seconds a connection may sit silent (handshake, headers, body) before it is closed
MAX_CONNECTIONS = 128               # connections served at once (a browser keeps about six open); more are turned away
_BUSY_BODY = b'{"error":{"code":"busy","message":"Land Planner is answering too many people at once. Try again soon."}}'
BUSY = (b"HTTP/1.1 503 Service Unavailable\r\nContent-Type: application/json; charset=utf-8\r\nRetry-After: 5\r\n"
        b"Content-Length: " + str(len(_BUSY_BODY)).encode() + b"\r\nConnection: close\r\n\r\n" + _BUSY_BODY)
LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})
HSTS = "max-age=31536000"
DRAIN_LIMIT = DISTRICT_JSON_LIMIT     # an unused body up to this size is read before a refusal (see _drain)
INTERNAL_ROLES = ("administrator", "analyst")   # who may change lands, plans and forecasts in network mode


class Refused(Exception):
    """The server will not start like this (a network address without HTTPS)."""


def is_loopback(host):
    """True for an address only this computer can reach (127.x, ::1, localhost)."""
    h = str(host or "").strip("[]").lower()
    if h == "localhost":
        return True
    try:
        return ipaddress.ip_address(h).is_loopback
    except ValueError:
        return False


def _is_ip(text):
    try:
        ipaddress.ip_address(str(text).strip("[]"))
        return True
    except ValueError:
        return False


def host_name(value):
    """The name in a Host header: lower case, without the port, IPv6 brackets or a final dot ('' when none)."""
    v = str(value or "").strip().lower()
    if v.startswith("["):
        v = v[1:v.index("]")] if "]" in v else ""
    elif v.count(":") == 1:
        v = v.rsplit(":", 1)[0]
    return v.rstrip(".")


def _origin(url):
    """(scheme, host, port) of an address, or None when it is not an http(s) address."""
    try:
        u = urllib.parse.urlsplit(str(url).strip())
        port = u.port
    except ValueError:
        return None
    if u.scheme not in ("http", "https") or not u.hostname:
        return None
    return u.scheme, u.hostname.lower().rstrip("."), port or (443 if u.scheme == "https" else 80)


def local_names():
    """This computer's own names and addresses: its name, its full name, the addresses the name resolves to and the
    address it uses to reach the network."""
    found = set()
    try:
        name = socket.gethostname()
        found |= {name.lower(), socket.getfqdn().lower()}
        for info in socket.getaddrinfo(name, None):
            found.add(str(info[4][0]).split("%")[0].lower())
    except OSError:
        pass
    for family, probe in ((socket.AF_INET, ("192.0.2.1", 9)), (socket.AF_INET6, ("2001:db8::1", 9))):
        try:
            with socket.socket(family, socket.SOCK_DGRAM) as s:
                s.connect(probe)                  # no packet is sent: this only asks which address would be used
                found.add(str(s.getsockname()[0]).split("%")[0].lower())
        except OSError:
            pass
    return {n.rstrip(".") for n in found if n}


def lan_addresses():
    """This computer's IPv4 addresses on the local network, the one it uses to reach the network first."""
    out = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))
            out.append(s.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            out.append(info[4][0])
    except OSError:
        pass
    keep = []
    for a in out:
        ip = ipaddress.ip_address(a)
        if not (ip.is_loopback or ip.is_link_local or ip.is_unspecified) and a not in keep:
            keep.append(a)
    return keep


def tls_context(cert, key):
    """A server TLS context: TLS 1.2 or newer, forward-secret AEAD ciphers only, no compression or renegotiation."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.set_ciphers("ECDHE+AESGCM:ECDHE+CHACHA20")     # TLS 1.2; TLS 1.3's own suites are all modern
    ctx.options |= ssl.OP_NO_COMPRESSION | ssl.OP_CIPHER_SERVER_PREFERENCE | getattr(ssl, "OP_NO_RENEGOTIATION", 0)
    ctx.load_cert_chain(str(cert), str(key))
    return ctx


def _is_district(path):
    return path == "/api/districts" or path.startswith("/api/districts/")


def make_handler(planner, web=WEB, verbose=False, secure=False, require_sign_in=False):
    """secure: served over HTTPS (Secure cookies, HSTS). require_sign_in: network mode (see the module's notes)."""
    districts = {}
    districts_guard = threading.Lock()

    def district_api(server=None):
        """The district projects' API, made on first use (its data lives in the same data folder)."""
        with districts_guard:
            if "api" not in districts:
                from .district.api import COOKIE, COOKIE_PATH, DistrictAPI
                port = getattr(server, "server_address", (None, None))[1]
                # cookies do not keep ports apart: on plain HTTP the port is in the name, so two copies of the app on
                # one computer do not sign each other out; on HTTPS the __Host- name, which only this origin can set
                name = "__Host-" + COOKIE if secure else f"{COOKIE}_{port}" if port else COOKIE
                # in network mode the session cookie must reach the app's other /api routes too
                districts["api"] = DistrictAPI(planner.data_dir, secure=secure, cookie_name=name,
                                               cookie_path="/api" if require_sign_in else COOKIE_PATH)
            return districts["api"]

    class Handler(BaseHTTPRequestHandler):
        server_version = "LandPlanner/" + VERSION
        protocol_version = "HTTP/1.1"

        def setup(self):
            self.timeout = getattr(self.server, "request_timeout", REQUEST_TIMEOUT)
            super().setup()

        def parse_request(self):
            self._drained = False                 # a new request on the same connection: its body is not read yet
            return super().parse_request()

        def _drain(self):
            """Read and drop a request body that will not be used, before a refusal is sent: Windows resets a
            connection closed with unread data, and the answer would be lost. A body larger than DRAIN_LIMIT is
            not read; the connection is closed instead."""
            if getattr(self, "_drained", True):
                return
            self._drained = True
            headers = getattr(self, "headers", None)
            if headers is None:
                return
            if headers.get("Transfer-Encoding"):
                self.close_connection = True
                return
            try:
                n = int(headers.get("Content-Length") or 0)
            except ValueError:
                n = -1
            if 0 < n <= DRAIN_LIMIT:
                try:
                    self.rfile.read(n)
                except OSError:
                    self.close_connection = True
            elif n:
                self.close_connection = True

        def log_message(self, fmt, *args):
            if verbose:
                sys.stderr.write("%s  %s\n" % (self.log_date_time_string(), fmt % args))

        # -- answers

        def _send(self, status, body, kind, extra=None):
            if status >= 400:
                self._drain()
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for name, value in {**SECURITY, **(extra or {})}.items():
                self.send_header(name, value)
            if secure and host_name((getattr(self, "headers", None) or {}).get("Host")) not in LOOPBACK:
                self.send_header("Strict-Transport-Security", HSTS)   # never for localhost: it would stick to it
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, status, answer, extra=None):
            self._send(status, json.dumps(answer, separators=(",", ":")).encode("utf-8"), "application/json; charset=utf-8", extra)

        def _problem(self, status, code, message):
            self._json(status, {"error": {"code": code, "message": message}})

        # -- checks

        def _local(self):
            """Only requests addressed to this server by one of its own names: a web page elsewhere cannot point a
            made-up host name at this server and read from it (DNS rebinding)."""
            if self.server.allowed_host(host_name(self.headers.get("Host"))):
                return True
            self.close_connection = True
            self._problem(403, "not-local", "Land Planner does not answer to that address." if self.server.network
                          else "Land Planner only answers on this computer.")
            return False

        def _from_here(self):
            """A change must come from this server's own pages. Its Origin (scheme, host and port) is this server's
            own; with no Origin, the browser's Sec-Fetch-Site says same-origin. A request with neither is refused:
            every browser sends at least one of them with a POST or DELETE, so only a page elsewhere could be
            hiding where it came from. A Referer, when sent, must be this server's too."""
            origin, fetch_site = self.headers.get("Origin"), self.headers.get("Sec-Fetch-Site")
            ok = (self.server.own_origin(origin) if origin is not None
                  else str(fetch_site or "").strip().lower() == "same-origin")
            if ok and fetch_site is not None and str(fetch_site).strip().lower() not in ("same-origin", "none"):
                ok = False                        # the browser says it came from another site or port
            referer = self.headers.get("Referer")
            if ok and referer is not None and not self.server.own_origin(referer):
                ok = False
            if not ok:
                self.close_connection = True
                self._problem(403, "not-local", "Changes must come from Land Planner's own pages (send the Origin "
                                                "header of this server's address).")
            return ok

        def _same_site(self):
            """Changes to My lands must come from the app's own pages."""
            if not self._from_here():
                return False
            if self.command == "POST" and "application/json" not in (self.headers.get("Content-Type") or "").lower():
                self._problem(415, "bad-request", "Send JSON.")
                return False
            return True

        def _length(self, limit, code="too-large"):
            """The body's length when it can be read, else None (the answer is sent and the connection closed)."""
            if self.headers.get("Transfer-Encoding"):
                self.close_connection = True
                self._problem(411, "bad-request", "Send the body with a Content-Length.")
                return None
            if len(self.headers.get_all("Content-Length") or []) > 1:
                self.close_connection = True       # two lengths: a proxy and this server could read different bodies
                self._problem(400, "bad-request", "Send one Content-Length.")
                return None
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = -1
            if length < 0:
                self.close_connection = True
                self._problem(400, "bad-request", "The Content-Length is not a number.")
                return None
            if length > limit:
                self.close_connection = True
                self._problem(413, code, "Too much data.")
                return None
            return length

        def _signed_in(self, change=False):
            """Network mode only: the app's own routes need a signed-in district user who accepted the NDA, and a
            change (lands, plans, forecasts, My lands) needs an administrator or analyst."""
            if not require_sign_in:
                return True
            from .district import Problem as DistrictProblem
            api = district_api(self.server)
            try:
                user = api.signed_in_user(self.headers, self.client_address[0])
            except DistrictProblem as e:
                message = {"sign-in-needed": "Sign in first: open Districts (#/districts), sign in, then come back.",
                           "session-expired": "You were signed out after a time without use. Open Districts "
                                              "(#/districts) and sign in again."}.get(e.code, e.message)
                extra = {"Set-Cookie": api._clear()} if e.code == "session-expired" else None
                self.close_connection = True
                self._json(e.status, {"error": {"code": e.code, "message": message}}, extra)
                return False
            if change and user.get("role") not in INTERNAL_ROLES:
                wanted = f"{self.command} {urllib.parse.urlsplit(self.path).path}"[:200]
                api.audit.log("denied", user, "denied", None, wanted=wanted)
                self.close_connection = True
                self._problem(403, "forbidden", "Only an administrator or analyst can change lands, plans and forecasts.")
                return False
            return True

        # -- requests

        def _api(self, body=None):
            url = urllib.parse.urlsplit(self.path)
            try:
                # HEAD answers like GET (the body is left out when it is sent)
                method = "GET" if self.command == "HEAD" else self.command
                status, answer = route(planner, method, url.path, urllib.parse.parse_qs(url.query), body)
                self._json(status, answer)
            except Problem as e:
                self._problem(e.status, e.code, e.message)
            except Exception:  # noqa: BLE001 - never show a stack trace in the browser
                traceback.print_exc()
                self._problem(500, "internal", "Something went wrong inside Land Planner. Try again; if it keeps "
                                               "happening, close and restart it.")

        def _static(self):
            path = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path)
            if path in ("", "/"):
                path = "/index.html"
            target = (web / path.lstrip("/")).resolve()
            if web.resolve() not in target.parents or not target.is_file():
                if re.fullmatch(r"/[\w\-/]*", path) and not path.startswith("/api"):
                    target = web / "index.html"  # an address typed without the "#" still opens the app
                else:
                    return self._send(404, b"Not found", "text/plain; charset=utf-8")
            kind = TYPES.get(target.suffix.lower()) or mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            self._send(200, target.read_bytes(), kind)

        def _district(self, body=b""):
            url = urllib.parse.urlsplit(self.path)
            try:
                method = "GET" if self.command == "HEAD" else self.command
                reply = district_api(self.server).handle(method, url.path, urllib.parse.parse_qs(url.query), self.headers, body,
                                              client=self.client_address[0])
                self._send(reply.status, reply.body, reply.kind, reply.headers)
            except Exception:  # noqa: BLE001 - never show a stack trace in the browser
                traceback.print_exc()
                self._problem(500, "internal", "Something went wrong inside Land Planner. Try again; if it keeps "
                                               "happening, close and restart it.")

        def _district_change(self):
            """District changes: JSON, or a file's bytes as application/octet-stream (which a form on another
            site cannot send without the browser asking first). The session cookie is SameSite=Strict too."""
            if not self._from_here():
                return
            kind = (self.headers.get("Content-Type") or "").lower()
            limit = DISTRICT_FILE_LIMIT if "application/octet-stream" in kind else DISTRICT_JSON_LIMIT
            length = self._length(limit)
            if length is None:
                return
            # every POST, even one with no body, carries a type a form or a plain fetch from another page cannot send
            # without the browser asking first (JSON, a file's bytes, or the app's own X-Land-Planner header)
            needs_type = length or (self.command == "POST" and not self.headers.get("X-Land-Planner"))
            if needs_type and "application/json" not in kind and "application/octet-stream" not in kind:
                self.close_connection = True
                return self._problem(415, "bad-request", "Send JSON, or a file as application/octet-stream.")
            self._drained = True
            self._district(self.rfile.read(length) if length else b"")

        def do_GET(self):
            if not self._local():
                return
            api = urllib.parse.urlsplit(self.path).path
            if _is_district(api):
                return self._district()
            if api == "/api" or api.startswith("/api/"):
                if api != "/api/health" and not self._signed_in():
                    return
                return self._api()
            self._static()

        do_HEAD = do_GET

        def _change(self):
            if _is_district(urllib.parse.urlsplit(self.path).path):
                return self._district_change() if self._local() else None
            if not self._local() or not self._same_site():
                return
            body = None
            length = self._length(JSON_LIMIT, "bad-request")
            if length is None or not self._signed_in(change=True):
                return
            if length:
                try:
                    self._drained = True
                    body = json.loads(self.rfile.read(length).decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    return self._problem(400, "bad-request", "That was not readable JSON.")
            self._api(body)

        do_POST = do_DELETE = _change

        def _not_allowed(self):
            """Any other method gets the same kind of answer as every other error: JSON, with what is allowed."""
            self.close_connection = True      # a body that came with it is not read
            if not self._local():
                return
            allowed = "GET, HEAD, POST, DELETE" if urllib.parse.urlsplit(self.path).path.startswith("/api") else "GET, HEAD"
            self._json(405, {"error": {"code": "method-not-allowed",
                                       "message": f"Land Planner does not answer {self.command} here. It answers {allowed}."}},
                       {"Allow": allowed})

        do_PUT = do_PATCH = do_OPTIONS = _not_allowed

        def send_error(self, code, message=None, explain=None):
            """The library's own errors (a method nobody handles, a request it cannot read) as JSON too, never HTML."""
            self.close_connection = True
            text = message or self.responses.get(code, ("Error",))[0]
            self._json(code, {"error": {"code": "bad-request", "message": f"{text}."}})

    return Handler


class LocalServer(ThreadingHTTPServer):
    """One thread per connection. With tls set, the TLS handshake happens in that connection's own thread (never
    in the accepting loop, where one silent client would hold up everyone)."""
    daemon_threads = True
    allow_reuse_address = False  # on Windows "reuse" would let two copies of the app share one port
    request_queue_size = 32
    max_connections = MAX_CONNECTIONS
    _slots = None
    tls = None
    network = False
    names = LOOPBACK
    origins = frozenset()
    request_timeout = REQUEST_TIMEOUT
    _names_checked = 0.0

    @property
    def scheme(self):
        return "https" if self.tls is not None else "http"

    def allowed_host(self, name):
        if name and name in self.names:
            return True
        if name and self.network and time.monotonic() - self._names_checked > 30:
            self._names_checked = time.monotonic()      # the computer may have a new address since it started
            self.names = frozenset(self.names | local_names())
            return name in self.names
        return False

    def own_origin(self, url):
        o = _origin(url)
        if o is None:
            return False
        return o in self.origins or (o[0] == self.scheme and o[1] in self.names and o[2] == self.server_address[1])

    def finish_request(self, request, client_address):
        request.settimeout(self.request_timeout)
        if self.tls is None:
            return super().finish_request(request, client_address)
        if self._plain_http(request):
            return
        conn = self.tls.wrap_socket(request, server_side=True, do_handshake_on_connect=False)
        try:
            conn.do_handshake()
            self.RequestHandlerClass(conn, client_address, self)
        except (ssl.SSLError, OSError):
            pass                                          # not TLS, a refused version, or the client went away
        finally:
            conn.close()

    def _plain_http(self, sock):
        """A browser that typed http:// for this https:// server is sent to the https address (same host and
        path, temporary so it is not remembered) instead of seeing the connection fail. True when answered."""
        try:
            head = sock.recv(8, socket.MSG_PEEK)
        except OSError:
            return False
        if not re.match(rb"(GET|HEAD|POST|PUT|DELETE|OPTIONS|PATCH) ", head):
            return False                                  # a TLS hello starts with 0x16
        try:
            text = sock.recv(8192).decode("latin-1")
            first, *lines = text.split("\r\n")
            parts = first.split(" ")
            path = parts[1] if len(parts) > 1 and re.fullmatch(r"/[!-~]*", parts[1]) else "/"
            host = next((ln.split(":", 1)[1].strip() for ln in lines if ln.lower().startswith("host:")), "")
            if self.allowed_host(host_name(host)) and re.fullmatch(r"[A-Za-z0-9.:\[\]-]{1,260}", host):
                body = f"Land Planner uses https://{host}{path}\n".encode("utf-8")
                answer = (f"HTTP/1.1 307 Temporary Redirect\r\nLocation: https://{host}{path}\r\n"
                          "Cache-Control: no-store\r\n")
            else:
                body, answer = b"Land Planner answers on https:// only.\n", "HTTP/1.1 400 Bad Request\r\n"
            sock.sendall((answer + f"Content-Type: text/plain; charset=utf-8\r\nContent-Length: {len(body)}\r\n"
                          "Connection: close\r\n\r\n").encode("latin-1") + body)
        except OSError:
            pass
        return True

    def process_request(self, request, client_address):
        """At most max_connections connections are served at once: one more is answered 503 (plain HTTP) or
        closed (HTTPS, where a plain answer cannot be read) at once, from this loop, without a thread."""
        if self._slots is None:
            self._slots = threading.BoundedSemaphore(self.max_connections)
        if not self._slots.acquire(blocking=False):
            if self.tls is None:
                try:
                    request.settimeout(1)
                    request.sendall(BUSY)
                except OSError:
                    pass
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()

    def handle_error(self, request, client_address):
        if isinstance(sys.exc_info()[1], (ConnectionError, TimeoutError, ssl.SSLError)):
            return                                        # a client that went away or stalled is not a fault
        super().handle_error(request, client_address)


class LocalServer6(LocalServer):
    address_family = socket.AF_INET6


def make_server(planner, port=0, web=WEB, verbose=False, host="127.0.0.1", tls=None, allow_plain_http=False,
                names=(), public_urls=(), require_sign_in=None, request_timeout=REQUEST_TIMEOUT,
                max_connections=MAX_CONNECTIONS):
    """A server on 127.0.0.1 by default (plain HTTP, no sign-in for the app's own routes, exactly as before).

    host:        another address ("0.0.0.0" for every network) is network mode; it needs tls (an ssl.SSLContext
                 from tls_context) unless allow_plain_http, and raises Refused otherwise, before binding anything.
    names:       more host names this server answers to (a DNS name that points at this computer).
    public_urls: the address people use when a reverse proxy or tunnel serves the app (its host is allowed, its
                 origin may send changes, and sign-in is required as in network mode).
    require_sign_in: None decides from the above; the tests set it to try network mode on 127.0.0.1.
    max_connections: connections served at once; one more is turned away at once (503) instead of waiting.
    port=0 picks any free port (the tests use that)."""
    network = not is_loopback(host)
    if network and tls is None and not allow_plain_http:
        raise Refused(f"Land Planner will not open {host or 'every address'} to other computers without HTTPS: "
                      "passcodes and district data would cross the network unencrypted. Start it with --https, or "
                      "add --allow-plain-http if you really mean it.")
    public = []
    for url in public_urls or ():
        o = _origin(url)
        if o is None:
            raise Refused(f"“{url}” is not an http:// or https:// address.")
        public.append(o)
    if require_sign_in is None:
        require_sign_in = network or bool(public)
    kind = LocalServer6 if ":" in str(host) else LocalServer
    server = kind((host, port), make_handler(planner, web, verbose, secure=tls is not None,
                                             require_sign_in=require_sign_in))
    server.tls = tls
    server.network = network
    server.request_timeout = request_timeout
    server.max_connections = max(1, int(max_connections))
    server._slots = threading.BoundedSemaphore(server.max_connections)
    known = set(LOOPBACK) | {host_name(n) for n in names or () if n} | {o[1] for o in public}
    if network:
        known |= local_names()
        bound = str(host).strip("[]").lower()
        if bound and not (_is_ip(bound) and ipaddress.ip_address(bound).is_unspecified):
            known.add(bound)
    server.names = frozenset(known)
    server._names_checked = time.monotonic()
    server.origins = frozenset(public)
    return server
