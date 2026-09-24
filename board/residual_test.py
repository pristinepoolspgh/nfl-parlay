#!/usr/bin/env python3
"""Does the model carry information the closing line doesn't?

Usage:  python3 board/residual_test.py

The reviewer's test: logistic regression of the home-win outcome on
the closing line's (de-vigged, logit) probability plus the model's
residual, logit(model) − logit(market). If the residual coefficient
is significantly positive, the model adds information beyond the
market and the residuals are a bet signal. If not, the model is a
research tool and the board should say so.

Data: the same 2015–2026 scored set as backtest/tune (closing
moneylines from nflverse games.csv). Model = sim v6 margins: pure
Elo, 4-pt QB-change dock applied only in weeks 5+ (the validated
regime). Reported for weeks 5+ (primary) and all weeks 2+.
"""
import math
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tune

MARGIN_SD = 13.2
DOCK = 4.0


def logit(p):
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def phi(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def fit_logistic(X, y, iters=60):
    """IRLS for logistic regression with intercept. X: list of feature
    tuples. Returns (betas, standard errors, log-likelihood)."""
    k = len(X[0]) + 1
    b = [0.0] * k
    rows = [(1.0,) + tuple(x) for x in X]
    for _ in range(iters):
        # gradient and Hessian
        g = [0.0] * k
        H = [[0.0] * k for _ in range(k)]
        for x, yi in zip(rows, y):
            z = sum(bj * xj for bj, xj in zip(b, x))
            p = 1.0 / (1.0 + math.exp(-max(min(z, 30), -30)))
            w = p * (1 - p)
            for i in range(k):
                g[i] += (yi - p) * x[i]
                for j in range(k):
                    H[i][j] += w * x[i] * x[j]
        # solve H delta = g  (gaussian elimination)
        A = [Hrow[:] + [g[i]] for i, Hrow in enumerate(H)]
        for col in range(k):
            piv = max(range(col, k), key=lambda r: abs(A[r][col]))
            A[col], A[piv] = A[piv], A[col]
            if abs(A[col][col]) < 1e-12:
                break
            for r in range(k):
                if r != col:
                    f = A[r][col] / A[col][col]
                    for c in range(col, k + 1):
                        A[r][c] -= f * A[col][c]
        delta = [A[i][k] / A[i][i] if abs(A[i][i]) > 1e-12 else 0.0
                 for i in range(k)]
        b = [bi + di for bi, di in zip(b, delta)]
        if max(abs(d) for d in delta) < 1e-9:
            break
    # standard errors from the final Hessian inverse (diagonal)
    H = [[0.0] * k for _ in range(k)]
    ll = 0.0
    for x, yi in zip(rows, y):
        z = sum(bj * xj for bj, xj in zip(b, x))
        p = 1.0 / (1.0 + math.exp(-max(min(z, 30), -30)))
        ll += yi * math.log(max(p, 1e-12)) + (1 - yi) * math.log(max(1 - p, 1e-12))
        w = p * (1 - p)
        for i in range(k):
            for j in range(k):
                H[i][j] += w * x[i] * x[j]
    # invert H (gauss-jordan)
    A = [Hrow[:] + [1.0 if i == j else 0.0 for j in range(k)]
         for i, Hrow in enumerate(H)]
    for col in range(k):
        piv = max(range(col, k), key=lambda r: abs(A[r][col]))
        A[col], A[piv] = A[piv], A[col]
        f = A[col][col]
        for c in range(2 * k):
            A[col][c] /= f
        for r in range(k):
            if r != col:
                f = A[r][col]
                for c in range(2 * k):
                    A[r][c] -= f * A[col][c]
    se = [math.sqrt(max(A[i][k + i], 0.0)) for i in range(k)]
    return b, se, ll


def run(rows, label):
    X1, X2, y = [], [], []
    for r in rows:
        m = r["m"]
        if r["wk"] >= 5:
            if r["nh"]:
                m -= DOCK
            if r["na"]:
                m += DOCK
        lp_mkt = logit(r["pm"])
        lp_mod = logit(phi(m / MARGIN_SD))
        X1.append((lp_mkt,))
        X2.append((lp_mkt, lp_mod - lp_mkt))
        y.append(1.0 if r["actual"] > 0 else 0.0)
    b1, se1, ll1 = fit_logistic(X1, y)
    b2, se2, ll2 = fit_logistic(X2, y)
    z = b2[2] / se2[2] if se2[2] else float("nan")
    print(f"\n{label} ({len(y)} games)")
    print(f"  market-only:   beta(mkt)={b1[1]:+.3f} ±{se1[1]:.3f}  "
          f"logloss {-ll1/len(y):.4f}")
    print(f"  with residual: beta(mkt)={b2[1]:+.3f} ±{se2[1]:.3f}  "
          f"beta(resid)={b2[2]:+.3f} ±{se2[2]:.3f}  z={z:+.2f}  "
          f"logloss {-ll2/len(y):.4f}")
    lr = 2 * (ll2 - ll1)
    print(f"  likelihood-ratio stat {lr:.2f} "
          f"(>3.84 = significant at 5%, 1 df)")
    return b2, z


def main():
    games = tune.load_games()
    rows = tune.replay(games, 20.0, 48.0)
    run([r for r in rows if r["wk"] >= 5], "PRIMARY: weeks 5+ (v6 regime)")
    run(rows, "All scored weeks 2+")


if __name__ == "__main__":
    main()
