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
  shapes: (city, minAcres) => call("GET", `/api/cities/${city}/shapes` + query({ min_acres: minAcres })),
  // every parcel inside a box of the map (west, south, east, north in degrees)
  parcels: (city, box) => call("GET", `/api/cities/${city}/parcels` + query(box)),
  land: (city, apn, group, fresh) => call("GET", `/api/cities/${city}/lands/${apn}` + query({ group, fresh })),
  // the year-by-year forecast for one parcel, or several as one site; the owner's own figures are kept by the server
  forecast: (city, apns) => call("GET", `/api/cities/${city}/forecast` + query({ apns: apns.join(",") })),
  forecastSet: (city, apns, assumptions) => call("POST", `/api/cities/${city}/forecast` + query({ apns: apns.join(",") }), { assumptions }),
  forecastReset: (city, apns) => call("DELETE", `/api/cities/${city}/forecast` + query({ apns: apns.join(",") })),
  // the wider picture for the same site: the city's economy by year, weather, hazards, what is close by, the
  // typical resident and the steps to take (slower the first time, so it is asked for after the forecast)
  // the ground heights under the site and the plan drawn on it, for the 3D view (slow the first time)
  ground: (city, apns, fresh) => call("GET", `/api/cities/${city}/ground` + query({ apns: apns.join(","), fresh: fresh ? 1 : undefined })),
  outlook: (city, apns, fresh) => call("GET", `/api/cities/${city}/outlook` + query({ apns: apns.join(","), fresh: fresh ? 1 : undefined })),
};

// ---- when a map's records and photo were last updated, asked once per place while the app is open
const updatedStore = new Map();
export function updated(cityId, lat, lon) {
  const key = `${cityId}/${Number(lat).toFixed(4)},${Number(lon).toFixed(4)}`;
  if (!updatedStore.has(key)) {
    const asking = call("GET", `/api/cities/${cityId}/updated` + query({ lat: Number(lat).toFixed(5), lon: Number(lon).toFixed(5) }));
    asking.catch(() => { if (updatedStore.get(key) === asking) updatedStore.delete(key); });
    updatedStore.set(key, asking);
  }
  return updatedStore.get(key);
}
api.updated = updated;

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
const savedState = { lands: [], loaded: false, keptIn: "", listeners: new Set() };
function setSaved(data) {
  savedState.lands = data.lands;
  if (data.kept_in !== undefined) savedState.keptIn = data.kept_in || "";
  savedState.loaded = true;
  savedState.listeners.forEach((fn) => fn());
}
export const saved = {
  list: () => savedState.lands,
  keptIn: () => savedState.keptIn,   // the file on this computer the list is kept in ("" when the server does not say)
  has: (cityId, apn) => savedState.lands.some((x) => x.city === cityId && x.apn === apn),
  load: () => call("GET", "/api/my-lands").then((d) => { setSaved(d); return d.lands; }),
  add: (cityId, apn) => call("POST", "/api/my-lands", { city: cityId, apn }).then(setSaved),
  remove: (cityId, apn) => call("DELETE", `/api/my-lands/${cityId}/${apn}`).then(setSaved),
  onChange: (fn) => { savedState.listeners.add(fn); return () => savedState.listeners.delete(fn); },
};

// ---- My lands side by side: one row per saved land with the headline numbers of its plans. The first answer for a
// land can take several seconds (it reads public records); later ones are quick.
export function compareLands() { return call("GET", "/api/my-lands/compare"); }

// ---- one land's facts, kept while the app is open
const landStore = new Map();
export function land(cityId, apn, { fresh = false } = {}) {
  const key = cityId + "/" + apn;
  if (fresh || !landStore.has(key)) {
    const entry = { quick: api.land(cityId, apn, "quick", fresh), ground: null, market: null };
    // the ground heights come from a slower service: asked for once the quick facts are in
    entry.loadGround = (again = false) => {
      if (!entry.ground || again) entry.ground = api.land(cityId, apn, "ground", fresh || again);
      return entry.ground;
    };
    // what is being built nearby, the people and schools around, and the traffic signals: also asked for after the page is drawn
    entry.loadMarket = (again = false) => {
      if (!entry.market || again) entry.market = api.land(cityId, apn, "market", fresh || again);
      return entry.market;
    };
    entry.quick.catch(() => { if (landStore.get(key) === entry) landStore.delete(key); });
    landStore.set(key, entry);
  }
  return landStore.get(key);
}
