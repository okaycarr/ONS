"""
Step 4: QC, visualization, and methods summary.

1. Static QC choropleths (PNG) in outputs: mean LST, UHI deviation, NDVI, NDBI
   by neighbourhood, plus the LST raster with neighbourhood boundaries overlaid.
2. Interactive HTML choropleth (folium) with a layer per measure and hover
   tooltips showing neighbourhood name and values.
3. Sanity checks: hot/cool patterns, NDVI-LST and NDBI-LST correlations,
   per-year LST rank stability.
4. outputs/METHODS.md documenting sources, scenes, steps, formulas, masking,
   the surface-vs-air caveat, and known limitations.

Run:
    python scripts/step4_qc_viz_methods.py
"""

import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import rioxarray  # noqa: F401

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config as C  # noqa: E402

MEASURES = {
    "lst_mean": ("Mean land surface temperature (deg C, surface)", "inferno"),
    "uhi_deviation": ("UHI deviation from citywide mean (deg C)", "RdBu_r"),
    "lst_mean_dev": ("Mean LST, developed land only (deg C, surface)", "inferno"),
    "uhi_deviation_dev": ("UHI deviation, developed land only (deg C)", "RdBu_r"),
    "ndvi_mean": ("Mean NDVI (greenness)", "YlGn"),
    "ndbi_mean": ("Mean NDBI (built-up)", "OrRd"),
}


def static_maps(gdf):
    for col, (label, cmap) in MEASURES.items():
        if col not in gdf.columns:
            print(f"  ! column {col} not in geopackage; re-run step3 first")
            continue
        fig, ax = plt.subplots(figsize=(10, 8))
        gdf.plot(column=col, cmap=cmap, legend=True, ax=ax,
                 legend_kwds={"label": label, "shrink": 0.6},
                 missing_kwds={"color": "lightgrey", "label": "no data"})
        ax.set_title(f"Ottawa neighbourhoods: {label}")
        ax.set_axis_off()
        plt.tight_layout()
        plt.savefig(C.OUTPUTS_DIR / f"map_{col}.png", dpi=120)
        plt.close(fig)


def raster_overlay(gdf):
    """High-detail LST raster clipped to the city, boundaries overlaid, so
    hotspots WITHIN each neighbourhood are visible."""
    lst_path = C.OUTPUTS_DIR / "lst_median_allyears.tif"
    if not lst_path.exists():
        return
    lst = rioxarray.open_rasterio(lst_path, masked=True).squeeze(drop=True)
    # Clip to city land (water already removed from polygons).
    lst_city = lst.rio.clip(gdf.geometry, gdf.crs, drop=True)
    lst_city.rio.to_raster(C.OUTPUTS_DIR / "lst_median_allyears_ottawa.tif",
                           driver="GTiff", compress="deflate")

    vals = lst_city.values[np.isfinite(lst_city.values)]
    vmin, vmax = np.percentile(vals, 2), np.percentile(vals, 98)

    fig, ax = plt.subplots(figsize=(15, 12))
    im = lst_city.plot(ax=ax, cmap="inferno", vmin=vmin, vmax=vmax,
                       add_colorbar=True,
                       cbar_kwargs={"label": "LST (deg C, surface)", "shrink": 0.6})
    gdf.boundary.plot(ax=ax, color="white", linewidth=0.6)
    ax.set_title("Ottawa land surface temperature (all-years median)\n"
                 "hotspots within neighbourhoods; contrast stretched 2-98 pct")
    ax.set_aspect("equal")
    ax.set_axis_off()
    plt.tight_layout()
    plt.savefig(C.OUTPUTS_DIR / "map_lst_hotspots_within_neighbourhoods.png",
                dpi=200)
    plt.close(fig)


def interactive_map(gdf):
    import folium

    g4326 = gdf.to_crs(4326)
    centre = [g4326.geometry.centroid.y.mean(), g4326.geometry.centroid.x.mean()]
    m = folium.Map(location=centre, zoom_start=10, tiles="cartodbpositron")

    for col, (label, cmap) in MEASURES.items():
        show = col == "lst_mean"
        folium.Choropleth(
            geo_data=g4326.__geo_interface__,
            data=g4326,
            columns=[C.ONS_ID_FIELD, col],
            key_on=f"feature.properties.{C.ONS_ID_FIELD}",
            fill_color={"inferno": "YlOrRd", "RdBu_r": "RdBu",
                        "YlGn": "YlGn", "OrRd": "OrRd"}.get(cmap, "YlOrRd"),
            nan_fill_color="lightgrey",
            legend_name=label,
            name=label,
            show=show,
        ).add_to(m)

    tooltip = folium.GeoJson(
        g4326,
        name="Neighbourhood details",
        style_function=lambda x: {"fillOpacity": 0, "color": "transparent"},
        tooltip=folium.GeoJsonTooltip(
            fields=[C.ONS_NAME_FIELD, "lst_mean", "uhi_deviation",
                    "lst_mean_dev", "uhi_deviation_dev", "pct_developed",
                    "ndvi_mean", "ndbi_mean", "pct_masked"],
            aliases=["Neighbourhood", "Mean LST (C)", "UHI dev (C)",
                     "Mean LST developed (C)", "UHI dev developed (C)",
                     "% developed", "NDVI", "NDBI", "% masked"],
            localize=True,
        ),
    )
    tooltip.add_to(m)
    try:
        _add_lst_raster_overlay(m, gdf)
    except Exception as e:
        print(f"  ! raster overlay failed: {e}")
    folium.LayerControl(collapsed=False).add_to(m)
    m.save(str(C.OUTPUTS_DIR / "ottawa_heat_interactive.html"))


def _add_lst_raster_overlay(m, gdf):
    """Add the LST raster as a toggleable image layer so users can see
    hotspots within neighbourhoods, plus a colour legend."""
    import folium
    import branca.colormap as bcm

    lst_path = C.OUTPUTS_DIR / "lst_median_allyears.tif"
    if not lst_path.exists():
        return
    lst = rioxarray.open_rasterio(lst_path, masked=True).squeeze(drop=True)
    lst_city = lst.rio.clip(gdf.geometry, gdf.crs, drop=True).rio.reproject("EPSG:4326")
    arr = lst_city.values.astype("float32")
    finite = np.isfinite(arr)
    vmin, vmax = np.percentile(arr[finite], 2), np.percentile(arr[finite], 98)
    norm = np.clip((arr - vmin) / (vmax - vmin), 0, 1)
    cmap = plt.get_cmap("inferno")
    rgba = cmap(norm)
    rgba[..., 3] = np.where(finite, 0.75, 0.0)

    left, bottom, right, top = lst_city.rio.bounds()
    folium.raster_layers.ImageOverlay(
        image=rgba, bounds=[[bottom, left], [top, right]],
        opacity=0.75, name="LST hotspots (raster)", show=False,
    ).add_to(m)
    bcm.LinearColormap(
        [tuple(int(c * 255) for c in cmap(x)[:3]) for x in np.linspace(0, 1, 6)],
        vmin=round(float(vmin), 1), vmax=round(float(vmax), 1),
        caption="LST hotspots (deg C, surface)",
    ).add_to(m)


def sanity_checks(df):
    lines = []
    d = df.dropna(subset=["lst_mean", "ndvi_mean", "ndbi_mean"])
    r_ndvi = d["ndvi_mean"].corr(d["lst_mean"])
    r_ndbi = d["ndbi_mean"].corr(d["lst_mean"])
    lines.append(f"NDVI vs LST correlation: {r_ndvi:+.2f} "
                 f"(expected negative)")
    lines.append(f"NDBI vs LST correlation: {r_ndbi:+.2f} "
                 f"(expected positive)")

    # Per-year rank stability.
    yr_cols = [f"lst_mean_{y}" for y in C.YEARS if f"lst_mean_{y}" in df.columns]
    if len(yr_cols) >= 2:
        ranks = df[yr_cols].rank()
        corr = ranks.corr(method="spearman")
        pairs = []
        for i in range(len(yr_cols)):
            for j in range(i + 1, len(yr_cols)):
                pairs.append(f"{yr_cols[i][-4:]}~{yr_cols[j][-4:]}: "
                             f"{corr.iloc[i, j]:.2f}")
        lines.append("Per-year LST rank correlation (Spearman): " + ", ".join(pairs))

    # Named-area spot checks (best-effort substring match on ONS_Name).
    def rank_of(sub):
        hit = df[df[C.ONS_NAME_FIELD].str.contains(sub, case=False, na=False)]
        if hit.empty:
            return None
        val = hit["uhi_deviation"].mean()
        return round(float(val), 2)

    for area in ["DOWNTOWN", "VANIER", "GREENBELT", "ROCKCLIFFE"]:
        v = rank_of(area)
        if v is not None:
            lines.append(f"  {area}: mean UHI deviation {v:+.2f} C")
    return lines


def write_methods(df, sanity_lines, approved):
    in_window = [s for s in (approved or []) if int(s["year"]) in C.YEARS]
    used = [s for s in in_window if s["date"] not in C.COMPOSITE_EXCLUDE_DATES]
    excluded = [s for s in in_window if s["date"] in C.COMPOSITE_EXCLUDE_DATES]
    n_scenes = len(used)
    scene_lines = "\n".join(
        f"  - {s['scene_id']} ({s['date']}, {s['satellite']}, "
        f"cloud {s['cloud_cover']}%)" for s in used
    )
    excluded_lines = "\n".join(
        f"  - {s['scene_id']} ({s['date']}, {s['satellite']}, "
        f"cloud {s['cloud_cover']}%)" for s in excluded
    ) or "  - none"
    text = f"""# Methods: Ottawa neighbourhood heat island & greenness

Accessed: {date.today().isoformat()}

## Data sources
- Landsat 8/9 Collection 2 Level-2 surface temperature and surface reflectance,
  via the Microsoft Planetary Computer STAC API (collection `landsat-c2-l2`).
- Ottawa Neighbourhood Study (ONS) Gen 3 boundaries, City of Ottawa only,
  water removed (`{C.BOUNDARY_SHP.stem}`), {len(df)} neighbourhoods.
  Join key: `{C.ONS_ID_FIELD}`.

## Scenes used in the composites ({n_scenes})
{scene_lines}

## Scenes excluded from the composites after quality control ({len(excluded)})
These passed the scene-level cloud filter, but the QA_PIXEL mask missed cloud
(see `config.COMPOSITE_EXCLUDE_DATES`).
{excluded_lines}

## Time coverage
Summer (1 June - 31 August) of 2023, 2024 and 2025.

## Processing steps
1. For each scene, download ST_B10, SR_B4, SR_B5, SR_B6 and QA_PIXEL, clipped
   to the study bbox {C.BBOX}.
2. Mask fill, cloud, dilated cloud, cirrus and cloud shadow using QA_PIXEL bit
   flags (bits 0-4) before any computation.
3. Convert ST_B10 to land surface temperature (LST) in Celsius:
   Kelvin = DN * {C.LST_SCALE} + {C.LST_OFFSET}; Celsius = Kelvin - 273.15.
4. Convert surface reflectance: reflectance = DN * {C.SR_SCALE} + ({C.SR_OFFSET}).
   NDVI = (NIR - Red)/(NIR + Red); NDBI = (SWIR1 - NIR)/(SWIR1 + NIR).
5. Composite per-pixel median per year, and an all-years median, on a common
   EPSG:{C.OUTPUT_EPSG} 30 m grid.
6. Aggregate to neighbourhoods (reprojected to the raster CRS): mean/max/p90
   LST, mean NDVI, mean NDBI, percent masked, and UHI deviation
   (neighbourhood mean LST minus citywide mean LST). The citywide baseline is
   area-weighted: the mean of all 30 m land pixels inside the city boundary.
7. Developed-area exposure metrics: a second LST mean and UHI deviation
   restricted to built-up land (ESA WorldCover 2021 v200 10 m, class 50,
   majority-resampled to the 30 m grid), so forests, cropland and other
   largely unoccupied land within a neighbourhood do not dilute the heat
   experienced where people live and work. `pct_developed` reports the share
   of each neighbourhood's land that is built-up; developed-area means are
   suppressed where fewer than 10 developed pixels exist.

## Sanity checks
{chr(10).join('- ' + s for s in sanity_lines)}

## IMPORTANT caveat: surface vs air temperature
All temperatures here are LAND SURFACE temperature (LST), derived from the
thermal band. This is the radiative temperature of the ground/roofs/canopy, not
the 2 m air temperature people experience. Surface temperatures are typically
warmer than air temperature on sunny days and vary strongly by surface type.

## Known limitations
- Landsat thermal is acquired at ~100 m and resampled to 30 m; fine detail is
  smoothed.
- Clear-sky bias: cloud masking keeps only clear pixels, so composites reflect
  clear-sky conditions.
- Snapshot timing: Landsat overpass is about 11:45 local daylight time; this does not capture
  afternoon peak heat or night-time heat retention.
- Median compositing reduces but does not eliminate residual cloud/haze effects.
  Tiles with residual cloud found in quality control are excluded by date.
"""
    (C.OUTPUTS_DIR / "METHODS.md").write_text(text)


def main() -> None:
    gpkg = C.OUTPUTS_DIR / "ons_heat_measures.gpkg"
    if not gpkg.exists():
        print("Missing ons_heat_measures.gpkg. Run Step 3 first.")
        return
    gdf = gpd.read_file(gpkg)
    df = pd.read_csv(C.OUTPUTS_DIR / "ons_heat_measures.csv")
    approved = (json.loads(C.APPROVED_SCENES_JSON.read_text())
                if C.APPROVED_SCENES_JSON.exists() else [])

    static_maps(gdf)
    raster_overlay(gdf)
    try:
        interactive_map(gdf)
    except Exception as e:
        print(f"  ! interactive map failed: {e}")

    sanity_lines = sanity_checks(df)
    write_methods(df, sanity_lines, approved)

    print("Sanity checks:")
    for s in sanity_lines:
        print("  " + s)

    print("\nFiles in outputs:")
    for p in sorted(C.OUTPUTS_DIR.iterdir()):
        print("  " + p.name)


if __name__ == "__main__":
    main()
