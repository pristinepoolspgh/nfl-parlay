// Parlay Board push alerts.
//   GET  ?key                         -> { publicKey } (VAPID; made on first call)
//   POST {action:"subscribe", subscription}
//   POST {action:"unsubscribe", endpoint}
//   POST {action:"test", endpoint}    -> one test alert to that phone
//   POST {action:"check"}             -> fetch the public board; if it
//        changed in a way that matters, alert every subscriber. Called by
//        pg_cron every 10 minutes; safe for anyone to call, because it only
//        ever reports what the public board already shows, once per version.
import { generateVapid, sendPush, type Sub, type Vapid } from "./webpush.ts";
import { diff, extract, type Snap } from "./diff.ts";

const BOARD = "https://nfl-parlay-inky.vercel.app/";
const ORIGINS = ["https://nfl-parlay-inky.vercel.app"];
const PUSH_HOSTS = [/\.push\.apple\.com$/, /^fcm\.googleapis\.com$/,
  /\.notify\.windows\.com$/, /^updates\.push\.services\.mozilla\.com$/,
  /\.push\.services\.mozilla\.com$/];
const MAX_SUBS = 2000;
const URL_ = Deno.env.get("SUPABASE_URL")!;
const KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;

async function db(path: string, init: RequestInit = {}) {
  const r = await fetch(`${URL_}/rest/v1/${path}`, {
    ...init,
    headers: { apikey: KEY, Authorization: `Bearer ${KEY}`,
               "Content-Type": "application/json", ...(init.headers || {}) },
  });
  if (!r.ok) throw new Error(`db ${path}: ${r.status} ${await r.text()}`);
  const t = await r.text();
  return t ? JSON.parse(t) : null;
}

async function vapid(): Promise<Vapid> {
  const rows = await db("push_keys?id=eq.1&select=*");
  if (rows.length) {
    const r = rows[0];
    return { publicKey: r.public_key, privateJwk: r.private_jwk, subject: r.subject };
  }
  const v = await generateVapid(BOARD.replace(/\/$/, ""));
  await db("push_keys?on_conflict=id", {
    method: "POST",
    headers: { Prefer: "resolution=ignore-duplicates" },
    body: JSON.stringify({ id: 1, public_key: v.publicKey,
                           private_jwk: v.privateJwk, subject: v.subject }),
  });
  const again = (await db("push_keys?id=eq.1&select=*"))[0];
  return { publicKey: again.public_key, privateJwk: again.private_jwk, subject: again.subject };
}

function quietHours(): boolean {
  const h = Number(new Intl.DateTimeFormat("en-US", { hour: "numeric", hour12: false,
    timeZone: "America/New_York" }).format(new Date()));
  return h >= 23 || h < 8;
}

async function fanout(payload: object) {
  const v = await vapid();
  const subs = await db("push_subs?select=endpoint,p256dh,auth,fails");
  let sent = 0, failed = 0, removed = 0;
  const body = JSON.stringify(payload);
  for (let i = 0; i < subs.length; i += 20) {
    await Promise.all(subs.slice(i, i + 20).map(async (s: any) => {
      const sub: Sub = { endpoint: s.endpoint, keys: { p256dh: s.p256dh, auth: s.auth } };
      const ep = encodeURIComponent(s.endpoint);
      try {
        const r = await sendPush(sub, body, v);
        if (r.ok) {
          sent++;
          await db(`push_subs?endpoint=eq.${ep}`, { method: "PATCH",
            body: JSON.stringify({ last_ok: new Date().toISOString(), fails: 0 }) });
          return;
        }
        failed++;
        if (r.status === 404 || r.status === 410 || s.fails >= 4) {
          removed++;
          await db(`push_subs?endpoint=eq.${ep}`, { method: "DELETE" });
        } else {
          await db(`push_subs?endpoint=eq.${ep}`, { method: "PATCH",
            body: JSON.stringify({ fails: s.fails + 1 }) });
        }
      } catch (_) { failed++; }
    }));
  }
  return { sent, failed, removed, subscribers: subs.length };
}

async function check(force = false) {
  if (quietHours() && !force) return { skipped: "quiet hours (11 PM-8 AM ET)" };
  const html = await (await fetch(BOARD, { headers: { "Cache-Control": "no-cache" } })).text();
  const m = html.match(/const D = (\{.*?\});\n/s);
  if (!m) return { error: "board data not found" };
  const D = JSON.parse(m[1]);
  const st = (await db("push_state?id=eq.1&select=*"))[0];
  const prev: Snap | null = st?.snap || null;
  if (st && st.generated === D.generated) return { unchanged: D.generated };
  const snap = extract(D, prev);
  const items = diff(prev, snap);
  await db("push_state?on_conflict=id", { method: "POST",
    headers: { Prefer: "resolution=merge-duplicates" },
    body: JSON.stringify({ id: 1, generated: D.generated, snap,
                           updated_at: new Date().toISOString() }) });
  if (!items.length) return { changed: D.generated, alerts: 0 };
  const more = items.length - 3;
  const payload = { title: items[0],
    body: items.slice(1, 3).join(" · ") + (more > 0 ? ` · +${more} more` : "") ||
          "Tap to see the board",
    url: "/", tag: "pb-board" };
  const res = await fanout(payload);
  await db("push_log", { method: "POST", body: JSON.stringify({
    title: payload.title, body: payload.body, sent: res.sent,
    failed: res.failed, removed: res.removed }) });
  return { changed: D.generated, items, ...res };
}

function validSub(s: any): s is Sub {
  try {
    const u = new URL(s.endpoint);
    return u.protocol === "https:" && PUSH_HOSTS.some((h) => h.test(u.hostname)) &&
      typeof s.keys?.p256dh === "string" && s.keys.p256dh.length >= 80 &&
      s.keys.p256dh.length <= 100 && typeof s.keys?.auth === "string" &&
      s.keys.auth.length >= 16 && s.keys.auth.length <= 32 && s.endpoint.length < 1000;
  } catch (_) { return false; }
}

Deno.serve(async (req) => {
  const origin = req.headers.get("origin") || "";
  const cors = {
    "Access-Control-Allow-Origin": ORIGINS.includes(origin) ? origin : ORIGINS[0],
    "Access-Control-Allow-Headers": "authorization, apikey, content-type",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Vary": "Origin",
  };
  const json = (o: unknown, status = 200) => new Response(JSON.stringify(o), {
    status, headers: { ...cors, "Content-Type": "application/json" } });
  if (req.method === "OPTIONS") return new Response("ok", { headers: cors });
  try {
    if (req.method === "GET") return json({ publicKey: (await vapid()).publicKey });
    const b = await req.json().catch(() => ({}));
    if (b.action === "subscribe") {
      const s = b.subscription;
      if (!validSub(s)) return json({ error: "bad subscription" }, 400);
      const count = await fetch(`${URL_}/rest/v1/push_subs?select=endpoint`, {
        method: "HEAD", headers: { apikey: KEY, Authorization: `Bearer ${KEY}`,
                                   Prefer: "count=exact" } });
      const n = Number((count.headers.get("content-range") || "*/0").split("/")[1]);
      if (n >= MAX_SUBS) return json({ error: "full" }, 503);
      await db("push_subs?on_conflict=endpoint", { method: "POST",
        headers: { Prefer: "resolution=merge-duplicates" },
        body: JSON.stringify({ endpoint: s.endpoint, p256dh: s.keys.p256dh,
          auth: s.keys.auth, ua: (req.headers.get("user-agent") || "").slice(0, 200),
          fails: 0 }) });
      return json({ ok: true });
    }
    if (b.action === "unsubscribe" && typeof b.endpoint === "string") {
      await db(`push_subs?endpoint=eq.${encodeURIComponent(b.endpoint)}`, { method: "DELETE" });
      return json({ ok: true });
    }
    if (b.action === "test" && typeof b.endpoint === "string") {
      const rows = await db(`push_subs?endpoint=eq.${encodeURIComponent(b.endpoint)}&select=*`);
      if (!rows.length) return json({ error: "not subscribed" }, 404);
      const s = rows[0];
      if (s.last_test && Date.now() - Date.parse(s.last_test) < 60_000)
        return json({ error: "one test a minute" }, 429);
      await db(`push_subs?endpoint=eq.${encodeURIComponent(b.endpoint)}`, { method: "PATCH",
        body: JSON.stringify({ last_test: new Date().toISOString() }) });
      const r = await sendPush({ endpoint: s.endpoint, keys: { p256dh: s.p256dh, auth: s.auth } },
        JSON.stringify({ title: "Parlay Board alerts are on",
          body: "You'll hear about QBs ruled out, upset calls, flipped favorites and big line moves.",
          url: "/", tag: "pb-test" }), await vapid());
      return json({ ok: r.ok, status: r.status }, r.ok ? 200 : 502);
    }
    if (b.action === "check") return json(await check());
    return json({ error: "unknown action" }, 400);
  } catch (e) {
    return json({ error: String((e as Error).message || e) }, 500);
  }
});
