#!/usr/bin/env python3
"""Market-anchored sims: research harness and the distributions sim v7 uses.

Usage:  python3 board/market_model.py            # run every test, print tables
        python3 board/market_model.py --build    # write memory/market_model.json

Idea: the closing line already carries almost everything knowable
(board/residual_test.py: the Elo sims add nothing beyond it). So v7 starts
from the market's own spread and total and only adds what passes a test
here. What the market's number does NOT tell you is the SHAPE of the
outcome around it — how often a 3-point favorite wins by exactly 3, how
wide totals really scatter. That shape is what prices every alt rung.

Tests (fit on 2006-2018, graded on 2019-2026, paired bootstrap 95% CI;
adopt only when the CI excludes zero, the project's standing rule):
  1. margin shape around the closing spread: normal(sd 13.2) vs an
     empirical key-number distribution (kernel over games with a similar
     closing spread), scored by log loss on alt lines +/-0.5 to +/-10.5;
  2. total shape around the closing total: normal(sd 10, the old sims),
     normal(fitted sd), normal(sd = a + b*total), empirical kernel;
  3. weather beyond the close: do wind/temperature bins move totals
     after the closing total has priced them?
  4. results ratings beyond the close: does blending the Elo margin into
     the closing spread (weight w, fit on train) help?
"""
import csv
import io
import json
import math
import os
import random
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
GAMES_URL = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
OUT = os.path.join(BASE, "memory", "market_model.json")
TRAIN_TO, TEST_FROM = 2018, 2019
OFFSETS = [k + 0.5 for k in range(-11, 11)]      # alt lines around center
M_LO, M_HI = -70, 70
T_LO, T_HI = 0, 110


def phi(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def load():
    txt = subprocess.run(["curl", "-sSg", GAMES_URL], capture_output=True,
                         text=True, check=True).stdout
    out = []
    for r in csv.DictReader(io.StringIO(txt)):
        try:
            g = {"season": int(r["season"]), "week": int(r["week"]),
                 "s": float(r["spread_line"]), "t": float(r["total_line"]),
                 "m": int(r["result"]), "tot": int(r["total"]),
                 "roof": r["roof"], "home": r["home_team"], "away": r["away_team"],
                 "wind": float(r["wind"]) if r["wind"] else None,
                 "temp": float(r["temp"]) if r["temp"] else None}
        except (ValueError, KeyError):
            continue
        if g["season"] >= 2006:
            out.append(g)
    return out


# ------------------------------------------------ empirical distributions --
def kernel_pmf(train, key, val, center, lo, hi, h, prior_sd, prior_n):
    """PMF over integer outcomes for games whose closing line is near
    `center`: Gaussian kernel (bandwidth h) on the line, each game's
    outcome shifted by (center - its line) rounded to keep integers
    honest only when the shift is whole; half-point shifts split the
    mass between neighbours. Blended with a normal prior worth
    `prior_n` pseudo-games so thin tails stay sane."""
    size = hi - lo + 1
    pmf = [0.0] * size
    wsum = 0.0
    for g in train:
        d = g[key] - center
        w = math.exp(-0.5 * (d / h) ** 2)
        if w < 1e-4:
            continue
        x = g[val] - d
        f = math.floor(x)
        frac = x - f
        for xi, wi in ((f, 1 - frac), (f + 1, frac)):
            if wi and lo <= xi <= hi:
                pmf[int(xi) - lo] += w * wi
        wsum += w
    for i in range(size):
        k = lo + i
        pn = phi((k + 0.5 - center) / prior_sd) - phi((k - 0.5 - center) / prior_sd)
        pmf[i] = (pmf[i] + prior_n * pn) / (wsum + prior_n)
    return pmf


def p_above(pmf, lo, line):
    """P(outcome > line) for a half-point line; for a whole line the
    push mass is split (graded as half)."""
    p = 0.0
    for i, q in enumerate(pmf):
        k = lo + i
        if k > line:
            p += q
        elif k == line:
            p += q / 2
    return p


def ll(p, y):
    p = min(max(p, 1e-6), 1 - 1e-6)
    return -(math.log(p) if y else math.log(1 - p))


def boot_ci(diffs, n=2000, seed=11):
    rng = random.Random(seed)
    k = len(diffs)
    means = sorted(sum(rng.choice(diffs) for _ in range(k)) / k for _ in range(n))
    return sum(diffs) / k, means[int(0.025 * n)], means[int(0.975 * n)]


def score(test, key, val, models):
    """Per-game summed log loss over the alt lines for each model;
    returns {name: [per-game loss]}."""
    out = {name: [] for name in models}
    for g in test:
        c = g[key]
        base = math.floor(c)
        lines = [base + o for o in OFFSETS]
        for name, f in models.items():
            s = 0.0
            for L in lines:
                y = g[val] > L
                s += ll(f(g, L), y)
            out[name].append(s / len(lines))
    return out


def report(title, res, ref):
    print(f"\n{title}  (mean log loss per alt line; lower is better)")
    for name, v in res.items():
        mean = sum(v) / len(v)
        if name == ref:
            print(f"  {name:28s} {mean:.5f}  (reference)")
        else:
            d, lo, hi = boot_ci([a - b for a, b in zip(v, res[ref])])
            tag = "BETTER" if hi < 0 else "worse" if lo > 0 else "no difference"
            print(f"  {name:28s} {mean:.5f}  vs ref {d:+.5f} [{lo:+.5f}, {hi:+.5f}]  {tag}")


def fit_sd_linear(train):
    best = None
    for a in [x * 0.5 for x in range(8, 30)]:
        for b in [x * 0.01 for x in range(0, 25)]:
            nll = 0.0
            for g in train:
                sd = a + b * g["t"]
                z = (g["tot"] - g["t"]) / sd
                nll += 0.5 * z * z + math.log(sd)
            if best is None or nll < best[0]:
                best = (nll, a, b)
    return best[1], best[2]


def main():
    games = load()
    train = [g for g in games if g["season"] <= TRAIN_TO]
    test = [g for g in games if g["season"] >= TEST_FROM]
    print(f"{len(train)} training games (2006-{TRAIN_TO}), "
          f"{len(test)} test games ({TEST_FROM}-2026)")

    # 1. margin shape ----------------------------------------------------
    cache = {}
    def emp_m(g, L, h=1.0, n=40):
        k = (g["s"], h, n)
        if k not in cache:
            cache[k] = kernel_pmf(train, "s", "m", g["s"], M_LO, M_HI, h, 13.2, n)
        return p_above(cache[k], M_LO, L)
    res = score(test, "s", "m", {
        "normal sd 13.2 (sims v6)": lambda g, L: 1 - phi((L - g["s"]) / 13.2),
        "empirical key-number": emp_m,
        "empirical, wider kernel": lambda g, L: emp_m(g, L, 2.0, 40),
    })
    report("1. MARGIN around the closing spread", res, "normal sd 13.2 (sims v6)")

    # 2. total shape -----------------------------------------------------
    sd_const = math.sqrt(sum((g["tot"] - g["t"]) ** 2 for g in train) / len(train))
    a, b = fit_sd_linear(train)
    tcache = {}
    def emp_t(g, L, h=1.0, n=40):
        k = (g["t"], h, n)
        if k not in tcache:
            sd = a + b * g["t"]
            tcache[k] = kernel_pmf(train, "t", "tot", g["t"], T_LO, T_HI, h, sd, n)
        return p_above(tcache[k], T_LO, L)
    res = score(test, "t", "tot", {
        "normal sd 10 (sims v6)": lambda g, L: 1 - phi((L - g["t"]) / 10.0),
        f"normal sd {sd_const:.1f} (fitted)": lambda g, L: 1 - phi((L - g["t"]) / sd_const),
        f"normal sd {a:.1f}+{b:.2f}*total": lambda g, L: 1 - phi((L - g["t"]) / (a + b * g["t"])),
        "empirical kernel": emp_t,
    })
    report("2. TOTAL around the closing total", res, "normal sd 10 (sims v6)")
    ref2 = f"normal sd {a:.1f}+{b:.2f}*total"
    report("2b. same, against the fitted linear sd", res, ref2)

    # 3. weather beyond the close ----------------------------------------
    outdoor = lambda g: g["roof"] in ("outdoors", "open")
    def wbin(g):
        w = g["wind"]
        if not outdoor(g) or w is None:
            return None
        return "wind 0-9" if w < 10 else "wind 10-14" if w < 15 else "wind 15-19" if w < 20 else "wind 20+"
    def tbin(g):
        t = g["temp"]
        if not outdoor(g) or t is None:
            return None
        return "temp <32" if t < 32 else "temp 32-49" if t < 50 else "temp 50-79" if t < 80 else "temp 80+"
    print("\n3. WEATHER beyond the closing total (actual total minus closing total)")
    shifts = {}
    for name, fn in (("wind", wbin), ("temp", tbin)):
        bins = {}
        for g in train:
            k = fn(g)
            if k:
                bins.setdefault(k, []).append(g["tot"] - g["t"])
        for k in sorted(bins):
            v = bins[k]
            mu = sum(v) / len(v)
            se = (sum((x - mu) ** 2 for x in v) / (len(v) - 1)) ** 0.5 / len(v) ** 0.5
            sig = abs(mu) > 1.96 * se
            shifts[k] = mu if sig else 0.0
            print(f"  train {k:12s} n={len(v):4d}  {mu:+.2f} ±{1.96*se:.2f}  "
                  f"{'significant' if sig else 'noise'}")
    def shifted(g):
        return g["t"] + shifts.get(wbin(g), 0.0) + shifts.get(tbin(g), 0.0)
    res = score(test, "t", "tot", {
        "linear sd, no weather": lambda g, L: 1 - phi((L - g["t"]) / (a + b * g["t"])),
        "linear sd + train weather shifts": lambda g, L: 1 - phi((L - shifted(g)) / (a + b * g["t"])),
    })
    report("3b. weather shifts applied out of sample", res, "linear sd, no weather")

    # 4. results rating beyond the close ---------------------------------
    import tune
    rows = tune.replay(tune.load_games(), 20.0, 48.0)
    keyed = {(r["season"], r["wk"], r["home"], r["away"]): r["m"] for r in rows}
    pairs = []
    for g in games:
        k = (g["season"], g["week"], tune.ALIAS.get(g["home"], g["home"]),
             tune.ALIAS.get(g["away"], g["away"]))
        if k in keyed:
            pairs.append((g, keyed[k]))
    tr = [(g, e) for g, e in pairs if g["season"] <= TRAIN_TO]
    te = [(g, e) for g, e in pairs if g["season"] >= TEST_FROM]
    best = min((sum((g["m"] - (g["s"] + w * (e - g["s"]))) ** 2 for g, e in tr), w)
               for w in [x * 0.02 for x in range(0, 26)])
    w = best[1]
    se_close = [(g["m"] - g["s"]) ** 2 for g, e in te]
    se_blend = [(g["m"] - (g["s"] + w * (e - g["s"]))) ** 2 for g, e in te]
    d, lo, hi = boot_ci([x - y for x, y in zip(se_blend, se_close)])
    print(f"\n4. ELO beyond the close: train-optimal weight w={w:.2f}; "
          f"test squared error vs close {d:+.3f} [{lo:+.3f}, {hi:+.3f}] "
          f"({'BETTER' if hi < 0 else 'worse' if lo > 0 else 'no difference'}; "
          f"{len(te)} test games)")

    json.dump({"a": a, "b": b, "sd_const": sd_const, "weather": shifts},
              open(os.path.join(os.path.dirname(OUT), "market_model_fit.json"), "w"), indent=1)


def build():
    """Write what v7 prices rungs with: margin PMFs keyed by closing
    spread (half-point grid -24..24, home perspective), fit on every
    season through 2026, plus the total-sd fit (normal, sd = a + b*total;
    the empirical total kernel tested no better, so it isn't shipped)."""
    games = load()
    fit = json.load(open(os.path.join(os.path.dirname(OUT), "market_model_fit.json")))
    a, b = fit["a"], fit["b"]
    margin = {}
    for i in range(-48, 49):
        s = i / 2
        margin[f"{s:g}"] = [round(x, 6) for x in
                            kernel_pmf(games, "s", "m", s, M_LO, M_HI, 1.0, 13.2, 40)]
    json.dump({"built_from": f"{len(games)} games 2006-2026 (closing lines)",
               "m_lo": M_LO, "t_lo": T_LO, "sd_a": a, "sd_b": b,
               "margin": margin}, open(OUT, "w"))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    build() if "--build" in sys.argv else main()
