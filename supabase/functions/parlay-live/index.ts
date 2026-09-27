// Live board feed for the Home Screen app: scores, in-play prices, and
// current pregame moneylines, straight from ESPN and FanDuel's public
// APIs. The page polls this every 15 minutes during games, so live
// prices don't wait for the full board rebuild. Read-only, cached 60s.
const FD_AK = "FhMFpcPWXMeyZxOx";
const FD_PAGE = "https://sbapi.pa.sportsbook.fanduel.com/api/content-managed-page" +
  `?page=CUSTOM&customPageId=nfl&pbHorizontal=false&_ak=${FD_AK}&timezone=America%2FNew_York`;
const TD_TAB = (eid: number) => "https://sbapi.pa.sportsbook.fanduel.com/api/event-page" +
  `?_ak=${FD_AK}&eventId=${eid}&tab=td-scorer-props`;
const ESPN = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard";
const ORIGINS = ["https://nfl-parlay-inky.vercel.app"];
const NICK: Record<string, string> = {
  ARI: "Cardinals", ATL: "Falcons", BAL: "Ravens", BUF: "Bills", CAR: "Panthers",
  CHI: "Bears", CIN: "Bengals", CLE: "Browns", DAL: "Cowboys", DEN: "Broncos",
  DET: "Lions", GB: "Packers", HOU: "Texans", IND: "Colts", JAX: "Jaguars",
  KC: "Chiefs", LAC: "Chargers", LAR: "Rams", LV: "Raiders", MIA: "Dolphins",
  MIN: "Vikings", NE: "Patriots", NO: "Saints", NYG: "Giants", NYJ: "Jets",
  PHI: "Eagles", PIT: "Steelers", SEA: "Seahawks", SF: "49ers", TB: "Buccaneers",
  TEN: "Titans", WSH: "Commanders",
};
const abbr = (full: string) =>
  Object.entries(NICK).find(([, n]) => full.includes(n))?.[0] ?? full;
const odds = (r: any): number | null => {
  const o = r?.winRunnerOdds?.americanDisplayOdds?.americanOdds;
  return o === undefined || o === null ? null : Number(o);
};
const imp = (o: number) => (o < 0 ? -o / (-o + 100) : 100 / (o + 100));
const r5 = (x: number) => Math.round(x * 1e5) / 1e5;

async function getJson(url: string) {
  const r = await fetch(url, { headers: { "User-Agent": "curl/8.5.0", Accept: "application/json" } });
  if (!r.ok) throw new Error(`${new URL(url).hostname} ${r.status}`);
  return r.json();
}

async function build() {
  const [espn, fd] = await Promise.all([getJson(ESPN), getJson(FD_PAGE)]);
  const scores: any[] = [];
  for (const ev of espn.events || []) {
    const comp = (ev.competitions || [{}])[0];
    const st = comp.status?.type || {};
    if (st.state !== "in" && st.state !== "post") continue;
    const t: Record<string, any> = {};
    for (const c of comp.competitors || []) t[c.homeAway] = c;
    scores.push({
      matchup: (ev.shortName || "").replace(" VS ", " @ "),
      away: `${t.away?.team?.abbreviation} ${t.away?.score ?? 0}`,
      home: `${t.home?.team?.abbreviation} ${t.home?.score ?? 0}`,
      detail: st.shortDetail || "", final: st.state === "post",
    });
  }
  const finals = new Set(scores.filter((s) => s.final).map((s) => s.matchup));
  const att = fd.attachments || {};
  const now = new Date().toISOString().slice(0, 19);
  const started: Record<number, string> = {}, upcoming: Record<number, string> = {};
  for (const [eid, ev] of Object.entries<any>(att.events || {})) {
    const name: string = ev.name || "";
    if (!name.includes(" @ ")) continue;
    const [a, h] = name.split(" @ ");
    const mu = `${abbr(a)} @ ${abbr(h)}`;
    if ((ev.openDate || "").slice(0, 19) <= now) started[Number(eid)] = mu;
    else upcoming[Number(eid)] = mu;
  }
  const live: Record<string, any[]> = {};
  const pregame: Record<string, any> = {};
  const kinds: Record<string, string> = { MONEY_LINE: "ml", "MATCH_HANDICAP_(2-WAY)": "spread",
    "TOTAL_POINTS_(OVER/UNDER)": "total" };
  for (const m of Object.values<any>(att.markets || {})) {
    const kind = kinds[m.marketType];
    if (!kind || m.marketStatus !== "OPEN") continue;
    const rs = (m.runners || []).filter((r: any) => r.runnerStatus === "ACTIVE" && odds(r) !== null);
    if (rs.length !== 2) continue;
    const [ia, ib] = [imp(odds(rs[0])!), imp(odds(rs[1])!)];
    const ps = [ia / (ia + ib), ib / (ia + ib)];
    const muLive = started[m.eventId], muPre = upcoming[m.eventId];
    if (muLive && !finals.has(muLive)) {
      rs.forEach((r: any, i: number) => {
        const nm: string = r.runnerName || "", h = Number(r.handicap || 0);
        const desc = kind === "ml" ? `${abbr(nm)} ML`
          : kind === "spread" ? `${abbr(nm)} ${h > 0 ? "+" + h : h}`
          : `${nm.startsWith("Over") ? "Over" : "Under"} ${Math.abs(h)} pts`;
        (live[muLive] ||= []).push({ desc, kind, p: r5(ps[i]), odds: odds(r),
          market: m.marketId, sel: r.selectionId });
      });
    } else if (muPre && kind === "ml") {
      pregame[muPre] = { market: m.marketId, sides: rs.map((r: any, i: number) => ({
        team: abbr(r.runnerName || ""), p: r5(ps[i]), odds: odds(r), sel: r.selectionId,
      })).sort((x: any, y: any) => y.p - x.p) };
    }
  }
  await Promise.all(Object.entries(started).filter(([, mu]) => !finals.has(mu)).map(async ([eid, mu]) => {
    try {
      const d = await getJson(TD_TAB(Number(eid)));
      const m = Object.values<any>(d.attachments?.markets || {}).find((x: any) =>
        x.marketName === "Any Time Touchdown Scorer" && x.marketStatus === "OPEN");
      if (!m) return;
      const rows = (m.runners || []).filter((r: any) => r.runnerStatus === "ACTIVE" && odds(r) !== null)
        .map((r: any) => ({ desc: `${r.runnerName} TD`, kind: "td", p: r5(imp(odds(r)!)),
          odds: odds(r), market: m.marketId, sel: r.selectionId }))
        .sort((a: any, b: any) => b.p - a.p).slice(0, 6);
      (live[mu] ||= []).push(...rows);
    } catch (_) { /* a missing TD tab shouldn't sink the feed */ }
  }));
  const order: Record<string, number> = { ml: 0, spread: 1, total: 2, td: 3 };
  for (const mu in live) live[mu].sort((a, b) => order[a.kind] - order[b.kind]);
  return { asof: new Date().toISOString(), scores, live, pregame };
}

let cache: { at: number; body: string } | null = null;

Deno.serve(async (req) => {
  const origin = req.headers.get("origin") || "";
  const cors = {
    "Access-Control-Allow-Origin": ORIGINS.includes(origin) ? origin : ORIGINS[0],
    "Access-Control-Allow-Headers": "authorization, apikey, content-type",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Vary": "Origin",
  };
  if (req.method === "OPTIONS") return new Response("ok", { headers: cors });
  try {
    if (!cache || Date.now() - cache.at > 60_000)
      cache = { at: Date.now(), body: JSON.stringify(await build()) };
    return new Response(cache.body, { headers: { ...cors, "Content-Type": "application/json",
      "Cache-Control": "public, max-age=60" } });
  } catch (e) {
    return new Response(JSON.stringify({ error: String((e as Error).message || e) }),
      { status: 502, headers: { ...cors, "Content-Type": "application/json" } });
  }
});
