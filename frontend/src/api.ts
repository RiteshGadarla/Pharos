import type { CaseSummary, CasesIndex, DemoBundle } from "./types";

// How long a request may wait for its response headers before it counts
// as unanswered. In dev every /api call goes through the Vite proxy, and
// a core service that is up but wedged holds the socket open forever
// rather than refusing it, which left the console on its loading screen
// with a perfectly good static bundle one fallback away. The timer stops
// once headers arrive, so a large bundle body is never cut off.
const HEADER_TIMEOUT_MS = 4000;

//
// Once one /api request has timed out the service is taken as wedged for
// the rest of the page load, so the case index, the bundle, the scene
// image and the dossier do not each wait out the timer in turn.
let apiUnresponsive = false;

async function fetchWithTimeout(url: string, init: RequestInit = {}): Promise<Response> {
  const isApi = url.startsWith("/api/");
  if (isApi && apiUnresponsive) throw new Error("core service is not answering");
  const controller = new AbortController();
  let timedOut = false;
  const timer = window.setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, HEADER_TIMEOUT_MS);
  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } catch (e) {
    if (isApi && timedOut) apiUnresponsive = true;
    throw e;
  } finally {
    window.clearTimeout(timer);
  }
}

// Tries the live core service first (proxied to localhost:8000 in dev),
// falls back to the static copy of the same bundle bundled into the
// frontend build. Either way this is the same offline-built JSON, see
// PLAN.md section 15: no live pipeline call, no database, network
// cable unplugged.
export async function loadDemoBundle(): Promise<DemoBundle> {
  try {
    const res = await fetchWithTimeout("/api/demo");
    if (res.ok) return (await res.json()) as DemoBundle;
  } catch {
    // core service not running, fall through to the static copy
  }
  const fallback = await fetch("/data/demo_bundle.json");
  if (!fallback.ok) {
    throw new Error("could not load the demo bundle from the core service or the static fallback");
  }
  return (await fallback.json()) as DemoBundle;
}

// Where the case index came from. It decides whether the core service
// can be asked for per-case assets: a service that does not serve
// /api/cases would ignore a ?case= query and hand back the default
// case's image under another case's name.
export type CasesSource = "api" | "static";

export interface LoadedCases {
  index: CasesIndex;
  source: CasesSource;
}

// A static host answers a missing file with its SPA fallback page and a
// 200, so a response only counts once it parses and has the right shape.
async function readJson(url: string): Promise<unknown | null> {
  try {
    const res = await fetchWithTimeout(url);
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

function isCasesIndex(value: unknown): value is CasesIndex {
  if (!value || typeof value !== "object") return false;
  const cases = (value as { cases?: unknown }).cases;
  return (
    Array.isArray(cases) &&
    cases.length > 0 &&
    cases.every((c) => c && typeof c === "object" && typeof c.id === "string" && typeof c.bundle_url === "string")
  );
}

function isBundle(value: unknown): value is DemoBundle {
  return Boolean(value && typeof value === "object" && "origin_field" in value && "scene" in value);
}

// The case index, or null when there is none. Null is the normal state
// of a checkout that only has the one demo bundle, and the console then
// loads that bundle exactly as before and shows no switcher.
export async function loadCasesIndex(): Promise<LoadedCases | null> {
  const live = await readJson("/api/cases");
  if (isCasesIndex(live)) return { index: live, source: "api" };
  const fallback = await readJson("/data/cases.json");
  if (isCasesIndex(fallback)) return { index: fallback, source: "static" };
  return null;
}

// The case the console should open on: the one named in the page URL if
// it exists, then the index's own default, then the first listed.
export function initialCaseId(index: CasesIndex): string {
  const requested = new URLSearchParams(window.location.search).get("case");
  const ids = index.cases.map((c) => c.id);
  if (requested && ids.includes(requested)) return requested;
  if (ids.includes(index.default_case)) return index.default_case;
  return ids[0];
}

export async function loadCaseBundle(entry: CaseSummary, source: CasesSource): Promise<DemoBundle> {
  const candidates = [entry.bundle_url];
  if (source === "api") candidates.push(`/api/demo?case=${encodeURIComponent(entry.id)}`);
  for (const url of candidates) {
    const body = await readJson(url);
    if (isBundle(body)) return body;
  }
  throw new Error(`could not load the bundle for ${entry.title || entry.id}`);
}

// Candidate URLs for the scene basemap and the dossier, most live first.
// With no case selected these are exactly the single-bundle paths the
// console always used.
export function scenePreviewCandidates(entry: CaseSummary | null, source: CasesSource | null): string[] {
  if (!entry) return ["/api/scene_preview.png", "/data/scene_preview.png"];
  const api = `/api/scene_preview.png?case=${encodeURIComponent(entry.id)}`;
  return source === "api" ? [api, entry.scene_preview_url] : [entry.scene_preview_url];
}

export function dossierCandidates(entry: CaseSummary | null, source: CasesSource | null): string[] {
  if (!entry) return ["/api/dossier", "/data/case_dossier.pdf"];
  const api = `/api/dossier?case=${encodeURIComponent(entry.id)}`;
  return source === "api" ? [api, entry.dossier_url] : [entry.dossier_url];
}

// The first candidate that answers a HEAD request, or the last one if
// none do, so there is always something to point at.
export async function firstAvailable(candidates: string[]): Promise<string> {
  for (const url of candidates.slice(0, -1)) {
    try {
      const res = await fetchWithTimeout(url, { method: "HEAD" });
      if (res.ok) return url;
    } catch {
      // unreachable, try the next one
    }
  }
  return candidates[candidates.length - 1];
}
