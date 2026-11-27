// The spoken briefing on every module page (Web Speech API): play, pause, stop, speed, and the same words written
// out. Hidden when the browser cannot speak.
import { esc, figureWords, leadOf } from "./ui.js";

const SPEEDS = [0.85, 1, 1.15, 1.3, 1.5];

// the words of the briefing, one paragraph each
function script(ctx, { module: m, cards, banners, narratives }) {
  const out = [`${m.label || m.id}, ${ctx.project.name || "this project"}.${m.description ? " " + m.description : ""}`];
  banners.forEach((b) => out.push("A rule for this page: " + b));
  cards.forEach(({ c, f }) => {
    const w = figureWords(f, c.format);
    out.push(`${c.label || (f && f.label) || c.assumption}: ${speakable(w.main)}${w.aside ? ", or " + speakable(w.aside) : ""}.${c.description ? " " + c.description : ""}${f && f.conflict ? " Sources disagree about this figure." : ""}`);
  });
  narratives.forEach((s) => { const t = leadOf(s.body || ""); if (t.lead) out.push((s.heading ? s.heading + ". " : "") + t.lead + (s.ai_assisted ? " This text was written with AI help." : "")); });
  if (ctx.viewAs) out.push(`This is the view the ${ctx.viewAs} audience gets.`);
  return out;
}
// "$6.12M/yr" read aloud as "6.12 million dollars per year"
function speakable(s) {
  return String(s).replace(/\$([\d,.]+)M/g, "$1 million dollars").replace(/\$([\d,.]+)B/g, "$1 billion dollars").replace(/\$([\d,.]+)/g, "$1 dollars")
    .replace(/\/SF\/yr/g, " per square foot per year").replace(/\/SF\/mo/g, " per square foot per month").replace(/\/yr/g, " per year").replace(/\/mo/g, " per month")
    .replace(/\/acre/g, " per acre").replace(/\bSF\b/g, "square feet").replace(/%/g, " percent");
}

export function mount(slot, ctx, parts) {
  if (!slot || !("speechSynthesis" in window) || typeof SpeechSynthesisUtterance === "undefined") return;
  const synth = window.speechSynthesis, paras = script(ctx, parts);
  let i = 0, speed = 1, state = "stopped";
  try { speed = Number(localStorage.getItem("landplanner.briefing.speed")) || 1; } catch (e) { /* default */ }
  if (!SPEEDS.includes(speed)) speed = 1;
  slot.innerHTML = `<div class="dz-audio" role="region" aria-label="Spoken briefing">
    <b>Briefing</b>
    <button type="button" class="btn small primary" data-play>Play</button>
    <button type="button" class="btn small" data-stop hidden>Stop</button>
    <label class="field inline"><span>Speed</span><select data-speed>${SPEEDS.map((s) => `<option value="${s}"${s === speed ? " selected" : ""}>${s}x</option>`).join("")}</select></label>
    <span class="dz-status" role="status" aria-live="polite"></span>
    <details class="calm-fold dz-transcript"><summary>Show the written briefing</summary><div class="calm-fold-body">${paras.map((p) => `<p>${esc(p)}</p>`).join("")}</div></details>
    <span class="dz-audio-end"><a href="${ctx.link(["tool", "ask"])}">Ask the package</a></span></div>`;
  const box = slot.firstElementChild, play = box.querySelector("[data-play]"), stop = box.querySelector("[data-stop]"), status = box.querySelector(".dz-status");
  const paint = () => {
    play.textContent = state === "playing" ? "Pause" : state === "paused" ? "Resume" : "Play";
    stop.hidden = state === "stopped";
    box.classList.toggle("speaking", state === "playing");
    status.textContent = state === "stopped" ? "" : `Part ${Math.min(i + 1, paras.length)} of ${paras.length}`;
  };
  const say = () => {
    if (i >= paras.length) { state = "stopped"; i = 0; paint(); return; }
    const u = new SpeechSynthesisUtterance(speakable(paras[i]));
    u.rate = speed; u.lang = "en-US";
    u.onend = () => { if (state !== "playing" || u.cancelled) return; i++; paint(); say(); };
    u.onerror = () => { if (!u.cancelled) { state = "stopped"; paint(); } };
    current = u;
    synth.speak(u);
  };
  let current = null;
  const halt = () => { if (current) current.cancelled = true; synth.cancel(); };
  play.addEventListener("click", () => {
    if (state === "playing") { synth.pause(); state = "paused"; }
    else if (state === "paused") { synth.resume(); state = "playing"; }
    else { halt(); state = "playing"; i = 0; say(); }
    paint();
  });
  stop.addEventListener("click", () => { halt(); state = "stopped"; i = 0; paint(); });
  box.querySelector("[data-speed]").addEventListener("change", (e) => {
    speed = Number(e.target.value) || 1;
    try { localStorage.setItem("landplanner.briefing.speed", String(speed)); } catch (x) { /* this visit only */ }
    if (state === "playing") { halt(); state = "playing"; say(); }
  });
  if (parts.alive && parts.alive.onLeave) parts.alive.onLeave(() => { halt(); });
  paint();
}
