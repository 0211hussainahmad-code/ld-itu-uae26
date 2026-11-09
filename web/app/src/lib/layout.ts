// Hand-laid schematic positions for the synthetic topology (design layer only; not geography).
// Coordinates are in a 1200 x 700 viewBox. Every link is a quadratic curve a -> control -> b.
export const VIEW = { w: 1200, h: 700 };

export const LAYOUT: {
  nodes: Record<string, { x: number; y: number; name: string; anchor: "start" | "end" | "middle"; dx: number; dy: number }>;
  links: Record<string, { c: [number, number] }>;
} = {
  nodes: {
    eu_west: { x: 170, y: 220, name: "EU-West", anchor: "middle", dx: 0, dy: -34 },
    asia_south: { x: 1040, y: 200, name: "Asia-South", anchor: "middle", dx: 0, dy: -34 },
    fujairah_cls: { x: 780, y: 410, name: "Fujairah landing", anchor: "start", dx: 22, dy: 6 },
    uae_core: { x: 610, y: 530, name: "UAE core", anchor: "start", dx: 20, dy: 30 },
    uae_central: { x: 420, y: 610, name: "UAE-Central", anchor: "middle", dx: 0, dy: 44 },
    gulf_land: { x: 330, y: 440, name: "Neighbour route", anchor: "end", dx: -20, dy: 6 },
  },
  links: {
    W1: { c: [480, 180] },
    W2: { c: [490, 236] },
    W3: { c: [500, 292] },
    E1: { c: [930, 268] },
    E2: { c: [972, 330] },
    X1: { c: [610, -40] },
    T1: { c: [460, 512] },
    T2: { c: [220, 346] },
    D1: { c: [500, 600] },
    L1: { c: [705, 498] },
  },
};

export function linkPath(a: { x: number; y: number }, b: { x: number; y: number }, c: [number, number]): string {
  return `M${a.x},${a.y} Q${c[0]},${c[1]} ${b.x},${b.y}`;
}

export function midpoint(a: { x: number; y: number }, b: { x: number; y: number }, c: [number, number]) {
  return { x: 0.25 * a.x + 0.5 * c[0] + 0.25 * b.x, y: 0.25 * a.y + 0.5 * c[1] + 0.25 * b.y };
}

// Abstract bathymetric contour texture: deterministic closed curves (no depth values, not a map).
export function contours(): string[] {
  const out: string[] = [];
  const basins = [
    { cx: 520, cy: 330, rx: 470, ry: 250, rings: 9, phase: 0.4 },
    { cx: 1010, cy: 560, rx: 260, ry: 170, rings: 5, phase: 1.7 },
    { cx: 120, cy: 600, rx: 220, ry: 120, rings: 4, phase: 2.9 },
  ];
  for (const b of basins) {
    for (let k = 1; k <= b.rings; k++) {
      const s = k / b.rings;
      const pts: string[] = [];
      const n = 72;
      for (let i = 0; i <= n; i++) {
        const t = (i / n) * Math.PI * 2;
        const wob = 1 + 0.06 * Math.sin(3 * t + b.phase + k * 0.7) + 0.035 * Math.sin(7 * t - k * 0.9 + b.phase);
        const x = b.cx + Math.cos(t) * b.rx * s * wob;
        const y = b.cy + Math.sin(t) * b.ry * s * wob;
        pts.push(`${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`);
      }
      out.push(pts.join("") + "Z");
    }
  }
  return out;
}
