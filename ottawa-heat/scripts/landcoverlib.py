"""
Land-cover helper: build a 'developed land' mask from ESA WorldCover 10 m
(2021, v200) on the project's common 30 m grid.

Used for the developed-area LST exposure metrics: the heat where people
actually live and work, excluding forests, cropland, wetlands and other
largely unoccupied land within a neighbourhood.

WorldCover class map (v200): 10 tree cover, 20 shrubland, 30 grassland,
40 cropland, 50 built-up, 60 bare/sparse, 70 snow/ice, 80 water,
90 herbaceous wetland, 95 mangroves, 100 moss/lichen.

We call a 30 m pixel 'developed' if the majority of overlapping 10 m
WorldCover pixels are class 50 (built-up). Runs locally (needs network) the
first time; the result is cached as a GeoTIFF and reused afterwards.
"""

import sys
from pathlib import Path

import numpy as np
import rioxarray
from pystac_client import Client
import planetary_computer as pc

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config as C          # noqa: E402
import rasterlib as R       # noqa: E402


def _fetch_worldcover_items():
    catalog = Client.open(C.STAC_URL, modifier=pc.sign_inplace)
    search = catalog.search(
        collections=[C.WORLDCOVER_COLLECTION],
        bbox=C.BBOX,
        datetime=f"{C.WORLDCOVER_YEAR}-01-01/{C.WORLDCOVER_YEAR}-12-31",
    )
    items = list(search.items())
    if not items:
        raise RuntimeError("No WorldCover items found for the study bbox.")
    return items


def build_developed_mask(force: bool = False):
    """
    Return the developed-land mask (xr.DataArray of 1/0 on the common grid).
    Cached at C.DEVELOPED_MASK_TIF.
    """
    if C.DEVELOPED_MASK_TIF.exists() and not force:
        return rioxarray.open_rasterio(
            C.DEVELOPED_MASK_TIF, masked=True
        ).squeeze(drop=True)

    template = R.make_template()
    items = _fetch_worldcover_items()
    print(f"  WorldCover: {len(items)} tile(s) cover the bbox")

    # Fraction of built-up per 30 m cell: average of the binary 10 m built-up
    # layer, resampled to the template grid.
    from rasterio.enums import Resampling
    from rasterio.warp import transform_bounds

    fractions = []
    for it in items:
        href = it.assets["map"].href
        da = rioxarray.open_rasterio(href, masked=True).squeeze(drop=True)
        l, b, r_, t = transform_bounds("EPSG:4326", da.rio.crs, *C.BBOX)
        try:
            da = da.rio.clip_box(minx=l, miny=b, maxx=r_, maxy=t)
        except Exception:
            continue  # tile may only graze the bbox
        builtup = (da == C.WORLDCOVER_BUILTUP_CLASS).astype("float32")
        builtup.rio.write_crs(da.rio.crs, inplace=True)
        builtup.rio.write_nodata(np.nan, inplace=True)
        frac = builtup.rio.reproject_match(template, resampling=Resampling.average)
        fractions.append(frac.values.astype("float32"))

    if not fractions:
        raise RuntimeError("No WorldCover data overlapped the bbox.")

    with np.errstate(all="ignore"):
        frac = np.nanmax(np.stack(fractions, 0), axis=0)

    mask = template.copy()
    mask.values = (frac >= 0.5).astype("float32")  # majority built-up
    C.SCENES_DIR.mkdir(parents=True, exist_ok=True)
    R.save_geotiff(mask, C.DEVELOPED_MASK_TIF)
    pct = 100 * float(np.nanmean(mask.values))
    print(f"  developed-land mask cached ({pct:.1f}% of bbox developed)")
    return mask


if __name__ == "__main__":
    build_developed_mask(force=True)
