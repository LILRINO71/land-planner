"""Start Land Planner:  python -m landplanner   (or double-click "Start Land Planner.bat")

    --port 8777       the port to try first
    --no-browser      do not open the browser
    --data FOLDER     where My lands and the saved answers are kept (default: the data folder beside the app)
    --verbose         print every request
"""
import argparse
import json
import logging
import logging.handlers
import socket
import sys
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

from . import APP
from .cities import all_cities
from .planner import LandPlanner
from .server import make_server

ROOT = Path(__file__).resolve().parent.parent
PORT = 8777


def already_running(port):
    """True when Land Planner itself is answering on the port, False when something else is, None when it is free."""
    with socket.socket() as s:
        s.settimeout(0.5)
        if s.connect_ex(("127.0.0.1", port)) != 0:
            return None
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2) as r:  # noqa: S310 - this computer
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


def main(argv=None):
    ap = argparse.ArgumentParser(prog="landplanner", description="Land Planner, on this computer only.")
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--data", default=str(ROOT / "data"))
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)
    keep_a_log(args.data)

    server = None
    for port in range(args.port, args.port + 20):
        state = already_running(port)
        if state:
            address = f"http://127.0.0.1:{port}/"
            print(f"Land Planner is already running. Opening {address}")
            if not args.no_browser:
                webbrowser.open(address)
            return 0
        if state is None:
            try:
                server = make_server(LandPlanner(all_cities(), args.data), port, verbose=args.verbose)
                break
            except OSError:
                continue
    if server is None:
        print(f"Land Planner could not find a free port between {args.port} and {args.port + 19}.")
        return 1

    address = f"http://127.0.0.1:{server.server_address[1]}/"
    print("Land Planner is running.")
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
