// The 3D ground view: a small canvas renderer (far pieces drawn first), so the app needs no 3D library.
// It draws exactly the height samples it is given; nothing is smoothed or filled in.
// With a plan (the optional 4th argument) the ground is coloured by the plan's pieces, the plan's streets are drawn
// on it and simple boxes stand in each piece to show the scale of what could be built. The boxes are a picture of
// scale, not a site plan.
import { num } from "./util.js";

// Building sizes in feet, by use: w along the front street, d across it, h tall (never stretched with the ground).
// many(amount): about how many such buildings the plan's homes or floor space would make.
const BUILDINGS = {
  homes: { w: 40, d: 50, h: 24, many: (a) => a.homes },
  apartments: { w: 150, d: 60, h: 38, many: (a) => (a.homes || 0) / 20 },
  retail: { w: 170, d: 110, h: 22, many: (a) => (a.sq_ft || 0) / (170 * 110) },
  office: { w: 110, d: 90, h: 48, many: (a) => (a.sq_ft || 0) / (110 * 90 * 3) },
  business: { w: 420, d: 260, h: 36, many: (a) => (a.sq_ft || 0) / (420 * 260) },
  park: { w: 26, d: 26, h: 0, tree: true, cell: 120 },
};
const MARGIN = 20;   // feet kept clear between a building and its piece's edge (the streets run along those edges)

export function insideRing(r, x, y) {
  let hit = false;
  for (let a = 0, b = r.length - 1; a < r.length; b = a++) {
    if ((r[a][1] > y) !== (r[b][1] > y) && x < (r[b][0] - r[a][0]) * (y - r[a][1]) / (r[b][1] - r[a][1]) + r[a][0]) hit = !hit;
  }
  return hit;
}
export function ringArea(r) {
  let s = 0;
  for (let a = 0, b = r.length - 1; a < r.length; b = a++) s += (r[b][0] + r[a][0]) * (r[b][1] - r[a][1]);
  return Math.abs(s) / 2;
}

// pieces: [{use, ring: [[x, y] in feet]}]. front: the unit vector toward the front street (or null).
// amounts: {use: {homes, sq_ft}} from the plan. Returns boxes [{use, x, y, w, d, h, u, v, tree}] in rows,
// each wholly inside its piece, at most `cap` of them (spaced further apart when there would be more).
export function layoutBuildings(pieces, front, amounts = {}, cap = 1500) {
  const f = front && Math.hypot(front[0], front[1]) > 0.1 ? [front[0] / Math.hypot(front[0], front[1]), front[1] / Math.hypot(front[0], front[1])] : [0, 1];
  const v = f, u = [-f[1], f[0]];
  const areaOf = {};
  pieces.forEach((p) => { p.area = ringArea(p.ring); areaOf[p.use] = (areaOf[p.use] || 0) + p.area; });
  const plans = pieces.filter((p) => BUILDINGS[p.use] && p.ring.length >= 3 && p.area > 0).map((p) => {
    const b = BUILDINGS[p.use];
    let cu, cv;
    if (b.tree) { cu = cv = b.cell; } else {
      const wanted = amounts[p.use] ? b.many(amounts[p.use]) * p.area / areaOf[p.use] : 0;
      const each = wanted >= 1 ? p.area * 0.8 / wanted : (b.w * 2.2) * (b.d * 2.2);
      // the gap g around each building so that (w + g) * (d + g) is the room each one has
      let g = (-(b.w + b.d) + Math.sqrt((b.w - b.d) ** 2 + 4 * each)) / 2;
      g = Math.max(g, Math.max(15, 0.25 * Math.min(b.w, b.d)));
      cu = b.w + g; cv = b.d + g;
    }
    return { p, b, cu, cv };
  });
  const guess = (q) => q.p.area / (q.cu * q.cv);
  for (let n = 0; n < 200 && plans.reduce((t, q) => t + guess(q), 0) > cap; n++) {
    const most = plans.reduce((a, q) => (guess(q) > guess(a) ? q : a), plans[0]);
    most.cu *= 1.1; most.cv *= 1.1;
  }
  const boxes = [];
  plans.forEach(({ p, b, cu, cv }) => {
    const along = p.ring.map((pt) => pt[0] * u[0] + pt[1] * u[1]), across = p.ring.map((pt) => pt[0] * v[0] + pt[1] * v[1]);
    const u0 = Math.min(...along), u1 = Math.max(...along), v0 = Math.min(...across), v1 = Math.max(...across);
    const su = u0 + ((u1 - u0) % cu) / 2 + cu / 2, sv = v0 + ((v1 - v0) % cv) / 2 + cv / 2;
    const hw = b.w / 2 + MARGIN, hd = b.d / 2 + MARGIN;
    for (let a = su; a < u1; a += cu) {
      for (let c = sv; c < v1; c += cv) {
        if (boxes.length >= cap) return;
        const x = a * u[0] + c * v[0], y = a * u[1] + c * v[1];
        const corners = [[-hw, -hd], [hw, -hd], [hw, hd], [-hw, hd], [0, 0]];
        if (!corners.every(([du, dv]) => insideRing(p.ring, x + du * u[0] + dv * v[0], y + du * u[1] + dv * v[1]))) continue;
        boxes.push({ use: p.use, x, y, w: b.w, d: b.d, h: b.h, u, v, tree: !!b.tree });
      }
    }
  });
  return boxes;
}

function rgb(hex) {
  const m = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(String(hex || ""));
  return m ? [parseInt(m[1], 16), parseInt(m[2], 16), parseInt(m[3], 16)] : [150, 150, 150];
}
const mix = (a, b, t) => a.map((x, i) => Math.round(x + (b[i] - x) * t));
const css = (c, k = 1) => `rgb(${c.map((x) => Math.max(0, Math.min(255, Math.round(x * k)))).join(",")})`;

// box: an element to fill. parcel: the parcel (centre, outline). H: the height grid from the server.
// plan (optional): {pieces: [{use, ring: [[lon, lat]...]}], streets: [[[lon, lat], [lon, lat]]], colours: {use: "#hex"},
//   front: [x, y] (toward the front street, feet east and north), amounts: {use: {homes, sq_ft}}, cap: 1500,
//   view: {turn, tilt, zoom, stretch} to start from (what getView gave)}.
// Returns a function that removes the listeners; its getView() says where the camera is now.
export function mountTerrain(box, parcel, H, plan = null) {
  box.innerHTML = `
    <canvas aria-label="${plan ? "3D view of the ground with the plan drawn on it" : "3D view of the ground"}"></canvas>
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
  const heightXY = (x, y) => height(midLon + x / ftLon, midLat + y / ftLat);
  function inside(lon, lat) {
    let hit = false;
    rings.forEach((r) => {
      for (let a = 0, b = r.length - 1; a < r.length; b = a++) {
        if ((r[a][1] > lat) !== (r[b][1] > lat) && lon < (r[b][0] - r[a][0]) * (lat - r[a][1]) / (r[b][1] - r[a][1]) + r[a][0]) hit = !hit;
      }
    });
    return hit;
  }

  // the plan's pieces in feet, with their colours
  const pieces = plan && plan.pieces ? plan.pieces.filter((p) => p.ring && p.ring.length >= 3).map((p) => ({
    use: p.use, ring: p.ring.map((q) => toXY(q[0], q[1])), colour: rgb((plan.colours || {})[p.use] || p.colour),
  })) : [];
  const pieceAt = (x, y) => pieces.findIndex((p) => insideRing(p.ring, x, y));

  const quads = [];
  for (let j = 0; j < H.ny - 1; j++) for (let i = 0; i < H.nx - 1; i++) {
    const corners = [[i, j], [i + 1, j], [i + 1, j + 1], [i, j + 1]];
    if (corners.some((c) => at(c[0], c[1]) === null)) continue;
    const mLon = (lonOf(i) + lonOf(i + 1)) / 2, mLat = (latOf(j) + latOf(j + 1)) / 2;
    const quad = {
      p: corners.map((c) => { const xy = toXY(lonOf(c[0]), latOf(c[1])); return [xy[0], xy[1], at(c[0], c[1])]; }),
      mine: inside(mLon, mLat),
    };
    if (pieces.length) { const xy = toXY(mLon, mLat), k = pieceAt(xy[0], xy[1]); if (k >= 0) quad.piece = pieces[k]; }
    quads.push(quad);
  }
  // a line laid on the ground, cut into short pieces so it follows the heights
  function onGround(a, b) {
    const out = [];
    const pieces = Math.max(1, Math.ceil(Math.hypot((b[0] - a[0]) * ftLon, (b[1] - a[1]) * ftLat) / (H.spacing_ft / 2)));
    const point = (t) => {
      const lon = a[0] + (b[0] - a[0]) * t, lat = a[1] + (b[1] - a[1]) * t, xy = toXY(lon, lat);
      return [xy[0], xy[1], height(lon, lat)];
    };
    for (let n = 0; n < pieces; n++) out.push([point(n / pieces), point((n + 1) / pieces)]);
    return out;
  }
  const edges = [];
  rings.forEach((r) => { r.slice(1).forEach((b, k) => { edges.push(...onGround(r[k], b)); }); });
  const roads = [];
  if (plan && plan.streets) plan.streets.forEach((line) => { line.slice(1).forEach((b, k) => roads.push(...onGround(line[k], b))); });

  // the boxes: standing on the lowest ground under them, so none floats
  const boxes = pieces.length ? layoutBuildings(pieces.map((p) => ({ use: p.use, ring: p.ring })), plan.front, plan.amounts || {}, plan.cap || 1500).map((b) => {
    const colour = pieces.find((p) => p.use === b.use).colour;
    if (b.tree) return { ...b, base: heightXY(b.x, b.y) };
    const hu = [b.u[0] * b.w / 2, b.u[1] * b.w / 2], hv = [b.v[0] * b.d / 2, b.v[1] * b.d / 2];
    const foot = [[-1, -1], [1, -1], [1, 1], [-1, 1]].map(([s, t]) => [b.x + s * hu[0] + t * hv[0], b.y + s * hu[1] + t * hv[1]]);
    const base = Math.min(...foot.map((q) => heightXY(q[0], q[1])));
    // outward normals of the four sides, in the same order as the sides foot[k] to foot[k + 1]
    const normals = [[-b.v[0], -b.v[1]], [b.u[0], b.u[1]], [b.v[0], b.v[1]], [-b.u[0], -b.u[1]]];
    return { ...b, base, foot, normals, paint: mix(colour, [255, 255, 255], 0.5) };
  }) : [];

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
    // p: [x, y, ground height, feet above the ground]; only the ground height is stretched
    const project = (p) => {
      const x = p[0] * ct - p[1] * st, y = p[0] * st + p[1] * ct, z = (p[2] - (low + high) / 2) * stretch + (p[3] || 0);
      return [w / 2 + x * scale, h / 2 - (y * se + z * ce) * scale, y * ce - z * se];
    };
    const lines = (list, kind, lift) => list.map((e) => {
      const s = e.map(project);
      return { s, kind, depth: (s[0][2] + s[1][2]) / 2 - H.spacing_ft * lift };
    });
    let items = quads.map((q) => {
      const s = q.p.map(project);
      return { q, s, depth: (s[0][2] + s[1][2] + s[2][2] + s[3][2]) / 4 };
    }).concat(lines(edges, "edge", 1.5));
    if (roads.length) items = items.concat(lines(roads, "road", 0.75));
    if (boxes.length) {
      // a box is drawn after the ground under it: its depth is that of its nearest foot corner, brought forward a little
      items = items.concat(boxes.map((b) => {
        if (b.tree) { const s = project([b.x, b.y, b.base, 14]); return { b, s, depth: s[2] - H.spacing_ft * 0.8 }; }
        const bottom = b.foot.map((q) => project([q[0], q[1], b.base, 0])), top = b.foot.map((q) => project([q[0], q[1], b.base, b.h]));
        return { b, bottom, top, depth: Math.min(...bottom.map((s) => s[2])) - H.spacing_ft * 0.8 };
      }));
    }
    items.sort((a, b) => b.depth - a.depth);
    const roadWidth = Math.max(2, Math.min(12, 44 * scale));
    items.forEach((it) => {
      if (it.b) { drawBox(g, it, st, ct, scale); return; }
      g.beginPath();
      it.s.forEach((p, k) => g[k ? "lineTo" : "moveTo"](p[0], p[1]));
      if (it.kind === "edge") { g.strokeStyle = "#e89a00"; g.lineWidth = 3.5; g.lineCap = "round"; g.stroke(); return; }
      if (it.kind === "road") { g.strokeStyle = "#f4f1e8"; g.lineWidth = roadWidth; g.lineCap = "round"; g.stroke(); return; }
      const p = it.q.p, t = high > low ? ((p[0][2] + p[2][2]) / 2 - low) / (high - low) : 0.5;
      const sx = (p[1][2] + p[2][2] - p[0][2] - p[3][2]) * stretch / (2 * H.spacing_ft);
      const sy = (p[2][2] + p[3][2] - p[0][2] - p[1][2]) * stretch / (2 * H.spacing_ft);
      const light = Math.max(-14, Math.min(14, (sx - sy) * 22));
      const fill = it.q.piece
        ? css(mix(it.q.piece.colour, [96, 110, 84], 0.35), 0.9 + light / 60 + 0.08 * t)
        : `hsl(${105 - 70 * t},${it.q.mine ? 42 : 10}%,${(it.q.mine ? 38 : 60) + 18 * t + light}%)`;
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
  const start = plan && plan.view;
  if (start && Number.isFinite(start.turn)) {
    // a plan redrawn after a change keeps the camera where the person left it
    view = { turn: start.turn, tilt: start.tilt, zoom: start.zoom };
    if (start.stretch) slider.value = String(start.stretch);
    draw();
  } else reset();
  const unmount = () => { if (watcher) watcher.disconnect(); window.removeEventListener("resize", draw); };
  unmount.getView = () => ({ ...view, stretch: Number(slider.value) });
  return unmount;
}

// One box: the sides that face the viewer, then the roof. A tree is a dark green dot.
function drawBox(g, it, st, ct, scale) {
  const b = it.b;
  if (b.tree) {
    g.beginPath(); g.arc(it.s[0], it.s[1], Math.max(1.5, b.w / 2 * scale), 0, 7);
    g.fillStyle = "#2f6b3f"; g.fill(); g.strokeStyle = "rgba(0,0,0,.3)"; g.lineWidth = 0.6; g.stroke();
    return;
  }
  g.lineWidth = 0.7; g.strokeStyle = "rgba(20,28,24,.55)"; g.lineJoin = "round";
  for (let k = 0; k < 4; k++) {
    const n = b.normals[k];
    if (n[0] * st + n[1] * ct >= 0) continue;            // facing away from the viewer
    const m = (k + 1) % 4, shade = 0.68 + 0.18 * (n[0] * -0.6 + n[1] * 0.8);   // light from the north-west
    g.beginPath();
    g.moveTo(it.bottom[k][0], it.bottom[k][1]); g.lineTo(it.bottom[m][0], it.bottom[m][1]);
    g.lineTo(it.top[m][0], it.top[m][1]); g.lineTo(it.top[k][0], it.top[k][1]); g.closePath();
    g.fillStyle = css(b.paint, shade); g.fill(); g.stroke();
  }
  g.beginPath();
  it.top.forEach((p, k) => g[k ? "lineTo" : "moveTo"](p[0], p[1]));
  g.closePath(); g.fillStyle = css(b.paint); g.fill(); g.stroke();
}
