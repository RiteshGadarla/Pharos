import type { DemoBundle } from "./types";

// Tries the live core service first (proxied to localhost:8000 in dev),
// falls back to the static copy of the same bundle bundled into the
// frontend build. Either way this is the same offline-built JSON, see
// PLAN.md section 15: no live pipeline call, no database, network
// cable unplugged.
export async function loadDemoBundle(): Promise<DemoBundle> {
  try {
    const res = await fetch("/api/demo");
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
