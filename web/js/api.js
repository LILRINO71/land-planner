// Talking to the local server, and the few things every page shares: the list of cities, My lands, and the
// facts of lands already opened (so moving between a land's pages does not ask again).

export class ApiError extends Error {
  constructor(message, code, status) { super(message); this.code = code; this.status = status; }
}

async function call(method, path, body) {
  let response;
  try {
    response = await fetch(path, {
      method, headers: body ? { "Content-Type": "application/json" } : {}, body: body ? JSON.stringify(body) : undefined,
    });
  } catch (e) {
    throw new ApiError("Land Planner is not running. Start it again with “Start Land Planner”, then reload this page.", "stopped", 0);
  }
  let data = null;
  try { data = await response.json(); } catch (e) { /* handled below */ }
  if (!response.ok || !data) {
    const err = data && data.error;
    throw new ApiError((err && err.message) || "Something went wrong. Try again.", (err && err.code) || "unknown", response.status);
  }
  return data;
}

function query(params) {
  const q = new URLSearchParams();
  Object.entries(params || {}).forEach(([k, v]) => { if (v !== "" && v !== null && v !== undefined && v !== false) q.set(k, v === true ? "1" : v); });
  const s = q.toString();
  return s ? "?" + s : "";
}

export const api = {
  summary: (city, fresh) => call("GET", `/api/cities/${city}/summary` + query({ fresh })),
  lands: (city, params) => call("GET", `/api/cities/${city}/lands` + query(params)),
  shapes: (city) => call("GET", `/api/cities/${city}/shapes`),
  land: (city, apn, group, fresh) => call("GET", `/api/cities/${city}/lands/${apn}` + query({ group, fresh })),
};

// ---- cities (asked once)
let citiesPromise = null;
export function cities() {
  if (!citiesPromise) citiesPromise = call("GET", "/api/cities").then((d) => d.cities).catch((e) => { citiesPromise = null; throw e; });
  return citiesPromise;
}
export async function city(id) {
  const found = (await cities()).find((c) => c.id === id);
  if (!found) throw new ApiError("That city is not in Land Planner yet.", "no-such-city", 404);
  return found;
}

// ---- My lands
const savedState = { lands: [], loaded: false, listeners: new Set() };
function setSaved(data) {
  savedState.lands = data.lands;
  savedState.loaded = true;
  savedState.listeners.forEach((fn) => fn());
}
export const saved = {
  list: () => savedState.lands,
  has: (cityId, apn) => savedState.lands.some((x) => x.city === cityId && x.apn === apn),
  load: () => call("GET", "/api/my-lands").then((d) => { setSaved(d); return d.lands; }),
  add: (cityId, apn) => call("POST", "/api/my-lands", { city: cityId, apn }).then(setSaved),
  remove: (cityId, apn) => call("DELETE", `/api/my-lands/${cityId}/${apn}`).then(setSaved),
  onChange: (fn) => { savedState.listeners.add(fn); return () => savedState.listeners.delete(fn); },
};

// ---- one land's facts, kept while the app is open
const landStore = new Map();
export function land(cityId, apn, { fresh = false } = {}) {
  const key = cityId + "/" + apn;
  if (fresh || !landStore.has(key)) {
    const entry = { quick: api.land(cityId, apn, "quick", fresh), ground: null };
    // the ground heights come from a slower service: asked for once the quick facts are in
    entry.loadGround = (again = false) => {
      if (!entry.ground || again) entry.ground = api.land(cityId, apn, "ground", fresh || again);
      return entry.ground;
    };
    entry.quick.catch(() => { if (landStore.get(key) === entry) landStore.delete(key); });
    landStore.set(key, entry);
  }
  return landStore.get(key);
}
