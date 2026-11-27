// Ask the package: a keyword search over the package's own text (narrative, questions and answers), its register
// figures and its requirements, ranked by simple scoring. It is a search of the package, not an AI: it runs in this
// browser on the data already loaded and needs no network.
import { esc, page, leadHtml, calmBox, int, entities, debounce, guarded } from "./common.js";
import { figureWords } from "../ui.js";

const STOP = new Set("a an and are as at be been but by can could did do does for from had has have how i if in into is it its may me more most my no not of on or our should so than that the their them then there these they this to was we were what when where which while who why will with would you your about any all also each just only over such very".split(" "));
// a few words that mean the same thing in a land package
const SAME = { sale: "sell", sold: "sell", purchase: "buy", bought: "buy", acreage: "acre", house: "home", housing: "home", dwelling: "home", lot: "parcel", apn: "parcel", cost: "cost", price: "price", pric: "price" };
// stemming-light: plural, -ing, -ed, -ly, -ment endings; good enough to match "parcels" with "parcel"
export function stem(w) {
  let s = w.toLowerCase();
  if (s.length > 5 && s.endsWith("ies")) s = s.slice(0, -3) + "y";
  else if (s.length > 4 && /(ches|shes|sses|xes)$/.test(s)) s = s.slice(0, -2);
  else if (s.length > 3 && s.endsWith("s") && !s.endsWith("ss") && !s.endsWith("us") && !s.endsWith("is")) s = s.slice(0, -1);
  if (s.length > 5 && s.endsWith("ing")) s = s.slice(0, -3);
  else if (s.length > 4 && s.endsWith("ed")) s = s.slice(0, -2);
  else if (s.length > 5 && s.endsWith("ly")) s = s.slice(0, -2);
  else if (s.length > 7 && s.endsWith("ment")) s = s.slice(0, -4);
  return SAME[s] || s;
}
export function terms(text) {
  return (String(text || "").toLowerCase().match(/[a-z0-9$][a-z0-9$.%-]*[a-z0-9%]|[a-z0-9]/g) || []).map((t) => t.replace(/[.-]+$/, "")).filter((t) => t && !STOP.has(t)).map(stem);
}

// every passage of the package that can answer a question
function corpus(ctx) {
  const e = entities(ctx), mods = new Map((ctx.modules || []).map((m) => [m.id, m])), out = [];
  const modOf = (id) => mods.get(id);
  (e.sections || []).forEach((s) => {
    const m = modOf(s.module);
    if (s.kind === "qa") (s.items || []).forEach((it, k) => out.push({ kind: "Answer", title: it.question || "", body: it.answer || "", module: m, cites: it.cites || [], id: `${s.id}#${k}`, qa: true }));
    else if (s.kind === "narrative" || s.kind === "banner") out.push({ kind: s.kind === "banner" ? "Rule" : "Text", title: s.heading || (m ? m.label : ""), body: s.body || "", module: m, cites: s.cites || [], id: s.id });
    else if (s.kind === "table" && (s.rows || []).length) out.push({ kind: "Table", title: s.heading || "Table", body: (s.columns || []).join(", ") + ". " + (s.rows || []).slice(0, 40).map((r) => r.join(" ")).join("; "), module: m, cites: s.cites || [], id: s.id, table: true });
  });
  (e.assumptions || []).forEach((a) => {
    const v = figureWords(a).main;
    out.push({ kind: "Figure", title: `${a.label}: ${v}`, body: [a.description, a.source_doc ? "Source: " + a.source_doc : "", a.note, a.conflict_note].filter(Boolean).join(" "), fig: a.id, idText: a.id, cites: [] });
  });
  (e.requirements || []).forEach((r) => out.push({ kind: "Requirement", title: `${r.id}${r.title ? ": " + r.title : ""}`, body: [r.text, r.section ? "Section: " + r.section : "", r.gap ? "Still missing: " + r.gap : ""].filter(Boolean).join(" "), req: r, idText: r.id, cites: [] }));
  out.forEach((d) => { d.tTitle = terms(d.title); d.tBody = terms(d.body); d.all = new Set(d.tTitle.concat(d.tBody)); });
  const df = new Map();
  out.forEach((d) => d.all.forEach((t) => df.set(t, (df.get(t) || 0) + 1)));
  return { docs: out, df, n: out.length };
}

function search(C, q) {
  const qt = [...new Set(terms(q))];
  const raw = String(q || "").trim().toLowerCase();
  if (!qt.length && !raw) return [];
  const idf = (t) => Math.log(1 + C.n / (1 + (C.df.get(t) || 0)));
  const scored = C.docs.map((d) => {
    let s = 0, hit = 0;
    qt.forEach((t) => {
      const inT = d.tTitle.filter((x) => x === t).length, inB = d.tBody.filter((x) => x === t).length;
      if (inT || inB) hit++;
      s += idf(t) * (3 * Math.min(inT, 3) + Math.min(inB, 5) * 1) / (1 + Math.log(1 + d.tBody.length / 60));
    });
    if (!hit) return null;
    s *= 0.5 + hit / qt.length;                                 // passages that hold more of the words rank higher
    if (raw.length > 3 && (d.title + " " + d.body).toLowerCase().includes(raw)) s *= 1.8;   // the exact words
    if (d.idText && raw && d.idText.toLowerCase() === raw) s += 50;                         // an id typed in full
    if (d.qa) s *= 1.15;
    return { d, s, hit };
  }).filter(Boolean).sort((a, b) => b.s - a.s);
  return scored.slice(0, 12);
}

// the sentences of a passage that hold the words, with the words marked
function snippet(text, qt, max = 360) {
  const t = String(text || "");
  if (!t) return "";
  const sentences = t.split(/(?<=[.!?])\s+/);
  const scoredS = sentences.map((s, i) => ({ s, i, n: terms(s).filter((x) => qt.includes(x)).length })).sort((a, b) => b.n - a.n || a.i - b.i);
  const pick = scoredS.filter((x) => x.n).slice(0, 2).sort((a, b) => a.i - b.i).map((x) => x.s);
  let out = (pick.length ? pick : sentences.slice(0, 2)).join(" … ");
  if (out.length > max) out = out.slice(0, max).replace(/\s+\S*$/, "") + "…";
  return mark(out, qt);
}
function mark(text, qt) {
  return esc(text).replace(/[A-Za-z0-9$][A-Za-z0-9$%-]*/g, (w) => (qt.includes(stem(w.toLowerCase().replace(/[.-]+$/, ""))) ? `<mark>${w}</mark>` : w));
}

export async function render(el, ctx) {
  await guarded(el, ctx, () => ask(el, ctx));
}
async function ask(el, ctx) {
  const C = corpus(ctx);
  const qaItems = C.docs.filter((d) => d.qa && d.title);
  // a few suggested questions from across the package's question sets
  const bySet = new Map();
  qaItems.forEach((d) => { const k = d.id.split("#")[0]; if (!bySet.has(k)) bySet.set(k, []); bySet.get(k).push(d); });
  const suggestions = [];
  for (let round = 0; suggestions.length < 6 && round < 3; round++) bySet.forEach((list) => { if (suggestions.length < 6 && list[round]) suggestions.push(list[round].title.replace(/^Q?\d+(\.\d+)*\s+/, "").trim()); });
  await guarded0(el, ctx, C, suggestions);
}

async function guarded0(el, ctx, C, suggestions) {
  const P = page(el, ctx);
  const look = new Map(((entities(ctx).assumptions) || []).map((a) => [a.id, a]));
  const lead = leadHtml({ kicker: "Ask the package", sentence: "Type a question in your own words. The best matching passages of the package come back, each with where it comes from.",
    big: int(C.n), bigLabel: "passages searched", aside: "This is a search of the package's own text, figures and requirements, not an AI: nothing is made up, and it works offline on this computer." });
  const form = `<form class="tl-ask" role="search" data-ask><label class="field"><span>Your question</span><input type="search" name="q" autocomplete="off" placeholder="For example: which parcels sell first?" aria-describedby="tl-ask-help"></label><button class="btn primary" type="submit">Search the package</button></form>
    <p id="tl-ask-help" class="fine">Words are matched with their simple forms (parcel and parcels). An id such as a register entry or a requirement number finds that entry.</p>
    ${suggestions.length ? `<div class="tl-suggest" aria-label="Questions the package answers">${suggestions.map((s) => `<button type="button" data-sq="${esc(s)}">${esc(s)}</button>`).join("")}</div>` : ""}
    <p class="dz-status" role="status" aria-live="polite" data-count></p><ol class="tl-hits" data-hits></ol>`;
  P.set({ lead, parts: [["ask", "Ask", C.n ? form : calmBox("The package has no text to search yet", "Its narrative, questions and answers, figures and requirements appear here once they are imported.")]] });
  const hitsEl = el.querySelector("[data-hits]"), countEl = el.querySelector("[data-count]"), input = el.querySelector('[data-ask] input[name="q"]');
  if (!hitsEl) return;
  const show = (q) => {
    const qt = [...new Set(terms(q))];
    const res = search(C, q);
    if (!String(q).trim()) { hitsEl.innerHTML = ""; countEl.textContent = ""; return; }
    countEl.textContent = res.length ? `${res.length === 12 ? "The 12 best" : res.length} matching ${res.length === 1 ? "passage" : "passages"}, best first.` : "Nothing in the package matches those words. Try fewer or other words.";
    hitsEl.innerHTML = res.map(({ d, hit }) => {
      const m = d.module;
      const where = d.fig ? `<button type="button" class="link" data-fig="${esc(d.fig)}">Where this figure comes from</button>`
        : d.req ? `<a href="${esc(d.req.where_in_app && /^#\/districts\//.test(d.req.where_in_app) ? d.req.where_in_app : ctx.link(["requirements"]))}">${d.req.where_in_app ? "Where it is met" : "Requirements checklist"}</a>`
        : m ? `<a href="${esc(ctx.link(["m", m.id]))}">Open the ${esc(m.label || m.id)} page</a>` : "";
      const chips = (d.cites || []).map((id) => { const f = look.get(id); return `<button type="button" class="dz-cite" data-fig="${esc(id)}">${esc(f ? `${f.label}: ${figureWords(f).main}` : id)}</button>`; }).join("");
      return `<li class="tl-hit"><p class="tl-hit-k"><span class="dz-chip">${esc(d.kind)}</span>${m ? `<span>${esc(m.label || m.id)}</span>` : ""}${d.req ? `<span>${esc(d.req.source_document || "")}</span>` : ""}<span>${hit} of ${qt.length || 1} words</span></p>
        <h3>${mark(d.title, qt)}</h3>${d.body ? `<p>${snippet(d.body, qt)}</p>` : ""}
        ${chips ? `<div class="dz-cites"><span>Figures it cites</span>${chips}</div>` : ""}${where ? `<p class="fine">${where}</p>` : ""}</li>`;
    }).join("");
  };
  const live = debounce(() => show(input.value), 250);
  el.addEventListener("input", (e) => { if (e.target === input) live(); });
  el.addEventListener("submit", (e) => { if (e.target.closest("[data-ask]")) { e.preventDefault(); show(input.value); } });
  el.addEventListener("click", (e) => {
    const b = e.target.closest("[data-sq]");
    if (b) { input.value = b.dataset.sq; show(input.value); input.focus(); }
  });
}
