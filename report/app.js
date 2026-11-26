// Draws the report from window.SITE (data.js). No parcel value is typed in here: missing data reads "not covered yet".
(function () {
  "use strict";
  var S = window.SITE;
  var $ = function (id) { return document.getElementById(id); };
  var NONE = "not covered yet";
  var missing = '<p class="missing">Not covered yet.</p>';
  if (!S || !S.parcel) {
    $("subtitle").textContent = "data.js is missing. Run: python tools/build_report.py <parcel number>";
    return;
  }
  var P = S.parcel, names = S.zone_names || {};

  function esc(v) {
    return String(v).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; });
  }
  function has(v) { return v !== null && v !== undefined && v !== ""; }
  function show(v, suffix) { return has(v) ? esc(v) + (suffix || "") : NONE; }
  function num(v) { return has(v) && !isNaN(Number(v)) ? Number(v).toLocaleString("en-US") : NONE; }
  function money(v) { return has(v) ? "$" + num(v) : NONE; }
  function table(head, rows) {
    return '<div class="scroll"><table><thead><tr>' + head.map(function (h) { return "<th>" + h + "</th>"; }).join("") +
      "</tr></thead><tbody>" + rows.map(function (r) {
        return "<tr>" + r.map(function (c, i) { return "<td" + (i && /^[\d,.%]+$/.test(c) ? ' class="num"' : "") + ">" + c + "</td>"; }).join("") + "</tr>";
      }).join("") + "</tbody></table></div>";
  }
  function zoneName(code) {
    if (code === "Specific Plan") return "Area with its own city-approved specific plan";
    if (code === "(none)") return "No zoning listed";
    return String(code).split(" & ").map(function (c) { return names[c] || c; }).join(" + ");
  }
  // one list of zoning families drives the map colours and the legend
  var FAMILIES = [
    [/&/, "#b59a7a", "More than one zone"], [/^EDC/, "#e0662f", "Economic Development Corridor"],
    [/^(HDR|MDR|LMDR)/, "#c9852b", "Denser housing"], [/^LDR/, "#f4d35e", "Low density housing"],
    [/^(RR|RM)/, "#c8d98a", "Rural residential"], [/^OS/, "#3f9d68", "Open space"], [/^(CR|CO)/, "#d9455f", "Commercial"],
    [/^(BP|HI)/, "#8a6bbd", "Business park / industrial"], [/^Specific/, "#4aa3c7", "Specific plan"], [/./, "#9aa0a6", "Other"]];
  function family(code) { return FAMILIES.filter(function (f) { return f[0].test(String(code)); })[0] || FAMILIES[FAMILIES.length - 1]; }
  function colour(code) { return family(code)[1]; }

  // ---- header and headline numbers
  var number = P.apn_formatted || P.apn;
  document.title = "Site report - parcel " + number;
  $("title").textContent = (has(P.acres) ? P.acres + " acres" : "Parcel") + " · parcel " + number;
  $("subtitle").textContent = (P.address ? P.address + " · " : "No street address listed · ") + "Data fetched " + S.fetched;
  if (S.example) {
    $("banner").hidden = false;
    $("banner").textContent = "Example parcel. " + number + " is a placeholder until the real parcel number is known.";
  }
  var T = S.terrain, traffic = S.state_highway_traffic, near = traffic && traffic.stations[0];
  function busiest(s) {
    var v = [s.vehicles_per_day_behind, s.vehicles_per_day_ahead].filter(has).map(Number).filter(function (n) { return !isNaN(n); });
    if (!v.length) return NONE;
    var lo = Math.min.apply(null, v), hi = Math.max.apply(null, v);
    return lo === hi ? num(hi) : num(lo) + "–" + num(hi);
  }
  $("headline").innerHTML = [
    [show(P.acres, " acres"), P.size_feet ? "about " + num(P.size_feet.east_west) + " ft east–west by " + num(P.size_feet.north_south) + " ft north–south" : "size"],
    [show(P.zoning), "zoning: " + (S.zoning ? esc(S.zoning.what_it_allows) : NONE)],
    [T ? esc(T.reading.charAt(0).toUpperCase() + T.reading.slice(1)) : NONE, T ? "about " + T.rough_slope_pct + "% slope, " + T.fall_across_site_ft + " ft of fall" : "slope"],
    [near ? busiest(near) : NONE, near ? "vehicles a day, route " + esc(near.route) + " at " + esc(near.where) + ", " + near.miles_away + " mi away" : "highway traffic"]
  ].map(function (s) { return '<div class="stat"><b>' + s[0] + "</b><span>" + s[1] + "</span></div>"; }).join("");

  // ---- map
  var ll = function (rings) { return rings.map(function (r) { return r.map(function (p) { return [p[1], p[0]]; }); }); };
  var map = L.map("map", { scrollWheelZoom: false, preferCanvas: true });
  L.tileLayer("https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer/tile/{z}/{y}/{x}",
    { maxNativeZoom: 16, maxZoom: 18, attribution: "Imagery: USGS The National Map" }).addTo(map);
  var shown = {};
  (S.neighbour_shapes || []).forEach(function (n) {
    if (n.apn === P.apn) return;
    shown[family(n.zoning)[2]] = colour(n.zoning);
    L.polygon(ll(n.rings), { color: "#fff", weight: 0.6, fillColor: colour(n.zoning), fillOpacity: 0.4 })
      .bindTooltip(esc(n.zoning) + " · " + esc(zoneName(n.zoning)) + (has(n.acres) ? " · " + n.acres + " ac" : ""), { sticky: true })
      .addTo(map);
  });
  L.polygon(ll(P.outline.coordinates), { color: "#1d2a24", weight: 7, fill: false, interactive: false }).addTo(map);
  var site = L.polygon(ll(P.outline.coordinates), { color: "#f2b632", weight: 4, fillColor: "#f2b632", fillOpacity: 0.12 })
    .bindTooltip("This parcel · " + esc(number), { sticky: true }).addTo(map);
  (traffic ? traffic.stations : []).forEach(function (s) {
    if (!has(s.lat)) return;
    L.circleMarker([s.lat, s.lon], { radius: 8, color: "#fff", weight: 2, fillColor: "#1f4436", fillOpacity: 1 })
      .bindTooltip("Route " + esc(s.route) + " at " + esc(s.where) + ": " + busiest(s) + " vehicles a day").addTo(map);
  });
  var wide = site.getBounds().pad(0.9);
  if (near && has(near.lat)) wide.extend([near.lat, near.lon]);
  map.fitBounds(wide);
  // A page opened in a background tab starts with a map of no size, and Leaflet then shows the whole world:
  // fit again whenever the map's box changes size.
  if (window.ResizeObserver) new ResizeObserver(function () { map.invalidateSize(); map.fitBounds(wide); }).observe($("map"));
  L.control.scale({ metric: false }).addTo(map);
  $("legend").innerHTML = Object.keys(shown).map(function (k) { return '<span><i style="background:' + shown[k] + '"></i>' + k + "</span>"; }).join("") ||
    '<span class="missing">Neighbouring parcels: not covered yet.</span>';

  // ---- zoning and general plan in plain words
  var Z = S.zoning, G = S.general_plan, html = "";
  if (Z) {
    html += "<h3>Zoning today: " + esc(Z.abbrev || Z.zone) + "</h3><p>The city calls this zone <b>" + esc(Z.what_it_allows) +
      "</b>. Zoning is the rulebook for what may be built on the land now.</p>";
  } else html += "<h3>Zoning</h3>" + missing;
  if (G) {
    html += "<h3>General plan: " + esc(G.label || G.land_use) + "</h3><p>The city's long-range plan marks this land as <b>" +
      esc(G.description) + "</b>" + (G.specific_plan ? ", inside the " + esc(G.specific_plan) + " specific plan" : "") +
      ". The general plan is the city's picture of what this area should become.</p>";
  } else html += "<h3>General plan</h3>" + missing;
  if (Z && (Z.abbrev || Z.zone) === "EDC-CC") {
    html += "<h3>What the city has in mind for the Community Core</h3><blockquote>“The Community Core is envisioned as the City’s primary activity center and gathering place. Civic and entertainment uses are envisioned here that are complemented with commercial retail uses and higher density housing options that encourage walkability and reduce the use of the automobile.”</blockquote>" +
      '<p class="fine">City development code wording, read from a <a href="https://www.zoneomics.com/code/menifee-CA/chapter_4">third-party copy</a>; confirm against the city’s own.</p>' +
      "<p><b>In plain words:</b> the city pictures this area as a kind of downtown: public and entertainment places, shops and closer-packed homes that people can walk between.</p>";
  }
  html += '<p class="fine">Which uses are allowed outright, need a permit or are banned: ' + NONE + '. See the <a href="https://online.encodeplus.com/regs/menifee-ca/doc-viewer.aspx?secid=1320">city development code</a>.</p>';
  $("zoning").innerHTML = html;

  // ---- facts
  $("facts").innerHTML = "<dl>" + [
    ["Parcel number", esc(number)], ["Size", show(P.acres, " acres")],
    ["Extent", P.size_feet ? num(P.size_feet.east_west) + " × " + num(P.size_feet.north_south) + " ft (E–W × N–S)" : NONE],
    ["Assessor class", show(P.assessor_class)],
    ["Buildings", P.looks_vacant ? "None assessed; appears vacant" : "Assessor records suggest it is not vacant"],
    ["Assessed land value", money(P.assessed_land_usd)], ["Assessed structures", money(P.assessed_structures_usd)],
    ["Fire hazard zone", show(P.fire_hazard_zone)], ["Council district", show(P.council_district)],
    ["Centre point", P.centre.lat.toFixed(5) + ", " + P.centre.lon.toFixed(5)]
  ].map(function (r) { return "<dt>" + r[0] + "</dt><dd>" + r[1] + "</dd>"; }).join("") +
    '</dl><p class="fine">Assessed values are for property tax. They are not market prices.</p>';

  // ---- surroundings
  var A = S.surroundings;
  if (A) {
    var listed = A.by_zoning.reduce(function (t, r) { return t + r.acres; }, 0), rest = A.total_acres - listed;
    var rows = A.by_zoning.map(function (r) {
      return ['<span class="swatch" style="background:' + colour(r.zoning) + '"></span>' + esc(r.zoning), esc(zoneName(r.zoning)),
        num(r.acres), num(r.parcels), r.share_pct + "%"];
    });
    if (rest > 0.5) rows.push(["Other", "Smaller zoning groups", num(Math.round(rest * 10) / 10), "—", "—"]);
    $("around").innerHTML = "<p>Parcels within <b>" + A.within_miles + " mile</b> of the centre, by zoning: " + num(A.total_acres) +
      " acres in all.</p>" + table(["Code", "Meaning", "Acres", "Parcels", "Share"], rows) +
      '<p class="fine">Includes this parcel. A parcel the circle only touches is counted whole. Roads and other land outside parcels are not counted. This is zoning, not what is built there today.</p>';
  } else $("around").innerHTML = missing;

  // ---- traffic
  if (traffic && traffic.stations.length) {
    $("traffic").innerHTML = table(["Count point", "Miles away", "Vehicles a day, “back” side", "Vehicles a day, “ahead” side", "Peak hour, “ahead”"],
      traffic.stations.map(function (s) {
        return ["Route " + esc(s.route) + " at " + esc(s.where), String(s.miles_away), num(s.vehicles_per_day_behind), num(s.vehicles_per_day_ahead), num(s.peak_hour_ahead)];
      })) + '<p class="fine">Caltrans annual average daily traffic. “Back” and “ahead” are the stretches of highway on either side of the count point. Distances are straight lines from the parcel centre, not driving distances. City street traffic: ' + NONE + ".</p>";
  } else $("traffic").innerHTML = traffic ? "<p>No state highway count point within " + traffic.within_miles + " miles.</p>" : missing;

  // ---- slope
  if (T) {
    var f = T.feet_above_sea_level;
    $("slope").innerHTML = "<p><b>Slope: " + esc(T.reading) + "</b>, about " + T.rough_slope_pct + "%. There are " + T.fall_across_site_ft +
      " ft between the highest and lowest of the five points below. It is a rough figure from those points only.</p>" +
      table(["Point", "Feet above sea level"], Object.keys(f).map(function (k) {
        return [k === "centre" ? "Centre" : k.charAt(0).toUpperCase() + k.slice(1) + "-most corner of the outline", num(f[k])];
      }));
  } else $("slope").innerHTML = missing;

  // ---- not covered, sources
  $("missing").innerHTML = (S.not_included || []).concat(["which uses the zone permits", "who the likely buyers are, costs and returns"])
    .map(function (m) { return "<li>" + esc(m.charAt(0).toUpperCase() + m.slice(1)) + "</li>"; }).join("");
  var from = [["parcel", "Parcel outline and facts", "City of Menifee public GIS"], ["zoning", "Zoning", "City of Menifee public GIS"],
    ["general_plan", "General plan", "City of Menifee public GIS"], ["surroundings", "Surroundings", "City of Menifee public GIS"],
    ["neighbour_shapes", "Neighbouring outlines", "City of Menifee public GIS"], ["zone_names", "Zoning code names", "City of Menifee public GIS"],
    ["terrain", "Five slope points", "U.S. Geological Survey elevation point service"], ["surface", "3D ground heights", "U.S. Geological Survey 3DEP"],
    ["state_highway_traffic", "Highway traffic", "Caltrans traffic counts"]];
  $("sources").innerHTML = table(["What", "Source", "Answered on " + esc(S.fetched)], from.map(function (r) {
    var state = S.sources[r[0]] || NONE;
    return [r[1], r[2], esc(state === "ok" ? "yes" : state)];
  }));

  // ---- 3D view: a small canvas renderer (far pieces drawn first), so the page needs no 3D library
  var H = S.surface, canvas = $("terrain");
  if (!H) {
    canvas.parentNode.hidden = true;
    $("terrainNote").textContent = "3D view: not covered yet (the elevation grid did not answer).";
    return;
  }
  var ftLat = 364000, ftLon = 364000 * Math.cos(P.centre.lat * Math.PI / 180);
  var midLon = (H.west + H.east) / 2, midLat = (H.south + H.north) / 2;
  var known = H.feet.filter(function (v) { return v !== null; });
  var low = Math.min.apply(null, known), high = Math.max.apply(null, known);
  var toXY = function (lon, lat) { return [(lon - midLon) * ftLon, (lat - midLat) * ftLat]; };
  var at = function (i, j) { return H.feet[j * H.nx + i]; };
  var lonOf = function (i) { return H.west + (H.east - H.west) * i / (H.nx - 1); };
  var latOf = function (j) { return H.south + (H.north - H.south) * j / (H.ny - 1); };
  function height(lon, lat) {
    var x = Math.max(0, Math.min(H.nx - 1.001, (lon - H.west) / (H.east - H.west) * (H.nx - 1)));
    var y = Math.max(0, Math.min(H.ny - 1.001, (lat - H.south) / (H.north - H.south) * (H.ny - 1)));
    var i = Math.floor(x), j = Math.floor(y), u = x - i, v = y - j;
    var q = [at(i, j), at(i + 1, j), at(i, j + 1), at(i + 1, j + 1)].map(function (z) { return z === null ? low : z; });
    return q[0] * (1 - u) * (1 - v) + q[1] * u * (1 - v) + q[2] * (1 - u) * v + q[3] * u * v;
  }
  function inside(lon, lat) {
    var hit = false;
    P.outline.coordinates.forEach(function (r) {
      for (var a = 0, b = r.length - 1; a < r.length; b = a++) {
        if ((r[a][1] > lat) !== (r[b][1] > lat) && lon < (r[b][0] - r[a][0]) * (lat - r[a][1]) / (r[b][1] - r[a][1]) + r[a][0]) hit = !hit;
      }
    });
    return hit;
  }
  var quads = [], insideHeights = [];
  for (var j = 0; j < H.ny; j++) for (var i = 0; i < H.nx; i++) {
    if (at(i, j) !== null && inside(lonOf(i), latOf(j))) insideHeights.push(at(i, j));
    if (i === H.nx - 1 || j === H.ny - 1) continue;
    var corners = [[i, j], [i + 1, j], [i + 1, j + 1], [i, j + 1]];
    if (corners.some(function (c) { return at(c[0], c[1]) === null; })) continue;
    quads.push({
      p: corners.map(function (c) { var xy = toXY(lonOf(c[0]), latOf(c[1])); return [xy[0], xy[1], at(c[0], c[1])]; }),
      mine: inside((lonOf(i) + lonOf(i + 1)) / 2, (latOf(j) + latOf(j + 1)) / 2)
    });
  }
  var edges = [];
  P.outline.coordinates.forEach(function (r) {
    r.slice(1).forEach(function (b, k) {
      var a = r[k];
      var pieces = Math.max(1, Math.ceil(Math.hypot((b[0] - a[0]) * ftLon, (b[1] - a[1]) * ftLat) / (H.spacing_ft / 2)));
      var point = function (t) {
        var lon = a[0] + (b[0] - a[0]) * t, lat = a[1] + (b[1] - a[1]) * t, xy = toXY(lon, lat);
        return [xy[0], xy[1], height(lon, lat)];
      };
      for (var n = 0; n < pieces; n++) edges.push([point(n / pieces), point((n + 1) / pieces)]);
    });
  });
  var inLow = Math.min.apply(null, insideHeights), inHigh = Math.max.apply(null, insideHeights);
  $("terrainNote").textContent = "Approximate ground surface from " + num(known.length) + " USGS 3DEP heights, one about every " + H.spacing_ft +
    " ft. Ditches, mounds and anything smaller than that can be missed. The samples inside the outline run from " + num(Math.round(inLow)) +
    " to " + num(Math.round(inHigh)) + " ft above sea level (a range of " + num(Math.round(inHigh - inLow)) +
    " ft). Heights are stretched so gentle slopes can be seen. Gold line: parcel outline. Paler ground: outside the parcel. N: north.";

  var view;
  function draw() {
    var ratio = window.devicePixelRatio || 1, w = canvas.clientWidth, h = canvas.clientHeight;
    canvas.width = w * ratio; canvas.height = h * ratio;
    var g = canvas.getContext("2d");
    g.setTransform(ratio, 0, 0, ratio, 0, 0);
    var stretch = Number($("stretch").value);
    $("stretchValue").textContent = stretch + "×";
    var span = Math.hypot((H.east - H.west) * ftLon, (H.north - H.south) * ftLat);
    var scale = Math.min(w / span, h / (span * 0.68)) * 0.95 * view.zoom;
    var ct = Math.cos(view.turn), st = Math.sin(view.turn), ce = Math.cos(view.tilt), se = Math.sin(view.tilt);
    function project(p) {
      var x = p[0] * ct - p[1] * st, y = p[0] * st + p[1] * ct, z = (p[2] - (low + high) / 2) * stretch;
      return [w / 2 + x * scale, h / 2 - (y * se + z * ce) * scale, y * ce - z * se];
    }
    var items = quads.map(function (q) {
      var s = q.p.map(project);
      return { q: q, s: s, depth: (s[0][2] + s[1][2] + s[2][2] + s[3][2]) / 4 };
    }).concat(edges.map(function (e) {
      var s = e.map(project);
      return { s: s, depth: (s[0][2] + s[1][2]) / 2 - H.spacing_ft * 1.5 };
    })).sort(function (a, b) { return b.depth - a.depth; });
    items.forEach(function (it) {
      g.beginPath();
      it.s.forEach(function (p, k) { g[k ? "lineTo" : "moveTo"](p[0], p[1]); });
      if (!it.q) { g.strokeStyle = "#e89a00"; g.lineWidth = 3.5; g.lineCap = "round"; g.stroke(); return; }
      var p = it.q.p, t = high > low ? ((p[0][2] + p[2][2]) / 2 - low) / (high - low) : 0.5;
      var sx = (p[1][2] + p[2][2] - p[0][2] - p[3][2]) * stretch / (2 * H.spacing_ft);
      var sy = (p[2][2] + p[3][2] - p[0][2] - p[1][2]) * stretch / (2 * H.spacing_ft);
      var light = Math.max(-14, Math.min(14, (sx - sy) * 22));
      var fill = "hsl(" + (105 - 70 * t) + "," + (it.q.mine ? 42 : 10) + "%," + ((it.q.mine ? 38 : 60) + 18 * t + light) + "%)";
      g.closePath(); g.fillStyle = fill; g.strokeStyle = fill; g.lineWidth = 0.8; g.fill(); g.stroke();
    });
    var tip = [-st, ct * se], len = Math.hypot(tip[0], tip[1]) || 1;
    var cx = 44, cy = 48, dx = tip[0] / len * 24, dy = -tip[1] / len * 24;
    g.strokeStyle = g.fillStyle = "#1d2a24"; g.lineWidth = 2.5;
    g.beginPath(); g.moveTo(cx - dx / 2, cy - dy / 2); g.lineTo(cx + dx / 2, cy + dy / 2); g.stroke();
    g.beginPath(); g.arc(cx + dx / 2, cy + dy / 2, 3.5, 0, 7); g.fill();
    g.font = "bold 14px Segoe UI, sans-serif"; g.textAlign = "center"; g.textBaseline = "middle";
    g.fillText("N", cx + dx, cy + dy);
  }
  function reset() { view = { turn: -0.5, tilt: 0.65, zoom: 1 }; draw(); }
  var drag = null;
  canvas.addEventListener("pointerdown", function (e) { drag = [e.clientX, e.clientY]; canvas.setPointerCapture(e.pointerId); });
  canvas.addEventListener("pointerup", function () { drag = null; });
  canvas.addEventListener("pointercancel", function () { drag = null; });
  canvas.addEventListener("pointermove", function (e) {
    if (!drag) return;
    view.turn += (e.clientX - drag[0]) * 0.008;
    view.tilt = Math.max(0.25, Math.min(1.45, view.tilt + (e.clientY - drag[1]) * 0.006));
    drag = [e.clientX, e.clientY];
    draw();
  });
  canvas.addEventListener("wheel", function (e) {
    e.preventDefault();
    view.zoom = Math.max(0.5, Math.min(4, view.zoom * (e.deltaY < 0 ? 1.1 : 1 / 1.1)));
    draw();
  }, { passive: false });
  $("stretch").addEventListener("input", draw);
  $("reset").addEventListener("click", reset);
  window.addEventListener("resize", draw);
  reset();
})();
