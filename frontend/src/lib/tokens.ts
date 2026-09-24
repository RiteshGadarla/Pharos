// PLAN.md section 16, "Design direction". Use exactly these.
export const COLORS = {
  ink: "#0A1E29",
  panel: "#102C3A",
  graticule: "#2E5567",
  paper: "#E9E3D2",
  muted: "#90A5AF",
  oil: "#F2A03D",
  suspect: "#D6455E",
  // Rank 2 and rank 3 survivors, so one can be told apart from another on
  // the map without opening its card. Picked to sit far in hue from every
  // other reserved colour on this page (oil, radar, current, forecast,
  // wind, cleared, and suspect itself) and validated for CVD-safe
  // all-pairs separation at this page's surface colour: worst pair
  // deltaE 9.1 (deutan/protan simulated), 17.6 normal-vision, both clear
  // of the >=8 / >=15 targets with zero warnings. Every vessel outside
  // this reserved trio still gets its own colour on the map — see
  // MapView's vesselColors — but from an auto-generated wheel rather
  // than a hand-validated slot, since a scene can carry more background
  // traffic than any hand-picked categorical set stays pairwise-distinct
  // for.
  suspect2: "#3987E5",
  suspect3: "#A6961A",
  cleared: "#4E7C6B",
  // Unmatched radar targets, and only those: a hull the SAR scene shows
  // that AIS never reported. Its own colour because it is the only
  // thing on the map that came from a second, independent sensor.
  radar: "#7FB2C4",
  // The forward forecast field, and only that. The backward origin
  // field is drawn in oil, because it is a claim about where observed
  // oil came from. The forecast is a claim about the future and is
  // never evidence, so it must not be able to borrow the authority of
  // the colour the observed slick is drawn in. Off the chart palette
  // deliberately: a prediction should not look like a measurement.
  forecast: "#B08CC7",
  // Surface current arrows. PLAN.md 16A puts the ambient flow in
  // --graticule at low alpha, and this is the legible countable version
  // of that layer, so it stays in the graticule family: the forcing is
  // the chart the case is drawn on, not a finding on it.
  current: "#3E7A93",
  // Wind arrows. Its own token only because wind and current have to be
  // told apart at a glance while both are on screen, and form alone
  // (barb versus arrow) does not survive a projector.
  wind: "#8FA98C",
} as const;

export function hexToRgb(hex: string): [number, number, number] {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

// h in degrees [0,360), s and l as percentages [0,100]. Used to generate
// the background vessel wheel: those colours aren't hand-picked hex, so
// they're built rather than looked up.
export function hslToRgb(h: number, s: number, l: number): [number, number, number] {
  const sN = s / 100;
  const lN = l / 100;
  const k = (n: number) => (n + h / 30) % 12;
  const a = sN * Math.min(lN, 1 - lN);
  const f = (n: number) => lN - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1)));
  return [Math.round(255 * f(0)), Math.round(255 * f(8)), Math.round(255 * f(4))];
}
