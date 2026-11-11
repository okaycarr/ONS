"""
Shared raster helpers for the Ottawa heat island pipeline.

Kept separate from config.py so the numeric/geospatial logic is testable and
reused by Step 2 (processing) and Step 3/4 (aggregation, QC).
"""

import math

import numpy as np
import xarray as xr
import rioxarray  # noqa: F401  (registers .rio accessor)
import rasterio
from rasterio.warp import transform_bounds

import config as C


# --------------------------------------------------------------------------
# Common target grid (EPSG:32618, 30 m) covering the Ottawa bbox
# --------------------------------------------------------------------------
def make_template(res: int = 30) -> xr.DataArray:
    """Empty DataArray defining the common output grid for all composites."""
    left, bottom, right, top = transform_bounds(
        "EPSG:4326", f"EPSG:{C.OUTPUT_EPSG}", *C.BBOX
    )
    left = math.floor(left / res) * res
    bottom = math.floor(bottom / res) * res
    right = math.ceil(right / res) * res
    top = math.ceil(top / res) * res

    width = int((right - left) / res)
    height = int((top - bottom) / res)
    transform = rasterio.transform.from_origin(left, top, res, res)

    xs = left + res / 2 + res * np.arange(width)
    ys = top - res / 2 - res * np.arange(height)
    da = xr.DataArray(
        np.full((height, width), np.nan, dtype="float32"),
        dims=("y", "x"),
        coords={"y": ys, "x": xs},
    )
    da.rio.write_crs(C.OUTPUT_EPSG, inplace=True)
    da.rio.write_transform(transform, inplace=True)
    da.rio.write_nodata(np.nan, inplace=True)
    return da


# --------------------------------------------------------------------------
# QA_PIXEL mask (Landsat Collection 2 Level-2 bit flags)
# --------------------------------------------------------------------------
# bit 0 fill, bit 1 dilated cloud, bit 2 cirrus, bit 3 cloud, bit 4 cloud shadow
_QA_BITS_TO_MASK = [0, 1, 2, 3, 4]
_QA_MASK_VALUE = sum(1 << b for b in _QA_BITS_TO_MASK)


def bad_pixel_mask(qa: xr.DataArray) -> xr.DataArray:
    """True where a pixel should be discarded (fill/cloud/shadow/cirrus)."""
    qa_int = qa.fillna(1).astype("uint16")  # NaN -> treat as fill
    return (qa_int & _QA_MASK_VALUE) != 0


# --------------------------------------------------------------------------
# Physical conversions
# --------------------------------------------------------------------------
def dn_to_lst_celsius(st_b10: xr.DataArray) -> xr.DataArray:
    """ST_B10 digital numbers -> land surface temperature in Celsius."""
    kelvin = st_b10 * C.LST_SCALE + C.LST_OFFSET
    return kelvin + C.KELVIN_TO_C


def dn_to_reflectance(sr: xr.DataArray) -> xr.DataArray:
    """Surface reflectance DN -> reflectance (0-1)."""
    return sr * C.SR_SCALE + C.SR_OFFSET


def ndvi(red: xr.DataArray, nir: xr.DataArray) -> xr.DataArray:
    # Use arithmetic + .where (method form) so the rio CRS/coords are preserved.
    denom = nir + red
    out = (nir - red) / denom
    out = out.where(denom != 0)
    out.rio.write_crs(red.rio.crs, inplace=True)
    return out


def ndbi(nir: xr.DataArray, swir1: xr.DataArray) -> xr.DataArray:
    denom = swir1 + nir
    out = (swir1 - nir) / denom
    out = out.where(denom != 0)
    out.rio.write_crs(nir.rio.crs, inplace=True)
    return out


# --------------------------------------------------------------------------
# Median compositing on the common grid
# --------------------------------------------------------------------------
def median_composite(layers, template: xr.DataArray) -> xr.DataArray:
    """
    Per-pixel median across a list of DataArrays, each first reprojected onto
    the common template grid. NaNs (masked/no-data) are ignored.
    """
    aligned = []
    for da in layers:
        matched = da.rio.reproject_match(template)
        aligned.append(matched.values.astype("float32"))
    stack = np.stack(aligned, axis=0)
    with np.errstate(all="ignore"):
        med = np.nanmedian(stack, axis=0)
    out = template.copy()
    out.values = med.astype("float32")
    return out


def save_geotiff(da: xr.DataArray, path) -> None:
    da.rio.write_nodata(np.nan, inplace=True)
    da.rio.to_raster(path, driver="GTiff", compress="deflate")
