"""Letting other computers in, safely: HTTPS (TLS 1.2 or newer, Secure cookies, HSTS), the refusal to open a
network address over plain HTTP, the Host header guard (DNS rebinding), the Origin and Referer guard on changes,
sign-in for every route in network mode, request limits and time limits, and that 127.0.0.1 behaves as before.

Network mode is tried on 127.0.0.1 (require_sign_in=True), so no test opens a port to the network. The HTTPS
certificate is tests/fixtures/tls-test-only (a throwaway made by tools/make-cert.ps1; its key is public)."""
import contextlib
import http.client
import io
import json
import os
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from landplanner import __main__ as start  # noqa: E402
from landplanner.district import access  # noqa: E402
from landplanner.planner import LandPlanner  # noqa: E402
from landplanner.server import Refused, host_name, is_loopback, make_server, tls_context  # noqa: E402

access.ITERATIONS = 1000
TLS = ROOT / "tests" / "fixtures" / "tls-test-only"
CERT, KEY = TLS / "cert.pem", TLS / "key.pem"
JSON = {"Content-Type": "application/json"}


class Served(unittest.TestCase):
    """A real server on a random port of 127.0.0.1, in a temporary data folder."""
    https = False
    options = {}

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.server = self.serve(**self.options)
        self.port = self.server.server_address[1]
        self.client_tls = ssl.create_default_context(cafile=str(CERT)) if self.https else None

    def serve(self, **kw):
        if self.https:
            kw.setdefault("tls", tls_context(CERT, KEY))
        server = make_server(LandPlanner({}, self.folder.name), 0, **kw)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server

    def ask(self, method, path, body=None, headers=None, server=None):
        port = (server or self.server).server_address[1]
        if self.client_tls:
            c = http.client.HTTPSConnection("127.0.0.1", port, timeout=10, context=self.client_tls)
        else:
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        if isinstance(body, dict):
            body, headers = json.dumps(body), {**JSON, **(headers or {})}
        try:
            c.request(method, path, body=body, headers=headers or {})
            r = c.getresponse()
            data = r.read()
            try:
                data = json.loads(data.decode("utf-8")) if r.getheader("Content-Type", "").startswith("application/json") else data
            except ValueError:
                pass
            return r.status, data, {k.lower(): v for k, v in r.getheaders()}
        finally:
            c.close()

    def own(self):
        return f"{'https' if self.https else 'http'}://127.0.0.1:{self.port}"

    def sign_in(self, name, passcode, nda=True):
        s, b, h = self.ask("POST", "/api/districts/session", {"method": "passcode", "name": name, "passcode": passcode})
        self.assertEqual(s, 200, b)
        jar = {"Cookie": h["set-cookie"].split(";")[0]}
        if nda:
            self.assertEqual(self.ask("POST", "/api/districts/session/nda", {"accept": True}, jar)[0], 200)
        return jar, h["set-cookie"]


# ---------------------------------------------------------------- starting

class Starting(unittest.TestCase):
    def test_a_network_address_without_https_is_refused_before_anything_is_opened(self):
        for host in ("0.0.0.0", "192.168.1.20", "::", ""):
            with self.assertRaises(Refused, msg=host):
                make_server(LandPlanner({}, tempfile.gettempdir()), 0, host=host)

    def test_the_command_line_refuses_plain_http_on_the_network_and_says_why(self):
        with tempfile.TemporaryDirectory() as data:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = start.main(["--host", "0.0.0.0", "--no-browser", "--data", data])
            self.assertEqual(code, 2)
            self.assertIn("without HTTPS", out.getvalue())
            self.assertIn("--allow-plain-http", out.getvalue())

    def test_https_without_a_certificate_says_how_to_make_one(self):
        with tempfile.TemporaryDirectory() as data:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = start.main(["--host", "0.0.0.0", "--https", "--no-browser", "--data", data])
            self.assertEqual(code, 2)
            self.assertIn("make-cert.ps1", out.getvalue())
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(start.main(["--https", "--cert", str(CERT), "--no-browser", "--data", data]), 2)
            self.assertIn("both --cert and --key", out.getvalue())

    def test_loopback_and_host_names_are_read_carefully(self):
        for h in ("127.0.0.1", "127.5.5.5", "::1", "[::1]", "localhost", "LOCALHOST"):
            self.assertTrue(is_loopback(h), h)
        for h in ("0.0.0.0", "", "::", "192.168.1.2", "localhost.evil.example", "10.0.0.1"):
            self.assertFalse(is_loopback(h), h)
        self.assertEqual(host_name("127.0.0.1:8777"), "127.0.0.1")
        self.assertEqual(host_name("[::1]:8777"), "::1")
        self.assertEqual(host_name("LocalHost.:8777"), "localhost")
        self.assertEqual(host_name("[::1"), "")
        self.assertEqual(host_name(None), "")


# ---------------------------------------------------------------- the Host and Origin guards

class HostGuard(Served):
    def test_only_the_servers_own_names_are_answered(self):
        for host in (f"127.0.0.1:{self.port}", "localhost", f"[::1]:{self.port}", "127.0.0.1"):
            self.assertEqual(self.ask("GET", "/api/health", headers={"Host": host})[0], 200, host)
        for host in ("evil.example", f"evil.example:{self.port}", "127.0.0.1.evil.example", "localhost.evil.example",
                     "", "[::1"):
            for path in ("/api/health", "/", "/api/districts", "/api/cities"):
                s, b, _ = self.ask("GET", path, headers={"Host": host})
                self.assertEqual(s, 403, (host, path))
                self.assertEqual(b["error"]["code"], "not-local")
        self.assertEqual(self.ask("POST", "/api/my-lands", {"city": "x", "apn": "1"}, {"Host": "evil.example"})[0], 403)

    def test_a_request_with_no_host_at_all_is_refused(self):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.putrequest("GET", "/api/health", skip_host=True)
        c.endheaders()
        self.assertEqual(c.getresponse().status, 403)
        c.close()

    def test_extra_names_are_answered_when_given(self):
        named = self.serve(names=["planner.test"])
        self.assertEqual(self.ask("GET", "/api/health", headers={"Host": "planner.test"}, server=named)[0], 200)
        self.assertEqual(self.ask("GET", "/api/health", headers={"Host": "planner.test"})[0], 403)


class OriginGuard(Served):
    def change(self, origin=None, referer=None, path="/api/my-lands", method="POST"):
        headers = {}
        if origin is not None:
            headers["Origin"] = origin
        if referer is not None:
            headers["Referer"] = referer
        return self.ask(method, path, {"city": "nowhere", "apn": "1"} if method == "POST" else None, headers)

    def test_a_change_from_another_origin_is_refused(self):
        other = self.port + 1 if self.port < 65535 else self.port - 1
        for origin in ("http://evil.example", f"http://127.0.0.1:{other}", f"https://127.0.0.1:{self.port}",
                       "null", "", f"http://evil.example:{self.port}"):
            s, b, _ = self.change(origin)
            self.assertEqual((s, b["error"]["code"]), (403, "not-local"), origin)
        s, _, _ = self.change(referer="http://evil.example/page")
        self.assertEqual(s, 403, "a Referer from elsewhere too")
        s, _, _ = self.change(origin=self.own(), referer="http://evil.example/page")
        self.assertEqual(s, 403, "both are checked")
        self.assertEqual(self.change("http://evil.example", path="/api/my-lands/nowhere/1", method="DELETE")[0], 403)
        self.assertEqual(self.change("http://evil.example", path="/api/districts/session")[0], 403)
        self.assertEqual(self.change(referer="http://evil.example/", path="/api/districts/session", method="DELETE")[0],
                         403)

    def test_a_change_from_the_servers_own_pages_goes_through(self):
        for origin in (None, self.own(), f"http://localhost:{self.port}", f"http://[::1]:{self.port}"):
            s, b, _ = self.change(origin, referer=None if origin is None else origin + "/#/lands")
            self.assertNotEqual(s, 403, (origin, b))
            self.assertNotEqual(s, 401, origin)
        s, b, _ = self.ask("POST", "/api/districts/session", {"method": "passcode", "name": "Owner",
                                                              "passcode": "owner-pass-1"}, {"Origin": self.own()})
        self.assertEqual(s, 200, b)

    def test_reading_is_not_blocked_by_an_origin(self):
        self.assertEqual(self.ask("GET", "/api/cities", headers={"Origin": "http://evil.example"})[0], 200)

    def test_a_public_url_from_a_reverse_proxy_may_send_changes(self):
        proxied = self.serve(public_urls=["https://planner.example.org"])
        s, _, _ = self.ask("POST", "/api/districts/session", {"method": "passcode", "name": "Owner",
                                                              "passcode": "owner-pass-1"},
                           {"Host": "planner.example.org", "Origin": "https://planner.example.org"}, server=proxied)
        self.assertEqual(s, 200)
        s, b, _ = self.ask("GET", "/api/cities", headers={"Host": "planner.example.org"}, server=proxied)
        self.assertEqual((s, b["error"]["code"]), (401, "sign-in-needed"), "behind a proxy, sign-in is required")


# ---------------------------------------------------------------- 127.0.0.1 as before

class LocalhostUnchanged(Served):
    def test_the_apps_own_routes_need_no_sign_in_and_the_cookie_is_as_before(self):
        self.assertFalse(self.server.network)
        for path in ("/api/cities", "/api/my-lands", "/api/health", "/"):
            s, _, h = self.ask("GET", path)
            self.assertEqual(s, 200, path)
            self.assertNotIn("strict-transport-security", h)
        self.assertNotIn(self.ask("POST", "/api/my-lands", {"city": "nowhere", "apn": "1"})[0], (401, 403))
        _, cookie = self.sign_in("Owner", "owner-pass-1")
        self.assertEqual(cookie.split("; ")[1:], ["HttpOnly", "SameSite=Strict", "Path=/api/districts"])


# ---------------------------------------------------------------- network mode

class NetworkMode(Served):
    options = {"require_sign_in": True}

    def test_every_route_but_sign_in_and_the_pages_needs_a_signed_in_user(self):
        for path in ("/", "/js/main.js", "/style.css", "/api/health", "/api/districts", "/api/districts/session"):
            self.assertEqual(self.ask("GET", path)[0], 200, path)
        for method, path in (("GET", "/api/cities"), ("GET", "/api/my-lands"), ("HEAD", "/api/cities"),
                             ("GET", "/api/cities/menifee/lands"), ("GET", "/api/my-lands/compare"),
                             ("GET", "/api/cities/menifee/forecast?apns=1"), ("POST", "/api/my-lands"),
                             ("DELETE", "/api/my-lands/menifee/1"), ("GET", "/api/districts/projects")):
            s, b, _ = self.ask(method, path, {"city": "menifee", "apn": "1"} if method == "POST" else None)
            self.assertEqual(s, 401, (method, path))
            if method != "HEAD":
                self.assertEqual(b["error"]["code"], "sign-in-needed", path)
        s, b, _ = self.ask("GET", "/api/cities", headers={"Cookie": "lp_district=made-up"})
        self.assertEqual(s, 401)

    def test_signed_in_users_read_and_only_administrators_and_analysts_change(self):
        admin, cookie = self.sign_in("Owner", "owner-pass-1", nda=False)
        self.assertIn("Path=/api;", cookie + ";", "the cookie reaches every /api route in network mode")
        s, b, _ = self.ask("GET", "/api/cities", headers=admin)
        self.assertEqual((s, b["error"]["code"]), (403, "nda-needed"))
        self.assertEqual(self.ask("POST", "/api/districts/session/nda", {"accept": True}, admin)[0], 200)
        self.assertEqual(self.ask("GET", "/api/cities", headers=admin)[0], 200)
        self.assertNotIn(self.ask("POST", "/api/my-lands", {"city": "nowhere", "apn": "1"}, admin)[0], (401, 403))
        for role in ("viewer_city", "viewer_partner", "consultant", "analyst"):
            s, b, _ = self.ask("POST", "/api/districts/users", {"name": role, "role": role, "projects": ["*"],
                                                                "passcode": f"pass-{role}-1"}, admin)
            self.assertEqual(s, 200, b)
            jar, _ = self.sign_in(role, f"pass-{role}-1")
            self.assertEqual(self.ask("GET", "/api/cities", headers=jar)[0], 200, role)
            s, b, _ = self.ask("POST", "/api/my-lands", {"city": "nowhere", "apn": "1"}, jar)
            if role == "analyst":
                self.assertNotIn(s, (401, 403))
            else:
                self.assertEqual((s, b["error"]["code"]), (403, "forbidden"), role)
                self.assertEqual(self.ask("DELETE", "/api/cities/menifee/lands/1/plan", headers=jar)[0], 403, role)

    def test_a_signed_in_user_stays_signed_in_when_the_server_restarts(self):
        admin, _ = self.sign_in("Owner", "owner-pass-1")
        self.server.shutdown()
        self.server.server_close()
        again = self.serve(require_sign_in=True)
        self.assertEqual(self.ask("GET", "/api/cities", headers=admin, server=again)[0], 200)
        self.assertEqual(self.ask("GET", "/api/districts/projects", headers=admin, server=again)[0], 200)
        kept = (Path(self.folder.name) / "district-sessions.json").read_text(encoding="utf-8")
        self.assertNotIn(admin["Cookie"].split("=", 1)[1], kept, "only the token's hash is on disk")
        self.assertEqual(self.ask("DELETE", "/api/districts/session", headers=admin, server=again)[0], 200)
        self.assertEqual(self.ask("GET", "/api/cities", headers=admin, server=again)[0], 401, "sign-out still works")


# ---------------------------------------------------------------- HTTPS

class Https(Served):
    https = True
    options = {"require_sign_in": True, "names": ["planner.test"]}

    def test_tls_is_12_or_newer_and_the_cookie_is_secure(self):
        c = http.client.HTTPSConnection("127.0.0.1", self.port, timeout=10, context=self.client_tls)
        c.request("GET", "/api/health")
        self.assertEqual(c.getresponse().status, 200)
        self.assertIn(c.sock.version(), ("TLSv1.2", "TLSv1.3"))
        c.close()
        _, cookie = self.sign_in("Owner", "owner-pass-1")
        self.assertEqual(cookie.split("; ")[1:], ["HttpOnly", "SameSite=Strict", "Path=/api", "Secure"])

    def test_old_tls_versions_are_refused(self):
        old = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        old.check_hostname, old.verify_mode = False, ssl.CERT_NONE
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)     # that is the point: an old client
            old.minimum_version = ssl.TLSVersion.MINIMUM_SUPPORTED
            old.maximum_version = ssl.TLSVersion.TLSv1_1
        try:
            old.set_ciphers("DEFAULT:@SECLEVEL=0")
        except ssl.SSLError:
            pass
        with socket.create_connection(("127.0.0.1", self.port), timeout=10) as raw:
            with self.assertRaises((ssl.SSLError, OSError)):
                old.wrap_socket(raw, server_hostname="localhost")

    def test_hsts_is_sent_on_https_except_to_localhost(self):
        s, _, h = self.ask("GET", "/api/health", headers={"Host": f"planner.test:{self.port}"})
        self.assertEqual(s, 200)
        self.assertEqual(h["strict-transport-security"], "max-age=31536000")
        self.assertEqual(self.ask("GET", "/", headers={"Host": "planner.test"})[2]["strict-transport-security"],
                         "max-age=31536000")
        self.assertNotIn("strict-transport-security", self.ask("GET", "/api/health")[2],
                         "HSTS would stick to 127.0.0.1 and break the plain one-computer mode")

    def test_plain_http_on_the_https_port_is_sent_to_https(self):
        for host, want in ((f"127.0.0.1:{self.port}", 307), ("evil.example", 400)):
            c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
            c.request("GET", "/#/districts?x=1", headers={"Host": host})
            r = c.getresponse()
            self.assertEqual(r.status, want, host)
            if want == 307:
                self.assertEqual(r.getheader("Location"), f"https://127.0.0.1:{self.port}/#/districts?x=1")
            r.read()
            c.close()

    def test_a_client_that_never_finishes_its_handshake_does_not_hold_up_others(self):
        quiet = socket.create_connection(("127.0.0.1", self.port), timeout=10)
        self.addCleanup(quiet.close)
        half = socket.create_connection(("127.0.0.1", self.port), timeout=10)
        self.addCleanup(half.close)
        half.sendall(b"\x16\x03\x01")                   # the start of a TLS hello, then nothing
        t = time.monotonic()
        self.assertEqual(self.ask("GET", "/api/health")[0], 200)
        self.assertLess(time.monotonic() - t, 5)


# ---------------------------------------------------------------- limits

class Limits(Served):
    options = {"request_timeout": 1}

    def raw(self, data):
        s = socket.create_connection(("127.0.0.1", self.port), timeout=10)
        self.addCleanup(s.close)
        s.sendall(data)
        return s

    def test_a_chunked_body_and_a_body_too_large_are_refused(self):
        s = self.raw(b"POST /api/my-lands HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\n"
                     b"Transfer-Encoding: chunked\r\n\r\n5\r\n{}{}{\r\n0\r\n\r\n")
        self.assertIn(b" 411 ", s.recv(4096))
        self.assertEqual(self.ask("POST", "/api/my-lands", "x" * 70000, JSON)[0], 413)
        self.assertEqual(self.ask("POST", "/api/districts/session", "x" * 10, {**JSON, "Content-Length": "-4"})[0], 400)
        big = self.raw(b"POST /api/districts/session HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\n"
                       b"Content-Length: 99999999999\r\n\r\n")
        self.assertIn(b" 413 ", big.recv(4096))

    def test_a_slow_client_is_cut_off_and_does_not_block_the_others(self):
        slow = self.raw(b"GET /api/health HTTP/1.1\r\nHost: 127.0")      # and then nothing
        t = time.monotonic()
        self.assertEqual(self.ask("GET", "/api/health")[0], 200)
        self.assertLess(time.monotonic() - t, 2, "others are answered meanwhile")
        slow.settimeout(10)
        try:
            gone = slow.recv(4096)
        except ConnectionError:
            gone = b""
        self.assertLess(time.monotonic() - t, 8, "the silent connection is closed after its time limit")
        self.assertNotIn(b"200 OK", gone)


class ConnectionCap(Served):
    options = {"max_connections": 2, "request_timeout": 20}

    def test_one_connection_too_many_is_told_to_try_again_and_the_slots_come_back(self):
        held = [socket.create_connection(("127.0.0.1", self.port), timeout=10) for _ in range(2)]
        for s in held:                                   # each holds a slot: one request done, kept alive
            s.sendall(f"GET /api/health HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\n\r\n".encode())
            self.assertIn(b" 200 ", s.recv(4096))
        s, b, h = self.ask("GET", "/api/health")
        self.assertEqual((s, b["error"]["code"]), (503, "busy"))
        self.assertEqual(h["retry-after"], "5")
        for s in held:
            s.close()
        deadline = time.monotonic() + 5
        while self.ask("GET", "/api/health")[0] != 200:
            self.assertLess(time.monotonic(), deadline, "a closed connection gives its slot back")
            time.sleep(0.05)

    def test_the_cap_turns_https_connections_away_too(self):
        tls = self.serve(max_connections=1, tls=tls_context(CERT, KEY))
        port = tls.server_address[1]
        ctx = ssl.create_default_context(cafile=str(CERT))
        first = ctx.wrap_socket(socket.create_connection(("127.0.0.1", port), timeout=10), server_hostname="127.0.0.1")
        self.addCleanup(first.close)
        with self.assertRaises((ssl.SSLError, OSError)):
            with socket.create_connection(("127.0.0.1", port), timeout=10) as raw:
                ctx.wrap_socket(raw, server_hostname="127.0.0.1")


# ---------------------------------------------------------------- tools/make-cert.ps1

@unittest.skipUnless(os.name == "nt" and shutil.which("powershell"), "Windows PowerShell makes the certificate")
class MakeCert(unittest.TestCase):
    def test_the_script_makes_a_certificate_python_can_serve_with(self):
        with tempfile.TemporaryDirectory() as out:
            label = f"Land Planner test {os.getpid()}"
            done = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                                   str(ROOT / "tools" / "make-cert.ps1"), "-OutDir", out, "-OnlyGiven",
                                   "-DnsName", "localhost,planner.test", "-IpAddress", "127.0.0.1", "-Years", "1",
                                   "-Label", label], capture_output=True, text=True, timeout=120)
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            cert, key = Path(out) / "cert.pem", Path(out) / "key.pem"
            tls_context(cert, key)
            names = dict.fromkeys(v for _, v in ssl._ssl._test_decode_cert(str(cert))["subjectAltName"])
            self.assertEqual(list(names), ["localhost", "planner.test", "127.0.0.1"])
            self.assertTrue((Path(out) / "land-planner.cer").is_file())
            again = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                                    str(ROOT / "tools" / "make-cert.ps1"), "-OutDir", out],
                                   capture_output=True, text=True, timeout=60)
            self.assertIn("already", again.stdout, "an existing certificate is kept without -Force")
            left = subprocess.run(["powershell", "-NoProfile", "-Command",
                                   f"@(Get-ChildItem Cert:\\CurrentUser\\My | Where-Object {{ $_.Subject -eq 'CN={label}' }}).Count"],
                                  capture_output=True, text=True, timeout=60)
            self.assertEqual(left.stdout.strip(), "0", "the copy in the Windows certificate store is deleted")


if __name__ == "__main__":
    unittest.main()
