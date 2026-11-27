"""Start Land Planner:  python -m landplanner   (or double-click "Start Land Planner.bat")

    --port 8777       the port to try first
    --no-browser      do not open the browser
    --data FOLDER     where My lands and the saved answers are kept (default: the data folder beside the app)
    --verbose         print every request

Letting other computers sign in (double-click "Start Land Planner (network).bat", or):

    --host 0.0.0.0    accept other computers (or one address of this computer); refused without --https
    --https           serve HTTPS. The certificate is --cert and --key (PEM files), else data/tls/cert.pem and
                      data/tls/key.pem, which tools/make-cert.ps1 makes for this computer
    --cert, --key     a real certificate and its private key (PEM), e.g. for the owner's own domain
    --name NAME       another host name people use to reach this computer (repeatable)
    --public-url URL  the address people use when a reverse proxy or tunnel serves the app (repeatable)
    --allow-plain-http  accept other computers over plain HTTP (passcodes cross the network unencrypted)
    --max-connections N connections served at once (default 128); one more is told to try again (503)
"""
import argparse
import json
import logging
import logging.handlers
import socket
import ssl
import sys
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

from . import APP
from .cities import all_cities
from .planner import LandPlanner
from .server import MAX_CONNECTIONS, Refused, is_loopback, lan_addresses, make_server, tls_context

ROOT = Path(__file__).resolve().parent.parent
PORT = 8777


def already_running(port, https=False):
    """True when Land Planner itself is answering on the port, False when something else is, None when it is free."""
    with socket.socket() as s:
        s.settimeout(0.5)
        if s.connect_ex(("127.0.0.1", port)) != 0:
            return None
    scheme = "https" if https else "http"
    # only this computer's own copy is asked, for its name: its certificate need not be checked for that
    context = ssl._create_unverified_context() if https else None  # noqa: S323 - 127.0.0.1, no data is sent
    try:
        with urllib.request.urlopen(f"{scheme}://127.0.0.1:{port}/api/health", timeout=2, context=context) as r:  # noqa: S310
            return json.loads(r.read().decode("utf-8")).get("app") == APP
    except (urllib.error.URLError, OSError, ValueError):
        return False


def keep_a_log(data):
    """Answers the app could not read are written to problems.log in the data folder (and to this window), with
    where each one happened, so a mistake in reading a source can be found later. The file stays small."""
    log = logging.getLogger("landplanner")
    if log.handlers:
        return
    line = logging.Formatter("%(asctime)s %(message)s")
    window = logging.StreamHandler()
    window.setFormatter(line)
    log.addHandler(window)
    try:
        Path(data).mkdir(parents=True, exist_ok=True)
        kept = logging.handlers.RotatingFileHandler(Path(data) / "problems.log", maxBytes=500_000, backupCount=1,
                                                    encoding="utf-8", delay=True)
        kept.setFormatter(line)
        log.addHandler(kept)
    except OSError:
        pass  # a log that cannot be written is only a log that is missing


def _certificate(args):
    """(cert, key) paths for --https, or a message saying what is missing."""
    if bool(args.cert) != bool(args.key):
        return None, "Give both --cert and --key (the certificate and its private key, as PEM files)."
    if args.cert:
        cert, key = Path(args.cert), Path(args.key)
    else:
        cert, key = Path(args.data) / "tls" / "cert.pem", Path(args.data) / "tls" / "key.pem"
    if not cert.is_file() or not key.is_file():
        return None, (f"There is no certificate at {cert} and {key}.\n"
                      "  Make one for this computer with:\n"
                      f'    powershell -ExecutionPolicy Bypass -File "{ROOT / "tools" / "make-cert.ps1"}"\n'
                      "  (\"Start Land Planner (network).bat\" does this by itself), or give a real certificate with "
                      "--cert and --key.")
    return (cert, key), None


def main(argv=None):
    ap = argparse.ArgumentParser(prog="landplanner", description="Land Planner. On this computer only unless --host "
                                                                 "is given (see --https).")
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--data", default=str(ROOT / "data"))
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--host", default="127.0.0.1", help="the address to listen on; 0.0.0.0 lets other computers in")
    ap.add_argument("--https", action="store_true", help="serve HTTPS (TLS 1.2 or newer)")
    ap.add_argument("--cert", help="the certificate (PEM) for --https")
    ap.add_argument("--key", help="the certificate's private key (PEM) for --https")
    ap.add_argument("--name", action="append", default=[], help="another host name this computer is reached by")
    ap.add_argument("--public-url", action="append", default=[], help="the address a reverse proxy serves it at")
    ap.add_argument("--allow-plain-http", action="store_true",
                    help="accept other computers without HTTPS (passcodes cross the network unencrypted)")
    ap.add_argument("--max-connections", type=int, default=MAX_CONNECTIONS,
                    help=f"connections served at once (default {MAX_CONNECTIONS}); more are told to try again")
    args = ap.parse_args(argv)
    network = not is_loopback(args.host)
    if args.cert or args.key:
        args.https = True

    if network and not args.https and not args.allow_plain_http:
        print(f"Land Planner will not open {args.host} to other computers without HTTPS: passcodes and district data "
              "would cross the network unencrypted.")
        print("  Start it with --https (\"Start Land Planner (network).bat\" does), or add --allow-plain-http if you "
              "really mean it.")
        return 2
    tls = None
    if args.https:
        found, problem = _certificate(args)
        if problem:
            print(problem)
            return 2
        try:
            tls = tls_context(*found)
        except (ssl.SSLError, OSError) as e:
            print(f"The certificate could not be used ({e}). Check that {found[0]} and {found[1]} are a PEM "
                  "certificate and its unencrypted private key.")
            return 2
    if network and not args.https:
        print("WARNING: other computers can reach Land Planner over plain HTTP. Passcodes, session cookies and district")
        print("         data cross the network unencrypted. Use this only on a network you fully trust.")
    keep_a_log(args.data)

    server = None
    # in network mode people are given one address, so the port does not move to the next free one
    ports = [args.port] if network or args.public_url else range(args.port, args.port + 20)
    for port in ports:
        state = already_running(port, https=args.https)
        if state:
            address = f"{'https' if args.https else 'http'}://127.0.0.1:{port}/"
            print(f"Land Planner is already running. Opening {address}")
            if not args.no_browser:
                webbrowser.open(address)
            return 0
        if state is None:
            try:
                server = make_server(LandPlanner(all_cities(), args.data), port, verbose=args.verbose, host=args.host,
                                     tls=tls, allow_plain_http=args.allow_plain_http, names=args.name,
                                     public_urls=args.public_url, max_connections=args.max_connections)
                break
            except Refused as e:
                print(e)
                return 2
            except OSError:
                continue
    if server is None:
        if len(ports) == 1:
            print(f"Land Planner could not use port {args.port}: another program is using it. Close it, or start with "
                  "--port and a different number (and give people the new address).")
        else:
            print(f"Land Planner could not find a free port between {args.port} and {args.port + 19}.")
        return 1

    port = server.server_address[1]
    scheme = "https" if tls else "http"
    local = "localhost" if tls else "127.0.0.1"      # the certificate names localhost; plain HTTP keeps the old address
    address = f"{scheme}://{local}:{port}/"
    print("Land Planner is running.")
    if network or args.public_url:
        address += "#/districts"
        shown = args.public_url or [f"{scheme}://{a}:{port}/#/districts" for a in
                                    ([args.host] if args.host not in ("0.0.0.0", "::", "") else lan_addresses())]
        if args.host in ("0.0.0.0", "::", "") and not args.public_url:
            shown.append(f"{scheme}://{socket.gethostname()}:{port}/#/districts")
        print("  Give people this address (they sign in with the name and passcode you set under Admin > Users):")
        for a in shown:
            print(f"    {a}")
        if tls and not (args.cert or args.public_url):
            print("  With this computer's own certificate their browser warns once that it is not trusted:")
            print("  they choose Advanced > Continue (see README, \"Letting others sign in from their computers\").")
        print("  This computer must stay on, awake and connected for them to reach it.")
    print(f"  Open {address} in your browser" + ("." if args.no_browser else " (it should open by itself)."))
    print("  Keep this window open while you use it. Close it to stop.")
    sys.stdout.flush()
    if not args.no_browser:
        webbrowser.open(address)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    print("Land Planner stopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
