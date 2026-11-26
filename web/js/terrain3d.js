// The 3D ground view: a small canvas renderer (far pieces drawn first), so the app needs no 3D library.
// It draws exactly the height samples it is given; nothing is smoothed or filled in.
import { num } from "./util.js";

// box: an element to fill. parcel: the parcel (centre, outline). H: the height grid from the server.
// Returns a function that removes the listeners.
export function mountTerrain(box, parcel, H) {
  box.innerHTML = `
    <canvas aria-label="3D view of the ground"></canvas>
    <div class="controls">
      <label>Height stretched <input type="range" min="1" max="12" step="1" value="5"> <b></b></label>
      <button class="btn small" type="button">Reset view</button>
      <span>Drag to turn · scroll to zoom</span>
    </div>`;
  const canvas = box.querySelector("canvas"), slider = box.querySelector("input"), sliderValue = box.querySelector("b");
  const rings = parcel.outline.coordinates;
  const ftLat = 364000, ftLon = 364000 * Math.cos(parcel.centre.lat * Math.PI / 180);
  const midLon = (H.west + H.east) / 2, midLat = (H.south + H.north) / 2;
  const known = H.feet.filter((v) => v !== null);
  const low = Math.min(...known), high = Math.max(...known);
  const toXY = (lon, lat) => [(lon - midLon) * ftLon, (lat - midLat) * ftLat];
  const at = (i, j) => H.feet[j * H.nx + i];
  const lonOf = (i) => H.west + (H.east - H.west) * i / (H.nx - 1);
  const latOf = (j) => H.south + (H.north - H.south) * j / (H.ny - 1);
  function height(lon, lat) {
    const x = Math.max(0, Math.min(H.nx - 1.001, (lon - H.west) / (H.east - H.west) * (H.nx - 1)));
    const y = Math.max(0, Math.min(H.ny - 1.001, (lat - H.south) / (H.north - H.south) * (H.ny - 1)));
    const i = Math.floor(x), j = Math.floor(y), u = x - i, v = y - j;
    const q = [at(i, j), at(i + 1, j), at(i, j + 1), at(i + 1, j + 1)].map((z) => (z === null ? low : z));
    return q[0] * (1 - u) * (1 - v) + q[1] * u * (1 - v) + q[2] * (1 - u) * v + q[3] * u * v;
  }
  function inside(lon, lat) {
    let hit = false;
    rings.forEach((r) => {
      for (let a = 0, b = r.length - 1; a < r.length; b = a++) {
        if ((r[a][1] > lat) !== (r[b][1] > lat) && lon < (r[b][0] - r[a][0]) * (lat - r[a][1]) / (r[b][1] - r[a][1]) + r[a][0]) hit = !hit;
      }
    });
    return hit;
  }
  const quads = [];
  for (let j = 0; j < H.ny - 1; j++) for (let i = 0; i < H.nx - 1; i++) {
    const corners = [[i, j], [i + 1, j], [i + 1, j + 1], [i, j + 1]];
    if (corners.some((c) => at(c[0], c[1]) === null)) continue;
    quads.push({
      p: corners.map((c) => { const xy = toXY(lonOf(c[0]), latOf(c[1])); return [xy[0], xy[1], at(c[0], c[1])]; }),
      mine: inside((lonOf(i) + lonOf(i + 1)) / 2, (latOf(j) + latOf(j + 1)) / 2),
    });
  }
  const edges = [];
  rings.forEach((r) => {
    r.slice(1).forEach((b, k) => {
      const a = r[k];
      const pieces = Math.max(1, Math.ceil(Math.hypot((b[0] - a[0]) * ftLon, (b[1] - a[1]) * ftLat) / (H.spacing_ft / 2)));
      const point = (t) => {
        const lon = a[0] + (b[0] - a[0]) * t, lat = a[1] + (b[1] - a[1]) * t, xy = toXY(lon, lat);
        return [xy[0], xy[1], height(lon, lat)];
      };
      for (let n = 0; n < pieces; n++) edges.push([point(n / pieces), point((n + 1) / pieces)]);
    });
  });
  // the lowest and highest samples inside the outline, as the server measured them
  const marks = [];
  if (H.inside) {
    [["Lowest", H.inside.low_at, H.inside.low_ft], ["Highest", H.inside.high_at, H.inside.high_ft]].forEach(([label, where, feet]) => {
      const xy = toXY(where.lon, where.lat);
      marks.push({ p: [xy[0], xy[1], feet], text: `${label} ${num(Math.round(feet))} ft` });
    });
  }

  let view = null;
  function draw() {
    const ratio = window.devicePixelRatio || 1, w = canvas.clientWidth, h = canvas.clientHeight;
    if (!w || !h) return;
    canvas.width = w * ratio; canvas.height = h * ratio;
    const g = canvas.getContext("2d");
    g.setTransform(ratio, 0, 0, ratio, 0, 0);
    const stretch = Number(slider.value);
    sliderValue.textContent = stretch + "×";
    const span = Math.hypot((H.east - H.west) * ftLon, (H.north - H.south) * ftLat);
    const scale = Math.min(w / span, h / (span * 0.68)) * 0.95 * view.zoom;
    const ct = Math.cos(view.turn), st = Math.sin(view.turn), ce = Math.cos(view.tilt), se = Math.sin(view.tilt);
    const project = (p) => {
      const x = p[0] * ct - p[1] * st, y = p[0] * st + p[1] * ct, z = (p[2] - (low + high) / 2) * stretch;
      return [w / 2 + x * scale, h / 2 - (y * se + z * ce) * scale, y * ce - z * se];
    };
    const items = quads.map((q) => {
      const s = q.p.map(project);
      return { q, s, depth: (s[0][2] + s[1][2] + s[2][2] + s[3][2]) / 4 };
    }).concat(edges.map((e) => {
      const s = e.map(project);
      return { s, depth: (s[0][2] + s[1][2]) / 2 - H.spacing_ft * 1.5 };
    })).sort((a, b) => b.depth - a.depth);
    items.forEach((it) => {
      g.beginPath();
      it.s.forEach((p, k) => g[k ? "lineTo" : "moveTo"](p[0], p[1]));
      if (!it.q) { g.strokeStyle = "#e89a00"; g.lineWidth = 3.5; g.lineCap = "round"; g.stroke(); return; }
      const p = it.q.p, t = high > low ? ((p[0][2] + p[2][2]) / 2 - low) / (high - low) : 0.5;
      const sx = (p[1][2] + p[2][2] - p[0][2] - p[3][2]) * stretch / (2 * H.spacing_ft);
      const sy = (p[2][2] + p[3][2] - p[0][2] - p[1][2]) * stretch / (2 * H.spacing_ft);
      const light = Math.max(-14, Math.min(14, (sx - sy) * 22));
      const fill = `hsl(${105 - 70 * t},${it.q.mine ? 42 : 10}%,${(it.q.mine ? 38 : 60) + 18 * t + light}%)`;
      g.closePath(); g.fillStyle = fill; g.strokeStyle = fill; g.lineWidth = 0.8; g.fill(); g.stroke();
    });
    g.font = "600 13px Segoe UI, system-ui, sans-serif"; g.textBaseline = "middle";
    marks.forEach((m) => {
      const s = project(m.p), width = g.measureText(m.text).width + 14;
      const left = Math.max(4, Math.min(w - width - 4, s[0] + 10));
      g.fillStyle = "#1d2a24"; g.beginPath(); g.arc(s[0], s[1], 5, 0, 7); g.fill();
      g.strokeStyle = "#fff"; g.lineWidth = 2; g.stroke();
      g.fillStyle = "rgba(29,42,36,.86)"; g.fillRect(left, s[1] - 11, width, 22);
      g.fillStyle = "#fff"; g.textAlign = "left"; g.fillText(m.text, left + 7, s[1]);
    });
    const tip = [-st, ct * se], len = Math.hypot(tip[0], tip[1]) || 1;
    const cx = 44, cy = 48, dx = tip[0] / len * 24, dy = -tip[1] / len * 24;
    g.strokeStyle = g.fillStyle = "#1d2a24"; g.lineWidth = 2.5;
    g.beginPath(); g.moveTo(cx - dx / 2, cy - dy / 2); g.lineTo(cx + dx / 2, cy + dy / 2); g.stroke();
    g.beginPath(); g.arc(cx + dx / 2, cy + dy / 2, 3.5, 0, 7); g.fill();
    g.font = "bold 14px Segoe UI, system-ui, sans-serif"; g.textAlign = "center";
    g.fillText("N", cx + dx, cy + dy);
  }
  function reset() { view = { turn: -0.5, tilt: 0.65, zoom: 1 }; draw(); }
  let drag = null;
  const stop = () => { drag = null; canvas.classList.remove("dragging"); };
  canvas.addEventListener("pointerdown", (e) => { drag = [e.clientX, e.clientY]; canvas.setPointerCapture(e.pointerId); canvas.classList.add("dragging"); });
  canvas.addEventListener("pointerup", stop);
  canvas.addEventListener("pointercancel", stop);
  canvas.addEventListener("pointermove", (e) => {
    if (!drag) return;
    view.turn += (e.clientX - drag[0]) * 0.008;
    view.tilt = Math.max(0.25, Math.min(1.45, view.tilt + (e.clientY - drag[1]) * 0.006));
    drag = [e.clientX, e.clientY];
    draw();
  });
  canvas.addEventListener("wheel", (e) => {
    e.preventDefault();
    view.zoom = Math.max(0.5, Math.min(4, view.zoom * (e.deltaY < 0 ? 1.1 : 1 / 1.1)));
    draw();
  }, { passive: false });
  slider.addEventListener("input", draw);
  box.querySelector("button").addEventListener("click", reset);
  const watcher = window.ResizeObserver ? new ResizeObserver(draw) : null;
  if (watcher) watcher.observe(canvas);
  window.addEventListener("resize", draw);
  reset();
  return () => { if (watcher) watcher.disconnect(); window.removeEventListener("resize", draw); };
}
