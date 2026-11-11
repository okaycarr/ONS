"""
Step 5: Heat-wave analysis: does the between-neighbourhood surface-temperature spread
widen as the day gets hotter?

Design
------
Instead of the smoothed median composite (good for the dashboard baseline), this
builds a PER-DATE panel:
  - For each acquisition date, mosaic that date's per-scene LST tiles onto the
    common grid, then aggregate to neighbourhood-mean LST.
  - Compute the citywide mean LST and several across-neighbourhood spread
    metrics for that date.
  - Attach the station daily maximum AIR temperature for that date.
Then test whether spread increases with air temperature (and with citywide
surface temperature), and identify which neighbourhoods amplify most on hot days.

Inputs
------
  - data/scenes/<scene_id>_LST_C.tif   (written by step2_download_process.py)
  - outputs/approved_scenes.json       (all low-cloud tiles, with air_tmax_c)
  - ONS boundaries

Outputs
-------
  - outputs/heatwave_panel.csv             (one row per date)
  - outputs/heatwave_neighbourhood_panel.csv (long: date x neighbourhood LST)
  - outputs/heatwave_amplifiers.csv        (per-neighbourhood sensitivity)
  - outputs/heatwave_spread_vs_temp.png    (scatter + regression)

CAVEATS: LST is late-morning (about 11:45 local daylight time) SURFACE temperature, not afternoon air
temperature. Air temperature here is the ECCC station daily maximum.

Run:
    python scripts/step5_heatwave_panel.py
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import rioxarray  # noqa: F401
from rasterio.features import geometry_mask
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config as C          # noqa: E402
import rasterlib as R       # noqa: E402

# A neighbourhood-date is used only if at least this fraction of its pixels are
# valid (not cloud-masked / not off-tile).
MIN_VALID_FRAC = 0.5


def date_mosaic(scene_ids, template):
    """Mosaic (nanmean) the per-scene LST tiles for one date onto the grid."""
    layers = []
    for sid in scene_ids:
        p = C.SCENES_DIR / f"{sid}_LST_C.tif"
        if not p.exists():
            print(f"    missing {p.name} (run step2 first); skipping")
            continue
        da = rioxarray.open_rasterio(p, masked=True).squeeze(drop=True)
        layers.append(da.rio.reproject_match(template).values.astype("float32"))
    if not layers:
        return None
    with np.errstate(all="ignore"):
        return np.nanmean(np.stack(layers, 0), axis=0)


def neighbourhood_means(arr, gdf, affine):
    """Return {ons_id: mean_lst} for neighbourhoods meeting the valid-frac bar."""
    means = {}
    for _, feat in gdf.iterrows():
        mask = geometry_mask([feat.geometry], out_shape=arr.shape,
                             transform=affine, invert=True)
        sel = arr[mask]
        if sel.size == 0:
            continue
        valid = sel[np.isfinite(sel)]
        if valid.size / sel.size < MIN_VALID_FRAC:
            continue
        means[feat[C.ONS_ID_FIELD]] = float(valid.mean())
    return means


def main() -> None:
    if not C.APPROVED_SCENES_JSON.exists():
        print("Missing approved_scenes.json.")
        return
    approved = json.loads(C.APPROVED_SCENES_JSON.read_text())

    template = R.make_template()
    affine = template.rio.transform()
    gdf = gpd.read_file(C.BOUNDARY_SHP).to_crs(template.rio.crs)
    gdf[C.ONS_ID_FIELD] = gdf[C.ONS_ID_FIELD].astype("Int64")
    names = dict(zip(gdf[C.ONS_ID_FIELD], gdf[C.ONS_NAME_FIELD]))

    # Area-weighted city mask (all land pixels inside the city boundary).
    citymask = geometry_mask(list(gdf.geometry), out_shape=template.shape,
                             transform=affine, invert=True)

    # Group tiles by date; keep the date's air temp.
    by_date = defaultdict(list)
    air = {}          # station daily MAX air temp (afternoon)
    overpass = {}     # station air temp interpolated to the ~11:45 overpass
    for rec in approved:
        if rec["date"] in C.EXCLUDE_DATES:
            continue  # QC-failed dates (see config.EXCLUDE_DATES)
        by_date[rec["date"]].append(rec["scene_id"])
        air[rec["date"]] = rec.get("air_tmax_c")
        overpass[rec["date"]] = rec.get("overpass_air_c")

    panel_rows = []
    long_rows = []
    for d in sorted(by_date):
        arr = date_mosaic(by_date[d], template)
        if arr is None:
            continue
        means = neighbourhood_means(arr, gdf, affine)
        if len(means) < 10:
            print(f"  {d}: only {len(means)} valid neighbourhoods, skipping")
            continue
        vals = np.array(list(means.values()))
        # Area-weighted citywide baseline (pixels inside the city, each equal).
        citywide = float(np.nanmean(np.where(citymask, arr, np.nan)))
        for oid, v in means.items():
            long_rows.append({"date": d, C.ONS_ID_FIELD: oid,
                              C.ONS_NAME_FIELD: names.get(oid),
                              "lst_mean": round(v, 2),
                              "uhi_dev": round(v - citywide, 2)})
        panel_rows.append({
            "date": d,
            "year": int(d[:4]),
            "overpass_air_c": overpass.get(d),
            "air_tmax_c": air.get(d),
            "n_valid_nbh": len(means),
            "citywide_mean_lst": round(citywide, 2),
            "nbh_lst_std": round(float(vals.std(ddof=1)), 2),
            "nbh_p90_minus_p10": round(float(np.percentile(vals, 90)
                                             - np.percentile(vals, 10)), 2),
            "nbh_max_minus_min": round(float(vals.max() - vals.min()), 2),
        })

    if not panel_rows:
        print("No usable dates. Did step2 write per-scene LST tiles?")
        return

    panel = pd.DataFrame(panel_rows).sort_values("date")
    panel.to_csv(C.HEATWAVE_PANEL_CSV, index=False)
    long_df = pd.DataFrame(long_rows)
    long_df.to_csv(C.HEATWAVE_NBH_PANEL_CSV, index=False)

    # ---- regression: spread vs air temperature ----
    def regress(x, y, xlabel):
        m = np.isfinite(x) & np.isfinite(y)
        if m.sum() < 3:
            return None
        res = stats.linregress(x[m], y[m])
        print(f"  spread(std) vs {xlabel}: slope={res.slope:.3f}, "
              f"r={res.rvalue:.2f}, p={res.pvalue:.3f}, n={m.sum()}")
        return res

    print(f"Reference station: {C.ECCC_STATION_NAME}\n")
    print("Regression of across-neighbourhood LST std deviation on:")
    op_x = panel["overpass_air_c"].to_numpy(dtype=float)
    air_x = panel["air_tmax_c"].to_numpy(dtype=float)
    lst_x = panel["citywide_mean_lst"].to_numpy(dtype=float)
    std_y = panel["nbh_lst_std"].to_numpy(dtype=float)
    res_op = regress(op_x, std_y, "overpass (~11:45) AIR temp  [PRIMARY]")
    res_air = regress(air_x, std_y, "daily max AIR temp")
    regress(lst_x, std_y, "citywide mean SURFACE temp")

    # ---- per-neighbourhood amplification (UHI dev vs overpass air temp) ----
    amp = []
    for oid, grp in long_df.merge(panel[["date", "overpass_air_c"]], on="date").groupby(C.ONS_ID_FIELD):
        x = grp["overpass_air_c"].to_numpy(dtype=float)
        y = grp["uhi_dev"].to_numpy(dtype=float)
        m = np.isfinite(x) & np.isfinite(y)
        if m.sum() < 4:
            continue
        r = stats.linregress(x[m], y[m])
        amp.append({C.ONS_ID_FIELD: oid, C.ONS_NAME_FIELD: names.get(oid),
                    "n_dates": int(m.sum()),
                    "uhi_per_deg_air": round(r.slope, 3),
                    "r": round(r.rvalue, 2)})
    amp_df = pd.DataFrame(amp).sort_values("uhi_per_deg_air", ascending=False)
    amp_df.to_csv(C.OUTPUTS_DIR / "heatwave_amplifiers.csv", index=False)

    if not amp_df.empty:
        print("\nTop 5 amplifier neighbourhoods (UHI grows most per deg of air temp):")
        print(amp_df.head(5)[[C.ONS_NAME_FIELD, "uhi_per_deg_air", "r", "n_dates"]].to_string(index=False))
        print("\nTop 5 buffering neighbourhoods (UHI grows least / shrinks):")
        print(amp_df.tail(5)[[C.ONS_NAME_FIELD, "uhi_per_deg_air", "r", "n_dates"]].to_string(index=False))

    # ---- plot (spread vs overpass-time air temperature) ----
    fig, ax = plt.subplots(figsize=(8, 6))
    ax.scatter(op_x, std_y, c=panel["year"], cmap="viridis", s=60,
               edgecolor="k", zorder=3)
    for _, row in panel.iterrows():
        ax.annotate(row["date"][5:], (row["overpass_air_c"], row["nbh_lst_std"]),
                    fontsize=7, xytext=(3, 3), textcoords="offset points")
    if res_op is not None:
        xs = np.linspace(np.nanmin(op_x), np.nanmax(op_x), 50)
        ax.plot(xs, res_op.intercept + res_op.slope * xs, "r--",
                label=f"slope={res_op.slope:.3f} C/C, r={res_op.rvalue:.2f}, "
                      f"p={res_op.pvalue:.3f}")
        ax.legend()
    ax.set_xlabel("Overpass-time (~11:45) AIR temperature (deg C, station)")
    ax.set_ylabel("Across-neighbourhood LST std dev (deg C, surface)")
    ax.set_title("Does the neighbourhood surface-heat spread widen on hotter days?")
    plt.tight_layout()
    plt.savefig(C.HEATWAVE_PLOT, dpi=120)
    print(f"\nWrote {C.HEATWAVE_PANEL_CSV.name}, {C.HEATWAVE_NBH_PANEL_CSV.name}, "
          f"heatwave_amplifiers.csv, {C.HEATWAVE_PLOT.name}")
    print("\nInterpretation guide: a positive, significant slope (p<0.05) means "
          "the neighbourhood surface-heat gap widens as air temperature rises.")


if __name__ == "__main__":
    main()
