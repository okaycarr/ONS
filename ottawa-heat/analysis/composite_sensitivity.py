"""
Sensitivity of the 2023 to 2025 median LST composite to individual tiles.

Rebuilds the all-years composite from the cached per-scene LST tiles
(data/scenes/<scene_id>_LST_C.tif) under four settings and writes the
neighbourhood means for each:
  1. all approved tiles in the composite years, including the dates in
     config.COMPOSITE_EXCLUDE_DATES
  2. without the tile(s) of 2024-06-06
  3. without the tiles of 2024-06-06 and 2023-06-28 (replicates step2 and
     step3, which exclude both dates)
  4. all tiles, with pixels below 0 deg C set to missing

Output:
  - outputs/composite_sensitivity_by_neighbourhood.csv

Run:
    python analysis/composite_sensitivity.py
"""

import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import geopandas as gpd
import rioxarray  # noqa: F401
from rasterio.features import geometry_mask

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import config as C          # noqa: E402
import rasterlib as R       # noqa: E402
import landcoverlib as LC   # noqa: E402

SETTINGS = {
    "all_tiles": dict(exclude=(), floor=None),
    "drop_20240606": dict(exclude=("2024-06-06",), floor=None),
    "drop_20240606_20230628": dict(exclude=("2024-06-06", "2023-06-28"), floor=None),
    "floor_0c": dict(exclude=(), floor=0.0),
}


def load_tiles(template):
    approved = json.loads(C.APPROVED_SCENES_JSON.read_text())
    tiles = []
    for rec in approved:
        if int(rec["year"]) not in C.YEARS:
            continue
        p = C.SCENES_DIR / f"{rec['scene_id']}_LST_C.tif"
        da = rioxarray.open_rasterio(p, masked=True).squeeze(drop=True)
        arr = da.rio.reproject_match(template).values.astype("float32")
        tiles.append((int(rec["year"]), rec["date"], arr))
    return tiles


def composite(tiles, exclude, floor):
    by_year = {}
    for year, date, arr in tiles:
        if date in exclude:
            continue
        if floor is not None:
            arr = np.where(arr < floor, np.nan, arr)
        by_year.setdefault(year, []).append(arr)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # all-NaN pixels
        yearly = [np.nanmedian(np.stack(v, 0), axis=0)
                  for _, v in sorted(by_year.items())]
        return np.nanmedian(np.stack(yearly, 0), axis=0)


def main() -> None:
    template = R.make_template()
    affine = template.rio.transform()
    gdf = gpd.read_file(C.BOUNDARY_SHP).to_crs(template.rio.crs)
    dev = LC.build_developed_mask().values == 1
    masks = {
        int(f[C.ONS_ID_FIELD]): geometry_mask(
            [f.geometry], out_shape=template.shape, transform=affine, invert=True)
        for _, f in gdf.iterrows()
    }
    names = dict(zip(gdf[C.ONS_ID_FIELD].astype(int), gdf[C.ONS_NAME_FIELD]))
    citymask = geometry_mask(list(gdf.geometry), out_shape=template.shape,
                             transform=affine, invert=True)
    tiles = load_tiles(template)
    print(f"{len(tiles)} tiles in composite years {C.YEARS}")

    out = pd.DataFrame({C.ONS_NAME_FIELD: names})
    out.index.name = C.ONS_ID_FIELD
    for tag, kw in SETTINGS.items():
        comp = composite(tiles, **kw)
        comp_dev = np.where(dev, comp, np.nan)
        all_land, built_up = {}, {}
        for oid, m in masks.items():
            v = comp[m]
            v = v[np.isfinite(v)]
            dv = comp_dev[m]
            dv = dv[np.isfinite(dv)]
            all_land[oid] = v.mean() if v.size else np.nan
            built_up[oid] = dv.mean() if dv.size >= 10 else np.nan
        out[f"lst_mean_all_land_c_{tag}"] = pd.Series(all_land)
        out[f"lst_mean_built_up_c_{tag}"] = pd.Series(built_up)
        citywide = float(np.nanmean(np.where(citymask, comp, np.nan)))
        print(f"  {tag}: citywide mean LST {citywide:.2f} C")

    path = C.OUTPUTS_DIR / "composite_sensitivity_by_neighbourhood.csv"
    out.round(3).to_csv(path, na_rep="NA")
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
