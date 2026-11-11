"""
Shared configuration for the Ottawa neighbourhood heat island project.

All pipeline scripts import from this module so that the study area, time
coverage, band names, and scaling constants are defined in exactly one place.

Notes
-----
- All temperature outputs are LAND SURFACE temperature (LST) in degrees Celsius.
  This is surface temperature, not air temperature.
- Rasters are written in the UTM zone of the scenes (EPSG:32618).
- Canadian spelling is used in documentation (neighbourhood, colour).
"""

from pathlib import Path

# --------------------------------------------------------------------------
# Project folders
# --------------------------------------------------------------------------
# This file lives in <project>/scripts/config.py, so the project root is its
# parent's parent.
PROJECT_ROOT = Path(__file__).resolve().parent.parent

DATA_DIR = PROJECT_ROOT / "data"
BOUNDARIES_DIR = DATA_DIR / "boundaries"
SCENES_DIR = DATA_DIR / "scenes"
OUTPUTS_DIR = PROJECT_ROOT / "outputs"

# Boundary shapefile: ONS Gen 3, City of Ottawa only, WATER REMOVED.
# Water is removed from the polygons so that water pixels do not lower
# neighbourhood means.
BOUNDARY_SHP = (
    BOUNDARIES_DIR
    / "GEN3_OTT_1_3_3_water_removed"
    / "GEN3_OTT_1_3_3_water_removed.shp"
)
# Join key and name field.
ONS_ID_FIELD = "ONS_ID"
ONS_NAME_FIELD = "ONS_Name"

# --------------------------------------------------------------------------
# STAC / data source
# --------------------------------------------------------------------------
STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"
COLLECTION = "landsat-c2-l2"

# Ottawa study-area bounding box (lon/lat, WGS84).
BBOX = [-76.35, 44.95, -75.25, 45.55]

# Only Landsat 8 and 9 (Collection 2 Level-2 also serves older platforms).
PLATFORMS = ["landsat-8", "landsat-9"]

# --------------------------------------------------------------------------
# Time coverage: summer (Jun 1 - Aug 31) for 2023, 2024, 2025.
# --------------------------------------------------------------------------
YEARS = [2023, 2024, 2025]


def summer_range(year: int) -> str:
    """Return a STAC datetime range string for the summer of `year`."""
    return f"{year}-06-01/{year}-08-31"


# --------------------------------------------------------------------------
# Cloud-cover thresholds
# --------------------------------------------------------------------------
CLOUD_THRESHOLD = 20          # preferred maximum cloud cover (percent)
CLOUD_THRESHOLD_RELAXED = 40  # fallback if a year has < MIN_SCENES usable
MIN_SCENES_PER_YEAR = 3       # relax threshold below this count
TARGET_SCENES_PER_YEAR = 6    # aim for 3-6 per year

# --------------------------------------------------------------------------
# Bands and scaling
# --------------------------------------------------------------------------
# Planetary Computer asset keys for landsat-c2-l2.
BANDS = {
    "lst": "lwir11",   # ST_B10 thermal band (surface temperature)
    "red": "red",      # SR_B4
    "nir": "nir08",    # SR_B5
    "swir1": "swir16", # SR_B6
    "qa": "qa_pixel",  # QA_PIXEL bitmask
}

# Land surface temperature (ST_B10) scaling:
#   Kelvin = DN * 0.00341802 + 149.0
#   Celsius = Kelvin - 273.15
LST_SCALE = 0.00341802
LST_OFFSET = 149.0
KELVIN_TO_C = -273.15

# Surface reflectance (SR_B*) scaling:
#   reflectance = DN * 0.0000275 - 0.2
SR_SCALE = 0.0000275
SR_OFFSET = -0.2

# --------------------------------------------------------------------------
# Output CRS
# --------------------------------------------------------------------------
OUTPUT_EPSG = 32618  # UTM zone 18N

# Approved-scene list written by Step 1 and read by Step 2.
APPROVED_SCENES_JSON = OUTPUTS_DIR / "approved_scenes.json"
SHORTLIST_CSV = OUTPUTS_DIR / "scene_shortlist.csv"

# --------------------------------------------------------------------------
# Weather reference (for the heat-wave / spread-vs-temperature analysis)
# --------------------------------------------------------------------------
# Environment and Climate Change Canada daily data, bulk download endpoint.
# Ottawa CDA RCS (Central Experimental Farm), a long-running central station.
ECCC_STATION_ID = 30578
ECCC_STATION_NAME = "Ottawa CDA RCS"
ECCC_BULK_URL = "https://climate.weather.gc.ca/climate_data/bulk_data_e.html"

# A scene date counts as a "hot day" if the station daily max air temp is at or
# above this threshold (deg C). Note: air temperature, not surface or humidex.
HOT_DAY_TMAX_C = 30.0

# Dates excluded from the heat-wave panel (QC failures).
# 2023-06-28: citywide LST of ~11 C, implausibly cold; residual cloud
# contamination that slipped the QA mask.
EXCLUDE_DATES = {"2023-06-28"}

# Heat-wave analysis outputs.
DAILY_TMAX_CSV = OUTPUTS_DIR / "ottawa_daily_tmax_summers.csv"
HEATWAVE_PANEL_CSV = OUTPUTS_DIR / "heatwave_panel.csv"
HEATWAVE_NBH_PANEL_CSV = OUTPUTS_DIR / "heatwave_neighbourhood_panel.csv"
HEATWAVE_PLOT = OUTPUTS_DIR / "heatwave_spread_vs_temp.png"

# --------------------------------------------------------------------------
# Land cover (for the developed-area exposure metrics)
# --------------------------------------------------------------------------
# ESA WorldCover 10 m (2021, v200) via Planetary Computer.
WORLDCOVER_COLLECTION = "esa-worldcover"
WORLDCOVER_YEAR = 2021
WORLDCOVER_BUILTUP_CLASS = 50  # 'Built-up'
# Cached developed-land mask on the common 30 m grid (1=developed, 0=not).
DEVELOPED_MASK_TIF = SCENES_DIR / "developed_mask_worldcover.tif"
