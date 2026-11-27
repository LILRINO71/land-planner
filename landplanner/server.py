"""The local web server: the app's pages from web/ and its data under /api/. Standard library only.

It listens on this computer only (127.0.0.1). Requests that name another host, or that try to change My lands
from another website, are refused.

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
landplanner/district/api.py; see docs/district-data-contract.md. The routes above stay open without signing in.

Add &fresh=1 to a GET to ask the public service again instead of using the saved copy.
HEAD on an /api route answers like GET without the body. Any other method (PUT, PATCH, OPTIONS, ...) is a JSON 405,
and every error, including the library's own, is JSON. A parcel number is digits with dashes or spaces: a letter is
refused ("not a parcel number"), and a number of the wrong length is a 400.
"""
import json
import mimetypes
import re
import sys
import threading
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


def _is_district(path):
    return path == "/api/districts" or path.startswith("/api/districts/")


def make_handler(planner, web=WEB, verbose=False):
    districts = {}
    districts_guard = threading.Lock()

    def district_api():
        """The district projects' API, made on first use (its data lives in the same data folder)."""
        with districts_guard:
            if "api" not in districts:
                from .district.api import DistrictAPI
                districts["api"] = DistrictAPI(planner.data_dir)
            return districts["api"]

    class Handler(BaseHTTPRequestHandler):
        server_version = "LandPlanner/" + VERSION
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):
            if verbose:
                sys.stderr.write("%s  %s\n" % (self.log_date_time_string(), fmt % args))

        # -- answers

        def _send(self, status, body, kind, extra=None):
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for name, value in {**SECURITY, **(extra or {})}.items():
                self.send_header(name, value)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, status, answer, extra=None):
            self._send(status, json.dumps(answer, separators=(",", ":")).encode("utf-8"), "application/json; charset=utf-8", extra)

        def _problem(self, status, code, message):
            self._json(status, {"error": {"code": code, "message": message}})

        # -- checks

        def _local(self):
            """Only requests addressed to this computer by name: a web page elsewhere cannot point a made-up
            host name at this server and read from it."""
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]").lower()
            if host in ("127.0.0.1", "localhost", "::1"):
                return True
            self._problem(403, "not-local", "Land Planner only answers on this computer.")
            return False

        def _same_site(self):
            """Changes to My lands must come from the app's own pages."""
            origin = self.headers.get("Origin")
            if origin:
                host = urllib.parse.urlsplit(origin).hostname or ""
                if host.lower() not in ("127.0.0.1", "localhost", "::1"):
                    self._problem(403, "not-local", "Land Planner only answers on this computer.")
                    return False
            if self.command == "POST" and "application/json" not in (self.headers.get("Content-Type") or "").lower():
                self._problem(415, "bad-request", "Send JSON.")
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
                reply = district_api().handle(method, url.path, urllib.parse.parse_qs(url.query), self.headers, body)
                self._send(reply.status, reply.body, reply.kind, reply.headers)
            except Exception:  # noqa: BLE001 - never show a stack trace in the browser
                traceback.print_exc()
                self._problem(500, "internal", "Something went wrong inside Land Planner. Try again; if it keeps "
                                               "happening, close and restart it.")

        def _district_change(self):
            """District changes: JSON, or a file's bytes as application/octet-stream (which a form on another
            site cannot send without the browser asking first). The session cookie is SameSite=Strict too."""
            origin = self.headers.get("Origin")
            if origin and (urllib.parse.urlsplit(origin).hostname or "").lower() not in ("127.0.0.1", "localhost", "::1"):
                return self._problem(403, "not-local", "Land Planner only answers on this computer.")
            kind = (self.headers.get("Content-Type") or "").lower()
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = -1
            limit = DISTRICT_FILE_LIMIT if "application/octet-stream" in kind else DISTRICT_JSON_LIMIT
            if length < 0 or length > limit:
                self.close_connection = True
                return self._problem(413, "too-large", "Too much data.")
            if length and "application/json" not in kind and "application/octet-stream" not in kind:
                self.close_connection = True
                return self._problem(415, "bad-request", "Send JSON, or a file as application/octet-stream.")
            self._district(self.rfile.read(length) if length else b"")

        def do_GET(self):
            if not self._local():
                return
            api = urllib.parse.urlsplit(self.path).path
            if _is_district(api):
                return self._district()
            if api == "/api" or api.startswith("/api/"):
                return self._api()
            self._static()

        do_HEAD = do_GET

        def _change(self):
            if _is_district(urllib.parse.urlsplit(self.path).path):
                return self._district_change() if self._local() else None
            if not self._local() or not self._same_site():
                return
            body = None
            length = int(self.headers.get("Content-Length") or 0)
            if length > 65536:
                self.close_connection = True
                return self._problem(413, "bad-request", "Too much data.")
            if length:
                try:
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
    daemon_threads = True
    allow_reuse_address = False  # on Windows "reuse" would let two copies of the app share one port


def make_server(planner, port=0, web=WEB, verbose=False):
    """A server on 127.0.0.1 only. port=0 picks any free port (the tests use that)."""
    return LocalServer(("127.0.0.1", port), make_handler(planner, web, verbose))
