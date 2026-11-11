"""
Step 2: Download and process (run after the scene list is approved).

For each approved scene (from outputs/approved_scenes.json):
  1. Download ST_B10, SR_B4 (red), SR_B5 (NIR), SR_B6 (SWIR1) and QA_PIXEL,
     clipped to the Ottawa bbox, into data/scenes.
  2. Build a cloud/shadow/cirrus/fill mask from QA_PIXEL and apply it.
  3. Compute land surface temperature (LST) in Celsius from ST_B10.
  4. Compute NDVI and NDBI from the surface-reflectance bands.

Then composite:
  - per-year per-pixel median LST, NDVI, NDBI
  - all-years (2023-2025) median of each
All composites are written as GeoTIFFs (EPSG:32618) in outputs.

Also reports citywide min/mean/max LST per year as a sanity check, and renders
a PNG of the all-years LST composite.

NOTE: LST is SURFACE temperature, not air temperature.

Run (after `conda activate ottawa-heat`):
    python scripts/step2_download_process.py
"""

import json
import sys
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import rioxarray  # noqa: F401
from pystac_client import Client
import planetary_computer as pc

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config as C          # noqa: E402
import rasterlib as R       # noqa: E402


def open_catalog() -> Client:
    return Client.open(C.STAC_URL, modifier=pc.sign_inplace)


def get_item(catalog: Client, scene_id: str):
    """Fetch a single STAC item by id (already signed by the modifier)."""
    search = catalog.search(collections=[C.COLLECTION], ids=[scene_id])
    items = list(search.items())
    if not items:
        raise RuntimeError(f"Scene not found on STAC: {scene_id}")
    return items[0]


def load_band(item, asset_key: str):
    """Open one band, clipped to the Ottawa bbox in the scene's own CRS."""
    href = item.assets[asset_key].href
    da = rioxarray.open_rasterio(href, masked=True).squeeze(drop=True)
    # Reproject the WGS84 bbox into the raster CRS, then clip.
    from rasterio.warp import transform_bounds
    l, b, r, t = transform_bounds("EPSG:4326", da.rio.crs, *C.BBOX)
    return da.rio.clip_box(minx=l, miny=b, maxx=r, maxy=t)


def _cache_paths(scene_id: str, scenes_dir: Path):
    return {
        "lst": scenes_dir / f"{scene_id}_LST_C.tif",
        "ndvi": scenes_dir / f"{scene_id}_NDVI.tif",
        "ndbi": scenes_dir / f"{scene_id}_NDBI.tif",
    }


def load_cached(scene_id: str, scenes_dir: Path):
    """Return (lst, ndvi, ndbi) from disk if all three exist, else None."""
    paths = _cache_paths(scene_id, scenes_dir)
    if not all(p.exists() for p in paths.values()):
        return None
    def op(p):
        return rioxarray.open_rasterio(p, masked=True).squeeze(drop=True)
    return op(paths["lst"]), op(paths["ndvi"]), op(paths["ndbi"])


def process_scene(item, scene_id: str, scenes_dir: Path):
    """Download, mask, compute and cache (lst, ndvi, ndbi) for one scene."""
    qa = load_band(item, C.BANDS["qa"])
    lst_dn = load_band(item, C.BANDS["lst"])
    red_dn = load_band(item, C.BANDS["red"])
    nir_dn = load_band(item, C.BANDS["nir"])
    swir_dn = load_band(item, C.BANDS["swir1"])

    bad = R.bad_pixel_mask(qa)

    lst = R.dn_to_lst_celsius(lst_dn).where(~bad)
    red = R.dn_to_reflectance(red_dn).where(~bad)
    nir = R.dn_to_reflectance(nir_dn).where(~bad)
    swir = R.dn_to_reflectance(swir_dn).where(~bad)

    nd_vi = R.ndvi(red, nir)
    nd_bi = R.ndbi(nir, swir)

    # Cache all three per-scene products (data/scenes) for fast re-runs.
    scenes_dir.mkdir(parents=True, exist_ok=True)
    paths = _cache_paths(scene_id, scenes_dir)
    R.save_geotiff(lst, paths["lst"])
    R.save_geotiff(nd_vi, paths["ndvi"])
    R.save_geotiff(nd_bi, paths["ndbi"])
    return lst, nd_vi, nd_bi


def main() -> None:
    if not C.APPROVED_SCENES_JSON.exists():
        print(f"Missing {C.APPROVED_SCENES_JSON}. Run Step 1 and approve a "
              f"scene list first.")
        return
    approved = json.loads(C.APPROVED_SCENES_JSON.read_text())
    if not approved:
        print("approved_scenes.json is empty.")
        return

    C.OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    template = R.make_template()
    catalog = open_catalog()

    print(f"Processing {len(approved)} scene(s)...")
    # Note: composites are only built for the full summers in C.YEARS.
    # Scenes from other years (e.g. partial 2026) are still downloaded and
    # cached for the per-date heat-wave panel, but excluded from composites.
    per_year = {y: {"lst": [], "ndvi": [], "ndbi": []} for y in C.YEARS}

    for i, rec in enumerate(approved, 1):
        sid = rec["scene_id"]
        yr = int(rec["year"])
        print(f"  [{i}/{len(approved)}] {sid} ({yr}) ...", flush=True)
        try:
            cached = load_cached(sid, C.SCENES_DIR)
            if cached is not None:
                print("      (using cached per-scene products)")
                lst, nd_vi, nd_bi = cached
            else:
                item = get_item(catalog, sid)
                lst, nd_vi, nd_bi = process_scene(item, sid, C.SCENES_DIR)
            if yr in per_year:  # composite years only; others cached for panel
                per_year[yr]["lst"].append(lst)
                per_year[yr]["ndvi"].append(nd_vi)
                per_year[yr]["ndbi"].append(nd_bi)
        except Exception as e:  # keep going; report at end
            print(f"      ! failed: {e}")

    # Per-year composites.
    all_lst, all_ndvi, all_ndbi = [], [], []
    sanity = {}
    for yr in C.YEARS:
        if not per_year[yr]["lst"]:
            print(f"  {yr}: no usable scenes, skipping composite")
            continue
        lst_c = R.median_composite(per_year[yr]["lst"], template)
        ndvi_c = R.median_composite(per_year[yr]["ndvi"], template)
        ndbi_c = R.median_composite(per_year[yr]["ndbi"], template)
        R.save_geotiff(lst_c, C.OUTPUTS_DIR / f"lst_median_{yr}.tif")
        R.save_geotiff(ndvi_c, C.OUTPUTS_DIR / f"ndvi_median_{yr}.tif")
        R.save_geotiff(ndbi_c, C.OUTPUTS_DIR / f"ndbi_median_{yr}.tif")
        all_lst.append(lst_c)
        all_ndvi.append(ndvi_c)
        all_ndbi.append(ndbi_c)
        vals = lst_c.values[np.isfinite(lst_c.values)]
        sanity[yr] = (float(np.min(vals)), float(np.mean(vals)), float(np.max(vals)))

    # All-years composites (median of the per-year medians).
    if all_lst:
        lst_all = R.median_composite(all_lst, template)
        ndvi_all = R.median_composite(all_ndvi, template)
        ndbi_all = R.median_composite(all_ndbi, template)
        R.save_geotiff(lst_all, C.OUTPUTS_DIR / "lst_median_allyears.tif")
        R.save_geotiff(ndvi_all, C.OUTPUTS_DIR / "ndvi_median_allyears.tif")
        R.save_geotiff(ndbi_all, C.OUTPUTS_DIR / "ndbi_median_allyears.tif")

        # Quick render of the all-years LST composite.
        fig, ax = plt.subplots(figsize=(9, 8))
        im = lst_all.plot(ax=ax, cmap="inferno", add_colorbar=True,
                          cbar_kwargs={"label": "LST (deg C, surface)"})
        ax.set_title("All-years median land surface temperature\n"
                     "Ottawa summers 2023-2025 (surface, not air)")
        ax.set_aspect("equal")
        plt.tight_layout()
        plt.savefig(C.OUTPUTS_DIR / "lst_median_allyears.png", dpi=120)
        print("  wrote lst_median_allyears.png")

    # Sanity report.
    print("\nCitywide LST sanity check (surface temperature, deg C):")
    print(f"  {'year':<6}{'min':>8}{'mean':>8}{'max':>8}")
    for yr, (mn, me, mx) in sanity.items():
        print(f"  {yr:<6}{mn:>8.1f}{me:>8.1f}{mx:>8.1f}")
    print("\n(Ottawa summer surface temps should roughly span 15-50 C by cover type.)")
    print("Composites written to outputs/. Review the LST map before Step 3.")


if __name__ == "__main__":
    main()
