"""
Hot-day excess per neighbourhood.

Hot-day excess = a neighbourhood's mean UHI deviation on hot days (station
daily maximum air temperature >= config.HOT_DAY_TMAX_C) minus its mean UHI
deviation on the other panel dates that have a station daily maximum.
Dates with no station daily maximum are excluded from both means.

Inputs (written by scripts/step5_heatwave_panel.py):
  - outputs/heatwave_neighbourhood_panel.csv
  - outputs/heatwave_panel.csv

Output:
  - outputs/hot_day_excess.csv

Run:
    python analysis/hot_day_excess.py
"""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import config as C  # noqa: E402


def main() -> None:
    long_df = pd.read_csv(C.HEATWAVE_NBH_PANEL_CSV)
    panel = pd.read_csv(C.HEATWAVE_PANEL_CSV)[["date", "air_tmax_c"]]
    d = long_df.merge(panel, on="date").dropna(subset=["air_tmax_c"])
    d["hot"] = d["air_tmax_c"] >= C.HOT_DAY_TMAX_C

    g = d.groupby([C.ONS_ID_FIELD, C.ONS_NAME_FIELD, "hot"])["uhi_dev"]
    wide = g.agg(["mean", "count"]).unstack("hot")
    out = pd.DataFrame({
        "mean_uhi_dev_other_days_c": wide[("mean", False)],
        "mean_uhi_dev_hot_days_c": wide[("mean", True)],
        "n_other_day_obs": wide[("count", False)],
        "n_hot_day_obs": wide[("count", True)],
    })
    out["hot_day_excess_c"] = (
        out["mean_uhi_dev_hot_days_c"] - out["mean_uhi_dev_other_days_c"]
    )
    out = out.round(3).reset_index()
    path = C.OUTPUTS_DIR / "hot_day_excess.csv"
    out.to_csv(path, index=False)
    print(f"Wrote {path} ({len(out)} neighbourhoods, "
          f"{int(d.loc[d.hot, 'date'].nunique())} hot dates, "
          f"{int(d.loc[~d.hot, 'date'].nunique())} other dates)")


if __name__ == "__main__":
    main()
