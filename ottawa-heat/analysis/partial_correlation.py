"""
Partial Spearman correlation of an ordinal or continuous predictor with
hot-day excess, controlling for mean all-land LST.

Method: rank the three variables, regress the ranks of the predictor and of
the outcome on the ranks of the control by ordinary least squares, and
correlate the residuals. The p-value uses n - 3 degrees of freedom.

Input: a CSV with one row per neighbourhood and the columns named below
(defaults match Additional file 3 of the manuscript).

Run:
    python analysis/partial_correlation.py path/to/neighbourhood_table.csv
"""

import argparse

import numpy as np
import pandas as pd
from scipy import stats

URBAN = ["downtown core", "inner urban", "outer urban", "suburban"]


def partial_spearman(x, y, z):
    rx, ry, rz = (stats.rankdata(v) for v in (x, y, z))
    ex = rx - np.polyval(np.polyfit(rz, rx, 1), rz)
    ey = ry - np.polyval(np.polyfit(rz, ry, 1), rz)
    r = float(np.corrcoef(ex, ey)[0, 1])
    n = len(x)
    t = r * np.sqrt((n - 3) / (1 - r * r))
    return r, float(2 * stats.t.sf(abs(t), n - 3)), n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--predictor", default="ons_ses_quintile_2021")
    ap.add_argument("--outcome", default="hot_day_excess_c")
    ap.add_argument("--control", default="lst_mean_all_land_c")
    ap.add_argument("--setting", default="setting")
    a = ap.parse_args()

    d = pd.read_csv(a.csv)
    samples = [("all neighbourhoods", d)]
    if a.setting in d.columns:
        samples.append(("urban settings", d[d[a.setting].isin(URBAN)]))
    for label, s in samples:
        q = s.dropna(subset=[a.predictor, a.outcome, a.control])
        rc, pc = stats.spearmanr(q[a.predictor], q[a.outcome])
        r, p, n = partial_spearman(q[a.predictor].values, q[a.outcome].values,
                                   q[a.control].values)
        print(f"{label}: n = {n}; crude rho = {rc:.2f} (p = {pc:.2g}); "
              f"partial rho = {r:.2f} (p = {p:.4f})")


if __name__ == "__main__":
    main()
