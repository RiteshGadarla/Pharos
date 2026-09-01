// PLAN.md section 12, "Design direction". Use exactly these.
export const COLORS = {
  ink: "#0A1E29",
  panel: "#102C3A",
  graticule: "#2E5567",
  paper: "#E9E3D2",
  muted: "#90A5AF",
  oil: "#F2A03D",
  suspect: "#D6455E",
  cleared: "#4E7C6B",
} as const;

export function hexToRgb(hex: string): [number, number, number] {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}
