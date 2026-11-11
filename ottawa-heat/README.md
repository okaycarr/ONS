# Ottawa neighbourhood surface heat: Landsat LST pipeline

Processing scripts for summer land surface temperature (LST) by Ottawa
Neighbourhood Study (ONS) Gen 3 neighbourhood, from Landsat 8 and 9
Collection 2 Level-2 imagery.

All temperatures are land surface temperature, not air temperature.

## What the pipeline does

| Step | Script | Output |
|---|---|---|
| 1 | `scripts/step1_scene_selection.py` | Queries the Planetary Computer STAC API for summer scenes under the cloud threshold; writes a candidate shortlist and a recommended `outputs/approved_scenes.json` |
| 2 | `scripts/step2_download_process.py` | Downloads bands for approved scenes, applies the QA_PIXEL mask, computes LST, NDVI and NDBI, caches per-scene tiles, writes per-year and all-years median composites |
| 3 | `scripts/step3_aggregate.py` | Neighbourhood means over all land and over built-up land (ESA WorldCover 2021), UHI deviation, per-year means; writes `ons_heat_measures.csv` and `.gpkg` |
| 4 | `scripts/step4_qc_viz_methods.py` | QC maps, interactive map, sanity checks, `METHODS.md` |
| 5 | `scripts/step5_heatwave_panel.py` | Per-date neighbourhood LST panel, between-neighbourhood spread vs. station air temperature |

Analysis scripts that use the pipeline outputs:

| Script | Purpose |
|---|---|
| `analysis/hot_day_excess.py` | Hot-day excess per neighbourhood: mean UHI deviation on dates with a station daily maximum of 30 °C or more, minus the mean on other dates |
| `analysis/composite_sensitivity.py` | Rebuilds the composite without selected tiles, or with pixels below 0 °C set to missing, and writes the neighbourhood means for each setting |
| `analysis/partial_correlation.py` | Partial Spearman correlation of a predictor with hot-day excess, controlling for mean all-land LST |

Shared modules: `scripts/config.py` (study area, years, bands, scaling
constants, thresholds, paths), `scripts/rasterlib.py` (grid, masking,
conversions, compositing), `scripts/landcoverlib.py` (built-up mask),
`scripts/weatherlib.py` (ECCC daily maximum air temperature).

## Scene list

`outputs/approved_scenes.json` is the scene list used: 38 tiles on 23 dates
in the summers of 2023 to 2025 that passed scene selection, and 7 tiles on
4 dates in June and July 2026 (per-date panel only). Two of the 38 tiles
(2023-06-28 and 2024-06-06) are excluded from the composites after quality
control, so the composites use 36 tiles on 21 dates. Each record has the
scene ID, date, satellite, path, row, scene cloud cover, station daily
maximum air temperature and station air temperature at the overpass.
Step 1 writes a recommended list; the list in this repository is the one
that was used and can be passed directly to step 2.

## Data sources

- Landsat Collection 2 Level-2 (`landsat-c2-l2`) and ESA WorldCover 2021
  (`esa-worldcover`), through the Microsoft Planetary Computer STAC API.
- Environment and Climate Change Canada historical climate data, station
  Ottawa CDA RCS (station ID 30578).
- ONS Gen 3 neighbourhood boundaries, City of Ottawa, water removed
  (`GEN3_OTT_1_3_3_water_removed`). The boundary file is not included in
  this repository; place it in `data/boundaries/GEN3_OTT_1_3_3_water_removed/`.

## Setup and run

```
conda env create -f scripts/environment.yml
conda activate ottawa-heat
python scripts/run_all.py                    # steps 2 to 5 with the scene list in outputs/
python scripts/run_all.py --with-selection   # also run step 1 first
python analysis/hot_day_excess.py
```

Steps 1 and 2 need internet access. Per-scene products are cached in
`data/scenes/`, so later runs do not download again.

## Key parameters (scripts/config.py)

- Study bounding box (WGS84): longitude -76.35 to -75.25, latitude 44.95 to 45.55
- Output grid: EPSG:32618, 30 m
- Composite years: 2023, 2024, 2025; 1 June to 31 August
- Scene cloud cover: under 20 percent (fallback 40 percent for a year with fewer than 3 scenes)
- QA_PIXEL bits masked: 0 (fill), 1 (dilated cloud), 2 (cirrus), 3 (cloud), 4 (cloud shadow)
- LST: Kelvin = DN x 0.00341802 + 149.0; Celsius = Kelvin - 273.15
- Built-up land: ESA WorldCover class 50, majority of 10 m cells within a 30 m cell
- Per-date panel: a neighbourhood-date needs at least half its pixels valid; a date needs at least 10 valid neighbourhoods
- Hot day: station daily maximum air temperature of 30 °C or more
- Dates excluded from the composites: 2023-06-28 and 2024-06-06 (residual cloud that passed the QA_PIXEL mask)
- Date excluded from the per-date panel: 2023-06-28 (residual cloud)

## Known limitations

- Landsat thermal data are acquired at about 100 m and resampled to 30 m.
- Observations are clear-sky, late-morning (about 11:45 local daylight time) snapshots.
- The QA_PIXEL mask missed cloud in the tiles of 2023-06-28 and 2024-06-06.
  Both are excluded from the composites (`config.COMPOSITE_EXCLUDE_DATES`);
  `analysis/composite_sensitivity.py` measures the effect of the exclusion.
  Residual cloud in other tiles cannot be ruled out.
