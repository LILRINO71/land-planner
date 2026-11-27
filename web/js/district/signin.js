// The way into the district workspace: the landing lines, Google or name-and-passcode sign-in, the first run (the
// first person becomes the administrator), the confidentiality agreement, and the idle warning.
import { dapi, lastRequestAt } from "./api.js";
import { esc, say } from "./ui.js";

const GENERIC = { title: "Land Planner", subtitle: "District workspace", badge: "Private workspace", notice: "Authorized access only",
  location: "", footer: "" };

// the lines on the sign-in card: the server's `landing` (a project's branding) when it gives them, else the app's own
function landingLines(info) {
  const given = info && info.landing && typeof info.landing === "object" ? info.landing : null;
  const l = Object.assign({}, GENERIC, given || {});
  const year = new Date().getFullYear();
  const own = given && given.footer ? [].concat(given.footer).flatMap((x) => String(x).split(/\s+[·•|]\s+/)) : ["Confidential workspace", "Role-based access"];
  const foot = [`© ${year} ${(given && (given.copyright || given.owner)) || "Land Planner"}`].concat(own);
  return { ...l, foot: [...new Set(foot.filter(Boolean))] };
}

function frame(info, inner) {
  const l = landingLines(info);
  return `<div class="dz-gate">
    <div class="dz-gate-card">
      <div class="dz-gate-top">
        <span class="dz-badge">${esc(l.badge)}</span>
        <span class="dz-notice"><svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true"><path d="M12 3 5 6v5c0 4.4 3 8.3 7 9.5 4-1.2 7-5.1 7-9.5V6l-7-3z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/></svg>${esc(l.notice)}</span>
      </div>
      ${l.location ? `<p class="dz-gate-place">${esc(l.location)}</p>` : ""}
      <h1 class="dz-gate-title">${esc(l.title)}</h1>
      <p class="dz-gate-sub">${esc(l.subtitle)}</p>
      <div class="dz-gate-body">${inner}</div>
    </div>
    <footer class="dz-gate-foot">${l.foot.map((x) => `<span>${esc(x)}</span>`).join("")}</footer>
  </div>`;
}

let gsiLoading = null;
function loadGoogle() {
  if (window.google && window.google.accounts && window.google.accounts.id) return Promise.resolve();
  if (!gsiLoading) {
    gsiLoading = new Promise((ok, bad) => {
      const s = document.createElement("script");
      s.src = "https://accounts.google.com/gsi/client"; s.async = true; s.onload = ok;
      s.onerror = () => { gsiLoading = null; bad(new Error("Google sign-in could not be loaded. Check the internet connection, or sign in with your name and passcode.")); };
      document.head.appendChild(s);
    });
  }
  return gsiLoading;
}

// the sign-in screen. message: why the person is here again (session ended, refused). done(): signed in.
export function signInPage(el, info, { message = "", done }) {
  const first = !!(info && info.bootstrap);
  const google = info && info.google && info.google.enabled && info.google.client_id;
  const passForm = (firstRun) => `<form class="dz-form" data-pass>
      <label class="field"><span>Your name</span><input name="name" autocomplete="username" required maxlength="80"></label>
      <label class="field"><span>Passcode${firstRun ? " (at least 8 characters)" : ""}</span><input name="passcode" type="password" autocomplete="${firstRun ? "new-password" : "current-password"}" required minlength="${firstRun ? 8 : 1}"></label>
      ${firstRun ? '<label class="field"><span>Passcode again</span><input name="again" type="password" autocomplete="new-password" required minlength="8"></label>' : ""}
      <button class="btn primary" type="submit">${firstRun ? "Set up and sign in" : "Sign in"}</button>
      <p class="dz-status" role="status" aria-live="polite"></p></form>`;
  let inner;
  if (first) {
    inner = `<h2>Set up the workspace</h2>
      <p>Nobody has signed in here yet. You will be the administrator: choose your name and a passcode. A Sample District is put in so the workspace is not empty.</p>
      ${google ? `<div class="dz-google" data-google></div><p class="dz-or"><span>or</span></p>` : ""}${passForm(true)}`;
  } else {
    inner = `${message ? `<p class="notice" role="alert">${esc(message)}</p>` : ""}
      ${google ? `<div class="dz-google" data-google><button class="btn dz-g-wait" type="button" disabled>Continue with Google</button></div><p class="dz-or"><span>or</span></p>`
        : `<p class="dz-g-off">Google sign-in needs to be set up by the owner, so sign in with your name and passcode.</p>`}
      ${passForm(false)}`;
  }
  el.innerHTML = frame(info, inner);
  const form = el.querySelector("[data-pass]"), status = form.querySelector(".dz-status");
  const finish = (s) => { if (s && s.signed_in) done(s); else say(status, "That did not sign you in. Try again.", "bad"); };
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = new FormData(form), name = String(f.get("name") || "").trim(), passcode = String(f.get("passcode") || "");
    if (first && passcode !== String(f.get("again") || "")) { say(status, "The two passcodes are not the same.", "bad"); return; }
    say(status, "Signing in…", "busy");
    form.querySelector("button[type=submit]").disabled = true;
    try { finish(await dapi.signIn({ method: "passcode", name, passcode })); }
    catch (err) { say(status, err.message, "bad"); }
    finally { form.querySelector("button[type=submit]").disabled = false; }
  });
  if (google) {
    const box = el.querySelector("[data-google]");
    loadGoogle().then(() => {
      window.google.accounts.id.initialize({ client_id: info.google.client_id, callback: async (resp) => {
        say(status, "Checking your Google account…", "busy");
        try { finish(await dapi.signIn({ method: "google", id_token: resp.credential })); }
        catch (err) { say(status, err.message, "bad"); }
      } });
      box.innerHTML = "";
      window.google.accounts.id.renderButton(box, { theme: "outline", size: "large", text: "continue_with", shape: "rectangular", width: 280 });
    }).catch((err) => { box.innerHTML = `<p class="dz-g-off">${esc(err.message)}</p>`; });
  }
  const input = form.querySelector("input");
  if (input) setTimeout(() => input.focus(), 0);
}

export function ndaPage(el, info, session, { done, signOut }) {
  const nda = session.nda || {};
  el.innerHTML = frame(info, `<h2>Confidentiality agreement</h2>
    <p class="muted">Version ${esc(nda.version || 1)}. Read it, then accept it to open the workspace. The time and version are recorded.</p>
    <div class="dz-nda-text" tabindex="0">${esc(nda.text || "").replace(/\n/g, "<br>")}</div>
    <form class="dz-form" data-nda>
      <label class="check"><input type="checkbox" name="ok" required> I have read the agreement and accept it</label>
      <div class="dz-row"><button class="btn primary" type="submit">Accept and continue</button><button class="btn" type="button" data-out>Sign out</button></div>
      <p class="dz-status" role="status" aria-live="polite"></p></form>`);
  const form = el.querySelector("[data-nda]"), status = form.querySelector(".dz-status");
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    try { done(await dapi.acceptNda()); } catch (err) { say(status, err.message, "bad"); }
  });
  form.querySelector("[data-out]").addEventListener("click", signOut);
}

// ---------------------------------------------------------------- idle: a warning one minute before the session ends

let idleTimer = 0, warnBox = null, lastPing = 0;
export function watchIdle(minutes, { onEnded }) {
  stopIdle();
  const limit = Math.max(2, Number(minutes) || 30) * 60000;
  const activity = () => {
    // someone using the page is not idle: keep the session alive, at most once every two minutes
    if (Date.now() - lastRequestAt() > 120000 && Date.now() - lastPing > 60000) { lastPing = Date.now(); dapi.session().catch(() => {}); }
  };
  document.addEventListener("pointerdown", activity, true);
  document.addEventListener("keydown", activity, true);
  const tick = () => {
    const idle = Date.now() - lastRequestAt();
    if (idle >= limit) { hideWarn(); onEnded(); return; }
    if (idle >= limit - 60000) showWarn(Math.max(1, Math.round((limit - idle) / 1000)));
    else hideWarn();
  };
  idleTimer = setInterval(tick, 5000);
  stopIdle.extra = () => { document.removeEventListener("pointerdown", activity, true); document.removeEventListener("keydown", activity, true); };
}
export function stopIdle() {
  clearInterval(idleTimer); idleTimer = 0; hideWarn();
  if (stopIdle.extra) { stopIdle.extra(); stopIdle.extra = null; }
}
function showWarn(seconds) {
  if (!warnBox) {
    warnBox = document.createElement("div");
    warnBox.className = "dz-idle";
    warnBox.setAttribute("role", "alertdialog");
    warnBox.setAttribute("aria-labelledby", "dz-idle-t");
    warnBox.innerHTML = `<p id="dz-idle-t"><b>You will be signed out in about a minute</b> because the workspace has not been used.</p><button class="btn primary" type="button">Stay signed in</button>`;
    warnBox.querySelector("button").addEventListener("click", () => { dapi.session().catch(() => {}); hideWarn(); });
    document.body.appendChild(warnBox);
    warnBox.querySelector("button").focus({ preventScroll: true });
  }
  warnBox.dataset.left = seconds;
}
function hideWarn() { if (warnBox) { warnBox.remove(); warnBox = null; } }
