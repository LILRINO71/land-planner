// "Download PDF" and "Download Excel" for a page or a table, with the dataset, version and audience on screen.
import { esc } from "./ui.js";
import { toast } from "../util.js";

// opts: { module } for a page (PDF and Excel of everything), { entity } for one table; small: smaller buttons
export function exportButtons(ctx, { module = "", entity = "", small = false, pdf = true } = {}) {
  if (ctx.can && ctx.can.export === false) return "";
  const cls = "btn" + (small ? " small" : "");
  return `<span class="dz-exports">${pdf && module ? `<button type="button" class="${cls}" data-export="pdf" data-module="${esc(module)}">Download PDF</button>` : ""}` +
    `<button type="button" class="${cls}" data-export="xlsx" data-entity="${esc(entity || "all")}">Download Excel</button>` +
    `<span class="dz-status" role="status" aria-live="polite"></span></span>`;
}
export function wireExports(root, ctx) {
  root.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-export]");
    if (!b || !root.contains(b)) return;
    const status = b.parentElement.querySelector(".dz-status");
    const params = { dataset: ctx.dataset, version: ctx.version, audience: ctx.viewAs || "" };
    b.disabled = true;
    if (status) { status.className = "dz-status busy"; status.textContent = "Preparing the file…"; }
    try {
      const name = b.dataset.export === "pdf" ? await ctx.api.exportPdf(ctx.project.id, { ...params, module: b.dataset.module })
        : await ctx.api.exportXlsx(ctx.project.id, { ...params, entity: b.dataset.entity });
      if (status) { status.className = "dz-status ok"; status.textContent = ""; }
      toast(`Downloaded ${name}.`);
    } catch (err) {
      if (status) {
        status.className = "dz-status bad";
        status.textContent = err.code === "not-ready" ? `The ${b.dataset.export === "pdf" ? "PDF" : "Excel"} writer is not installed yet, so this download is not available.` : err.message;
      }
    } finally { b.disabled = false; }
  });
}
