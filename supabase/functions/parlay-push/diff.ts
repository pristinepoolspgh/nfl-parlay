// What changed between two board versions that is worth a buzz.
export type G = { mu: string; fav: string; dog: string; p: number; odds: number;
           dogOdds: number; inj: string[][]; upset: boolean;
           dock: Record<string, number> };
export type Snap = { week: number; generated: string; games: G[];
              td: Record<string, number>; outs: string[] };

export function extract(D: any, prev: Snap | null): Snap {
  const games: G[] = D.games.map((g: any) => ({
    mu: g.matchup, fav: g.sides[0].team, dog: g.sides[1].team,
    p: g.sides[0].p, odds: g.sides[0].odds, dogOdds: g.sides[1].odds,
    inj: Object.entries(g.inj || {}).flatMap(([t, rows]: [string, any]) =>
      rows.map((r: any) => [r.name, t, r.pos, r.status])),
    upset: !!g.upset, dock: (g.adj || {}).dock || {},
  }));
  const td: Record<string, number> = {};
  for (const pls of Object.values(D.menu || {}) as any[])
    for (const pl of pls) if (pl.td) td[pl.n] = pl.td[0];
  const outs = new Set(prev && prev.week === D.week ? prev.outs : []);
  for (const g of games) for (const r of g.inj)
    if (r[3] === "Out" || r[3] === "Doubtful") outs.add(r[0] + "|" + r[3]);
  return { week: D.week, generated: D.generated, games, td, outs: [...outs] };
}

const fd = (o: number) => (o < 0 ? "−" + Math.abs(o) : "+" + o);

export function diff(o: Snap | null, n: Snap): string[] {
  if (!o) return [];
  if (o.week !== n.week) {
    const ups = n.games.filter((g) => g.upset).map((g) => `${g.dog} over ${g.fav}`);
    return [`Week ${n.week} board is up`, `${n.games.length} games priced`,
            ...(ups.length ? [`Sims' upset calls: ${ups.join(", ")}`] : [])];
  }
  const seen = new Set(o.outs);
  const og = new Map(o.games.map((g) => [g.mu, g]));
  const out: [number, string][] = [];
  for (const g of n.games) {
    const p = og.get(g.mu);
    if (!p) continue;
    for (const [name, team, pos, status] of g.inj) {
      if ((status !== "Out" && status !== "Doubtful") || seen.has(name + "|" + status)) continue;
      const tdp = n.td[name] ?? o.td[name] ?? 0;
      if (pos === "QB") out.push([0, `${name} ${status.toUpperCase()} (${team} QB)`]);
      else if (tdp >= 0.3) out.push([1, `${name} ${status.toUpperCase()} (${team} ${pos})`]);
    }
    for (const t of Object.keys(g.dock))
      if (!p.dock[t]) out.push([1, `Sims dock ${t} ${g.dock[t]} pts for a QB change`]);
    if (g.upset && !p.upset)
      out.push([2, `Sims pick the upset: ${g.dog} ${fd(g.dogOdds)} over ${g.fav}`]);
    if (p.fav !== g.fav) out.push([2, `${g.fav} now favored over ${g.dog} (${fd(g.odds)})`]);
    else if (Math.abs(g.p - p.p) >= 0.05)
      out.push([3, `${g.fav} ${fd(p.odds)} → ${fd(g.odds)} vs ${g.dog}`]);
  }
  return out.sort((a, b) => a[0] - b[0]).map((x) => x[1]);
}

