// PLAN.md section 16, "Design direction". Use exactly these.
export const COLORS = {
  ink: "#0A1E29",
  panel: "#102C3A",
  graticule: "#2E5567",
  paper: "#E9E3D2",
  muted: "#90A5AF",
  oil: "#F2A03D",
  suspect: "#D6455E",
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
