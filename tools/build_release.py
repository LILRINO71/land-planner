"""Build the download people install: dist/LandPlanner.zip. Standard library only.

    python tools/build_release.py --runtime <folder> [--version v2.0.0]

<folder> is an unpacked copy of python.org's "Windows embeddable package" (the release workflow downloads it and
checks its signature). The zip holds one folder, LandPlanner, with the app, that Python in runtime/, a starter
.bat and an icon, so the app runs on a Windows computer that has no Python installed.
"""
import argparse
import shutil
import struct
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEEP = ("landplanner", "web", "tools/menifee.py", "Start Land Planner.bat", "README.md")
SKIP = ("__pycache__", ".pyc")


def icon(path, size=48):
    """A small icon in the app's colours (gold tile, green field shape), written by hand as a 32-bit .ico."""
    gold, green, clear = (0x32, 0xB6, 0xF2, 0xFF), (0x36, 0x44, 0x1F, 0xFF), (0, 0, 0, 0)   # blue, green, red, alpha
    shape = [(0.22, 0.70), (0.38, 0.28), (0.60, 0.39), (0.78, 0.31), (0.70, 0.74), (0.45, 0.66)]

    def inside(x, y):
        hit = False
        for (ax, ay), (bx, by) in zip(shape, shape[1:] + shape[:1]):
            if (ay > y) != (by > y) and x < (bx - ax) * (y - ay) / (by - ay) + ax:
                hit = not hit
        return hit

    def near_edge(x, y, width=0.045):
        for (ax, ay), (bx, by) in zip(shape, shape[1:] + shape[:1]):
            dx, dy = bx - ax, by - ay
            t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy)))
            if ((x - ax - dx * t) ** 2 + (y - ay - dy * t) ** 2) ** 0.5 <= width:
                return True
        return False

    rows = []
    radius = 0.2
    for j in range(size):
        row = b""
        for i in range(size):
            x, y = (i + 0.5) / size, (j + 0.5) / size
            cx, cy = min(max(x, radius), 1 - radius), min(max(y, radius), 1 - radius)
            if (x - cx) ** 2 + (y - cy) ** 2 > radius ** 2:
                colour = clear                       # outside the tile's rounded corners
            elif near_edge(x, y):
                colour = green
            else:
                colour = gold
            row += bytes(colour)
        rows.append(row)
    pixels = b"".join(reversed(rows))                # bitmaps are stored bottom row first
    mask = b"\x00" * (((size + 31) // 32) * 4 * size)
    header = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0, len(pixels) + len(mask), 0, 0, 0, 0)
    image = header + pixels + mask
    path.write_bytes(struct.pack("<HHH", 0, 1, 1) + struct.pack("<BBBBHHII", size, size, 0, 0, 1, 32, len(image), 22) + image)


def build(runtime, version, out):
    runtime = Path(runtime)
    if not (runtime / "python.exe").is_file():
        sys.exit(f"{runtime} does not hold python.exe: give the unpacked Windows embeddable package")
    app = out / "LandPlanner"
    if out.exists():
        shutil.rmtree(out)
    app.mkdir(parents=True)
    for name in KEEP:
        source, target = ROOT / name, app / name
        if source.is_dir():
            shutil.copytree(source, target, ignore=shutil.ignore_patterns(*["*" + s if s.startswith(".") else s for s in SKIP]))
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    shutil.copytree(runtime, app / "runtime")
    # The embeddable Python only looks where this file says: its own library, its folder, and the app's folder.
    for pth in (app / "runtime").glob("python*._pth"):
        library = pth.name.replace("._pth", ".zip")
        pth.write_text(f"{library}\n.\n..\n", encoding="ascii")
    (app / "VERSION.txt").write_text(f"Land Planner {version}\n", encoding="utf-8")
    icon(app / "landplanner.ico")
    archive = out / "LandPlanner.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for path in sorted(app.rglob("*")):
            if path.is_file():
                z.write(path, Path("LandPlanner") / path.relative_to(app))
    (out / "RELEASE_NOTES.md").write_text(
        f"## Install on Windows\n\n"
        f"1. Download **Install-Land-Planner.bat** below and double-click it.\n"
        f"2. If Windows shows \"Windows protected your PC\", click **More info**, then **Run anyway** "
        f"(the file is not signed by a company; it is the short script you can read in this repository).\n\n"
        f"It installs to your own user folder (no administrator rights, no Python needed), adds **Land Planner** to the "
        f"Desktop and Start menu, and opens the app in your browser. Run it again any time to update; your saved lands "
        f"and plans are kept.\n\n"
        f"Or paste this into PowerShell:\n\n"
        f"```powershell\nirm https://raw.githubusercontent.com/LILRINO71/land-planner/main/install.ps1 | iex\n```\n\n"
        f"`LandPlanner.zip` is the same app as a plain folder: unzip it anywhere and double-click `Start Land Planner.bat`.\n",
        encoding="utf-8")
    return archive


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build dist/LandPlanner.zip")
    ap.add_argument("--runtime", required=True, help="unpacked Windows embeddable Python")
    ap.add_argument("--version", default="dev")
    ap.add_argument("--out", default=str(ROOT / "dist"))
    args = ap.parse_args(argv)
    archive = build(args.runtime, args.version, Path(args.out))
    print(f"{archive}  {archive.stat().st_size / 1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
