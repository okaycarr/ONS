"""
Weather helper: pull Environment and Climate Change Canada (ECCC) daily maximum
air temperatures for the reference station, used by the heat-wave analysis.

Runs locally (needs internet). All temperatures returned are AIR temperature
(deg C) from the station, distinct from the satellite land surface temperature.
"""

import io
import sys
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config as C  # noqa: E402


def _fetch_year(station_id: int, year: int) -> pd.DataFrame:
    params = {
        "format": "csv",
        "stationID": station_id,
        "Year": year,
        "Month": 7,
        "Day": 1,
        "timeframe": 2,  # daily
        "submit": "Download Data",
    }
    r = requests.get(C.ECCC_BULK_URL, params=params, timeout=60)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    # Column names carry a degree symbol; match loosely.
    date_col = next(c for c in df.columns if "Date/Time" in c)
    tmax_col = next(c for c in df.columns if "Max Temp" in c)
    out = df[[date_col, tmax_col]].rename(
        columns={date_col: "date", tmax_col: "tmax_c"}
    )
    out["date"] = pd.to_datetime(out["date"]).dt.date.astype(str)
    return out


def summer_daily_tmax(years=None, station_id=None) -> pd.DataFrame:
    """Return summer (Jun-Aug) daily max air temp for the given years."""
    years = years or C.YEARS
    station_id = station_id or C.ECCC_STATION_ID
    frames = []
    for y in years:
        df = _fetch_year(station_id, y)
        df["month"] = pd.to_datetime(df["date"]).dt.month
        frames.append(df[df["month"].between(6, 8)])
    all_df = pd.concat(frames, ignore_index=True).drop(columns="month")
    all_df["tmax_c"] = pd.to_numeric(all_df["tmax_c"], errors="coerce")
    return all_df.sort_values("date").reset_index(drop=True)


def load_or_fetch() -> pd.DataFrame:
    """Use the cached CSV if present, otherwise fetch and cache it."""
    if C.DAILY_TMAX_CSV.exists():
        return pd.read_csv(C.DAILY_TMAX_CSV)
    df = summer_daily_tmax()
    C.OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(C.DAILY_TMAX_CSV, index=False)
    return df


if __name__ == "__main__":
    d = summer_daily_tmax()
    d.to_csv(C.DAILY_TMAX_CSV, index=False)
    print(f"Wrote {C.DAILY_TMAX_CSV} ({len(d)} days)")
    print(d.describe())
