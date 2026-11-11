"""
Step 3: Neighbourhood aggregation (run after composites look sane).

Using the all-years composites and the ONS Gen 3 boundaries (reprojected to the
raster CRS), computes per neighbourhood:
  - mean, max, 90th-percentile LST (surface, deg C)
  - mean NDVI, mean NDBI
  - percent of pixels masked (data-quality indicator)
  - UHI deviation = neighbourhood mean LST minus citywide mean LST (deg C)
  - per-year mean LST (three extra columns) for year-to-year stability

Outputs (keyed by neighbourhood ID, with name included):
  - outputs/ons_heat_measures.csv
  - outputs/ons_heat_measures.gpkg   (boundaries + measures, ArcGIS-ready)

Reports the 10 hottest and 10 coolest neighbourhoods by UHI deviation.

Run:
    python scripts/step3_aggregate.py
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import geopandas as gpd
import rioxarray  # noqa: F401
from rasterio.features import geometry_mask

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config as C          # noqa: E402
import landcoverlib as LC   # noqa: E402


def load_raster(path: Path):
    return rioxarray.open_rasterio(path, masked=True).squeeze(drop=True)


def zonal_stats(da, geom, affine):
    """Return (values_array, frac_masked) for pixels inside geom."""
    inside = geometry_mask(
        [geom], out_shape=da.shape, transform=affine, invert=True
    )
    arr = da.values
    sel = arr[inside]
    if sel.size == 0:
        return np.array([]), np.nan
    valid = sel[np.isfinite(sel)]
    frac_masked = 1.0 - (valid.size / sel.size)
    return valid, frac_masked


def main() -> None:
    lst_path = C.OUTPUTS_DIR / "lst_median_allyears.tif"
    if not lst_path.exists():
        print("Missing all-years composites. Run Step 2 first.")
        return

    lst = load_raster(lst_path)
    ndvi = load_raster(C.OUTPUTS_DIR / "ndvi_median_allyears.tif")
    ndbi = load_raster(C.OUTPUTS_DIR / "ndbi_median_allyears.tif")
    affine = lst.rio.transform()
    raster_crs = lst.rio.crs

    year_lst = {}
    for yr in C.YEARS:
        p = C.OUTPUTS_DIR / f"lst_median_{yr}.tif"
        if p.exists():
            year_lst[yr] = load_raster(p)

    # Boundaries -> raster CRS.
    gdf = gpd.read_file(C.BOUNDARY_SHP).to_crs(raster_crs)
    gdf[C.ONS_ID_FIELD] = gdf[C.ONS_ID_FIELD].astype("Int64")

    # Area-weighted citywide mean: average of all land pixels INSIDE the city
    # boundary (water already removed from the polygons), each 30 m pixel equal.
    citymask = geometry_mask(list(gdf.geometry), out_shape=lst.shape,
                             transform=affine, invert=True)
    citywide_mean = float(np.nanmean(np.where(citymask, lst.values, np.nan)))

    # Developed-land mask (ESA WorldCover built-up), aligned to the LST grid.
    # First run downloads WorldCover and caches the mask; later runs reuse it.
    print("Building/loading developed-land mask (ESA WorldCover)...")
    dev_da = LC.build_developed_mask()
    if dev_da.shape != lst.shape:
        dev_da = dev_da.rio.reproject_match(lst)
    dev = dev_da.values == 1
    lst_dev_arr = np.where(dev, lst.values, np.nan)
    citywide_mean_dev = float(
        np.nanmean(np.where(citymask, lst_dev_arr, np.nan))
    )

    rows = []
    for _, feat in gdf.iterrows():
        geom = feat.geometry
        lst_vals, frac_masked = zonal_stats(lst, geom, affine)
        ndvi_vals, _ = zonal_stats(ndvi, geom, affine)
        ndbi_vals, _ = zonal_stats(ndbi, geom, affine)

        # Developed-area (built-up) pixels only: exposure metric.
        nbh_mask = geometry_mask([geom], out_shape=lst.shape,
                                 transform=affine, invert=True)
        nbh_all = lst.values[nbh_mask]
        nbh_dev = lst_dev_arr[nbh_mask]
        dev_vals = nbh_dev[np.isfinite(nbh_dev)]
        n_pix = nbh_all.size
        pct_dev = 100 * dev[nbh_mask].mean() if n_pix else np.nan

        rec = {
            C.ONS_ID_FIELD: feat[C.ONS_ID_FIELD],
            C.ONS_NAME_FIELD: feat[C.ONS_NAME_FIELD],
            "lst_mean": np.nanmean(lst_vals) if lst_vals.size else np.nan,
            "lst_max": np.nanmax(lst_vals) if lst_vals.size else np.nan,
            "lst_p90": np.nanpercentile(lst_vals, 90) if lst_vals.size else np.nan,
            "lst_mean_dev": np.nanmean(dev_vals) if dev_vals.size >= 10 else np.nan,
            "pct_developed": round(float(pct_dev), 1) if np.isfinite(pct_dev) else np.nan,
            "ndvi_mean": np.nanmean(ndvi_vals) if ndvi_vals.size else np.nan,
            "ndbi_mean": np.nanmean(ndbi_vals) if ndbi_vals.size else np.nan,
            "pct_masked": round(100 * frac_masked, 1) if np.isfinite(frac_masked) else np.nan,
        }
        rec["uhi_deviation"] = (rec["lst_mean"] - citywide_mean
                                if np.isfinite(rec["lst_mean"]) else np.nan)
        rec["uhi_deviation_dev"] = (rec["lst_mean_dev"] - citywide_mean_dev
                                    if np.isfinite(rec["lst_mean_dev"]) else np.nan)
        for yr, da in year_lst.items():
            yv, _ = zonal_stats(da, geom, affine)
            rec[f"lst_mean_{yr}"] = np.nanmean(yv) if yv.size else np.nan
        rows.append(rec)

    df = pd.DataFrame(rows)
    # Round for readability.
    for col in df.columns:
        if col.startswith("lst") or col.startswith("uhi_deviation"):
            df[col] = df[col].round(2)
        if col.startswith("nd"):
            df[col] = df[col].round(3)

    df.to_csv(C.OUTPUTS_DIR / "ons_heat_measures.csv", index=False)

    out_gdf = gdf[[C.ONS_ID_FIELD, C.ONS_NAME_FIELD, "geometry"]].merge(
        df.drop(columns=[C.ONS_NAME_FIELD]), on=C.ONS_ID_FIELD
    )
    out_gdf.to_file(C.OUTPUTS_DIR / "ons_heat_measures.gpkg", driver="GPKG")

    print(f"Citywide mean LST (surface, all land): {citywide_mean:.2f} C")
    print(f"Citywide mean LST (developed land only): {citywide_mean_dev:.2f} C\n")
    ranked = df.dropna(subset=["uhi_deviation"]).sort_values("uhi_deviation")
    cols = [C.ONS_NAME_FIELD, "lst_mean", "uhi_deviation",
            "lst_mean_dev", "uhi_deviation_dev", "pct_developed"]
    print("10 HOTTEST neighbourhoods (by UHI deviation, whole-area):")
    print(ranked.tail(10)[cols].iloc[::-1].to_string(index=False))
    print("\n10 COOLEST neighbourhoods (by UHI deviation, whole-area):")
    print(ranked.head(10)[cols].to_string(index=False))
    # Where does the developed-area view change the ranking most?
    both = df.dropna(subset=["uhi_deviation", "uhi_deviation_dev"]).copy()
    both["rank_shift"] = (both["uhi_deviation"].rank()
                          - both["uhi_deviation_dev"].rank())
    biggest = both.reindex(both["rank_shift"].abs()
                           .sort_values(ascending=False).index).head(8)
    print("\nBiggest whole-area vs developed-area rank shifts "
          "(green space masking exposure):")
    print(biggest[[C.ONS_NAME_FIELD, "uhi_deviation", "uhi_deviation_dev",
                   "pct_developed"]].to_string(index=False))
    print("\nWrote ons_heat_measures.csv and ons_heat_measures.gpkg")


if __name__ == "__main__":
    main()
