// A calm page: one chapter on screen at a time, the figures behind disclosures the reader opens, and a little motion
// where it helps (a chapter fading in, chart lines drawing in once, headline numbers counting up once).
// Shared by the Forecast page; the Plan page can use the same pieces. Styles: the "calm" block at the end of style.css.
// Motion is on unless the person turns it off with the switch; it does not follow the computer's reduced-motion
// setting, because this computer reports it even though the owner wants the motion.
import { esc } from "./util.js";

// ---------------------------------------------------------------- motion: one remembered switch

const MOTION_KEY = "landplanner.motion", OLD_KEY = "landplanner.present.motion";

// true unless the person turned motion off (here, or earlier in the presentation)
export function motionOn() {
  try {
    const v = localStorage.getItem(MOTION_KEY) || localStorage.getItem(OLD_KEY);
    return v !== "off";
  } catch (e) { return true; }
}
// remembers the choice, and tells every switch on the page
export function setMotion(on) {
  try { localStorage.setItem(MOTION_KEY, on ? "on" : "off"); } catch (e) { /* remembered for this visit only */ }
  document.dispatchEvent(new CustomEvent("calm-motion", { detail: { on: !!on } }));
}
// the switch itself: a button with role="switch"; motionSwitch() writes it, watchMotion() makes it work
export function motionSwitch() {
  const on = motionOn();
  return `<button type="button" class="calm-switch" data-calm-motion role="switch" aria-checked="${on}" title="Turn the page's small movements on or off"><i aria-hidden="true"></i><span>Motion ${on ? "on" : "off"}</span></button>`;
}
// clicks on any switch inside root flip motion; onChange(on) runs on every change. Returns a function that stops it.
export function watchMotion(root, onChange) {
  const click = (e) => {
    const b = e.target.closest ? e.target.closest("[data-calm-motion]") : null;
    if (b && root.contains(b)) setMotion(!motionOn());
  };
  const changed = (e) => {
    const on = e.detail.on;
    root.querySelectorAll("[data-calm-motion]").forEach((b) => {
      b.setAttribute("aria-checked", String(on));
      const s = b.querySelector("span");
      if (s) s.textContent = `Motion ${on ? "on" : "off"}`;
    });
    if (!on) stopMotion(root);
    if (onChange) onChange(on);
  };
  root.addEventListener("click", click);
  document.addEventListener("calm-motion", changed);
  return () => { root.removeEventListener("click", click); document.removeEventListener("calm-motion", changed); };
}
// everything waiting to move is shown at once
function stopMotion(root) {
  root.querySelectorAll(".calm-wait,.calm-draw,.calm-enter").forEach((n) => n.classList.remove("calm-wait", "calm-draw", "calm-enter"));
}

// ---------------------------------------------------------------- the small movements

// a chapter coming in: a short fade and rise (about 200 ms). nodes: elements or a NodeList
export function enter(nodes) {
  if (!motionOn()) return;
  [...nodes].forEach((n) => {
    n.classList.remove("calm-enter");
    void n.offsetWidth;   // so it plays again
    n.classList.add("calm-enter");
    n.addEventListener("animationend", () => n.classList.remove("calm-enter"), { once: true });
  });
}

// a chart drawing in from left to right, once, when it first comes into view. box holds an <svg>; what draws in is
// the svg's <g class="calm-data"> (or the whole svg when it has none).
let seer = null;
function seen(entries) {
  entries.forEach((en) => {
    if (!en.isIntersecting) return;
    seer.unobserve(en.target);
    const box = en.target;
    if (!box.classList.contains("calm-wait")) return;
    box.classList.remove("calm-wait");
    box.classList.add("calm-draw");
    setTimeout(() => box.classList.remove("calm-draw"), 1100);
  });
}
export function drawIn(box) {
  if (!motionOn() || !box) return;
  if (!window.IntersectionObserver) return;
  if (!seer) seer = new IntersectionObserver(seen, { threshold: 0.3 });
  box.classList.add("calm-wait");
  seer.observe(box);
}

// a number counting up to its value, once. The element already shows the full value (so it reads without motion);
// format(n) writes a number between 0 and the value the same way.
export function countUp(node, to, format, ms = 900) {
  if (!motionOn() || !node || !isFinite(Number(to))) return;
  const end = Number(to), full = node.textContent, start = performance.now();
  const step = (now) => {
    if (!node.isConnected) return;
    const t = Math.min(1, (now - start) / ms);
    node.textContent = t < 1 ? format(end * (1 - Math.pow(1 - t, 3))) : full;
    if (t < 1) requestAnimationFrame(step);
  };
  node.textContent = format(0);
  requestAnimationFrame(step);
}

// ---------------------------------------------------------------- disclosures (native <details>)

// a closed box the reader opens: "Show the year-by-year figures". key names it, so it stays open when the page redraws.
// open: a Set of the keys open now (see watchFolds)
export function fold(key, summary, body, open, cls = "") {
  if (!body) return "";
  return `<details class="calm-fold${cls ? " " + cls : ""}" data-fold="${esc(key)}"${open && open.has(key) ? " open" : ""}><summary>${esc(summary)}</summary><div class="calm-fold-body">${body}</div></details>`;
}
// keeps open (a Set) in step with what the reader opens and closes inside root; onOpen(details) runs when one opens
export function watchFolds(root, open, onOpen) {
  const toggled = (e) => {
    const d = e.target;
    if (!d || d.tagName !== "DETAILS" || !d.dataset.fold || root.dataset.calmPrinting) return;
    if (d.open) { open.add(d.dataset.fold); if (onOpen) onOpen(d); } else open.delete(d.dataset.fold);
  };
  root.addEventListener("toggle", toggled, true);   // "toggle" does not bubble; it is caught on its way down
  return () => root.removeEventListener("toggle", toggled, true);
}

// ---------------------------------------------------------------- chapters: one part of the page at a time

// The address keeps the open chapter after the route: #/forecast/menifee/123+456?part=site
export function partInAddress(param = "part") {
  const q = location.hash.split("?")[1] || "";
  const m = new RegExp("(?:^|&)" + param + "=([^&]*)").exec(q);
  if (!m) return null;
  try { return decodeURIComponent(m[1]); } catch (e) { return m[1]; }
}
function writePart(param, id) {
  const [route, q = ""] = location.hash.split("?");
  const rest = q.split("&").filter((x) => x && !x.startsWith(param + "="));
  const next = route + "?" + rest.concat(param + "=" + encodeURIComponent(id)).join("&");
  try { history.replaceState(history.state, "", next); } catch (e) { /* the address keeps its old chapter */ }
}

// Chapters over a page whose parts carry data-part="<chapter id>" (they stay in their printed order in the page;
// only the open chapter's parts are on screen, and print shows them all).
//   list: [[id, "Words on the tab"], ...]   root: the element holding the parts
//   onShow(id, first): runs after a chapter is shown (first is true the first time it is shown)
// Returns { tabs(), pager(), open(id, how), current(), partOf(node) }:
//   tabs()  the row of chapter buttons (put it once, where the reader sees it first)
//   pager() Previous / Next for the open chapter (redrawn by open())
//   open(id, { scroll, focus, write }) shows a chapter: scroll brings the top of the chapter into view
export function chapters({ root, list, param = "part", onShow }) {
  const ids = list.map((c) => c[0]);
  let cur = ids.includes(partInAddress(param)) ? partInAddress(param) : ids[0];
  const shown = new Set();
  const words = (id) => (list.find((c) => c[0] === id) || [id, id])[1];

  function tabs() {
    return `<div class="calm-tabs-top" data-calm-top></div><nav class="calm-tabs" aria-label="Parts of this page">
      <div class="calm-tab-row">${list.map(([id, w], i) => `<button type="button" data-chapter="${esc(id)}"${id === cur ? ' aria-current="true" class="on"' : ""}><small aria-hidden="true">${i + 1}</small>${esc(w)}</button>`).join("")}</div>
      ${motionSwitch()}</nav>`;
  }
  function pager() {
    const i = ids.indexOf(cur), prev = ids[i - 1], next = ids[i + 1];
    return `<nav class="calm-pager" aria-label="Previous and next part">
      ${prev ? `<button type="button" class="calm-prev" data-chapter="${esc(prev)}" data-calm-scroll><span>Previous</span>${esc(words(prev))}</button>` : "<span></span>"}
      ${next ? `<button type="button" class="calm-next" data-chapter="${esc(next)}" data-calm-scroll><span>Next</span>${esc(words(next))}</button>` : "<span></span>"}</nav>`;
  }
  function paint() {
    root.querySelectorAll("[data-part]").forEach((n) => n.classList.toggle("calm-off", n.dataset.part !== cur));
    root.querySelectorAll(".calm-tabs [data-chapter]").forEach((b) => {
      const on = b.dataset.chapter === cur;
      b.classList.toggle("on", on);
      if (on) b.setAttribute("aria-current", "true"); else b.removeAttribute("aria-current");
    });
    root.querySelectorAll("[data-calm-pager]").forEach((p) => { p.innerHTML = pager(); });
    // on a phone the row scrolls sideways: keep the open chapter's button in sight
    const row = root.querySelector(".calm-tab-row"), on = row && row.querySelector(".on");
    if (row && on && row.scrollWidth > row.clientWidth) {
      const left = on.offsetLeft - row.offsetLeft, right = left + on.offsetWidth;
      if (left < row.scrollLeft || right > row.scrollLeft + row.clientWidth) row.scrollLeft = Math.max(0, left - 24);
    }
  }
  function open(id, how = {}) {
    if (!ids.includes(id)) return;
    const changed = id !== cur;
    cur = id;
    paint();
    if (how.write !== false && changed) writePart(param, id);
    const parts = root.querySelectorAll(`[data-part="${CSS.escape(id)}"]`);
    if (how.scroll) {
      const top = root.querySelector("[data-calm-top]");
      const y = top ? top.getBoundingClientRect().top + window.scrollY : 0;
      if (window.scrollY > y - 2) window.scrollTo({ top: y, behavior: "auto" });
    }
    if (changed || how.first) enter(parts);
    const first = !shown.has(id);
    shown.add(id);
    if (onShow) onShow(id, first);
    if (how.focus) {
      const h = parts[0] && parts[0].querySelector("h2");
      if (h) { h.setAttribute("tabindex", "-1"); h.focus({ preventScroll: true }); }
    }
  }
  // the chapter a node of the page belongs to
  const partOf = (node) => { const p = node && node.closest ? node.closest("[data-part]") : null; return p ? p.dataset.part : null; };
  root.addEventListener("click", (e) => {
    const b = e.target.closest ? e.target.closest("[data-chapter]") : null;
    if (!b || !root.contains(b)) return;
    open(b.dataset.chapter, { scroll: true, focus: b.hasAttribute("data-calm-scroll") });
  });
  return { tabs, pager, open, paint, current: () => cur, partOf };
}

// ---------------------------------------------------------------- print: every chapter, every disclosure open

// before the page prints, every chapter is shown and every disclosure opened (ready() redraws what needs a size,
// such as charts); after printing, the page goes back to how the reader left it. Returns a function that stops it.
export function printEverything(root, ready) {
  let closed = [];
  const before = () => {
    root.dataset.calmPrinting = "1";
    root.classList.add("calm-all");
    closed = [...root.querySelectorAll("details:not([open])")];
    closed.forEach((d) => { d.open = true; });
    if (ready) { try { ready(); } catch (e) { console.error(e); } }
  };
  const after = () => {
    closed.forEach((d) => { d.open = false; });
    closed = [];
    root.classList.remove("calm-all");
    setTimeout(() => { delete root.dataset.calmPrinting; }, 0);
  };
  window.addEventListener("beforeprint", before);
  window.addEventListener("afterprint", after);
  return () => { window.removeEventListener("beforeprint", before); window.removeEventListener("afterprint", after); };
}
