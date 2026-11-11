"""
Step 1: Scene selection (review checkpoint).

Queries the Planetary Computer STAC API for Landsat 8/9 Collection 2 Level-2
scenes intersecting the Ottawa bbox, for summer (Jun 1 - Aug 31) of 2023, 2024,
and 2025, with cloud cover under 20 percent.

For any year with fewer than 3 usable scenes, the cloud threshold is relaxed to
40 percent for that year, and the added scenes are flagged.

It then recommends a final list of 3 to 6 scenes per year, prioritising low
cloud cover and a spread across the summer, and writes:
  - outputs/scene_shortlist.csv   (every candidate, for your review)
  - outputs/approved_scenes.json          (the recommended list; edit before Step 2)

Nothing is downloaded. Review the shortlist, adjust approved_scenes.json if you
want, then move on to Step 2.

Run:
    python scripts/step1_scene_selection.py
"""

import json
import sys

import pandas as pd
from pystac_client import Client
import planetary_computer as pc

# Allow running from anywhere: make the scripts folder importable.
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
import config as C  # noqa: E402


def open_catalog() -> Client:
    return Client.open(STAC := C.STAC_URL, modifier=pc.sign_inplace)


def query_year(catalog: Client, year: int, cloud_max: float) -> pd.DataFrame:
    """Return a DataFrame of candidate scenes for one year at a cloud threshold."""
    search = catalog.search(
        collections=[C.COLLECTION],
        bbox=C.BBOX,
        datetime=C.summer_range(year),
        query={
            "eo:cloud_cover": {"lt": cloud_max},
            "platform": {"in": C.PLATFORMS},
        },
        sortby=[{"field": "properties.datetime", "direction": "asc"}],
    )
    rows = []
    for it in search.items():
        p = it.properties
        dt = pd.to_datetime(p["datetime"])
        rows.append(
            {
                "scene_id": it.id,
                "date": dt.date().isoformat(),
                "datetime": dt,
                "year": year,
                "month": dt.month,
                "satellite": p.get("platform", ""),
                "path": p.get("landsat:wrs_path", ""),
                "row": p.get("landsat:wrs_row", ""),
                "cloud_cover": round(float(p.get("eo:cloud_cover", float("nan"))), 1),
            }
        )
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.drop_duplicates(subset="scene_id").sort_values("datetime")
    return df


def build_shortlist(catalog: Client) -> pd.DataFrame:
    """Query each year, relaxing the cloud threshold when too few scenes."""
    frames = []
    for year in C.YEARS:
        df = query_year(catalog, year, C.CLOUD_THRESHOLD)
        df["threshold_used"] = C.CLOUD_THRESHOLD
        df["relaxed"] = False

        if len(df) < C.MIN_SCENES_PER_YEAR:
            print(
                f"  {year}: only {len(df)} scene(s) under "
                f"{C.CLOUD_THRESHOLD}% cloud -> relaxing to "
                f"{C.CLOUD_THRESHOLD_RELAXED}%"
            )
            df_relaxed = query_year(catalog, year, C.CLOUD_THRESHOLD_RELAXED)
            df_relaxed["threshold_used"] = C.CLOUD_THRESHOLD_RELAXED
            # Flag scenes that only appear because of relaxation.
            strict_ids = set(df["scene_id"])
            df_relaxed["relaxed"] = ~df_relaxed["scene_id"].isin(strict_ids)
            df = df_relaxed

        frames.append(df)

    if not frames or all(f.empty for f in frames):
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def recommend(df_year: pd.DataFrame) -> pd.DataFrame:
    """
    Pick 3-6 scenes for one year: prioritise low cloud and spread across
    June/July/August.

    Strategy: take the lowest-cloud scene in each summer month first (spread),
    then fill remaining slots with the next lowest-cloud scenes overall, up to
    TARGET_SCENES_PER_YEAR.
    """
    picks = []
    by_cloud = df_year.sort_values(["cloud_cover", "datetime"])

    # One per month, lowest cloud.
    for month in (6, 7, 8):
        month_scenes = by_cloud[by_cloud["month"] == month]
        if not month_scenes.empty:
            picks.append(month_scenes.iloc[0]["scene_id"])

    # Fill up to the target with the next lowest-cloud scenes.
    for _, r in by_cloud.iterrows():
        if len(picks) >= C.TARGET_SCENES_PER_YEAR:
            break
        if r["scene_id"] not in picks:
            picks.append(r["scene_id"])

    return df_year[df_year["scene_id"].isin(picks)].sort_values("datetime")


def main() -> None:
    C.OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Querying {C.COLLECTION} over Ottawa bbox {C.BBOX}")
    print(f"Summers {C.YEARS}, cloud < {C.CLOUD_THRESHOLD}% "
          f"(relaxing to {C.CLOUD_THRESHOLD_RELAXED}% where needed)\n")

    catalog = open_catalog()
    df = build_shortlist(catalog)

    if df.empty:
        print("No scenes returned. Check network access and query parameters.")
        return

    # Save full shortlist for review.
    cols = ["year", "date", "scene_id", "satellite", "path", "row",
            "cloud_cover", "threshold_used", "relaxed"]
    df[cols].to_csv(C.SHORTLIST_CSV, index=False)

    # Print shortlist grouped by year.
    pd.set_option("display.max_rows", None, "display.width", 200)
    print("\n================ CANDIDATE SHORTLIST ================")
    for year in C.YEARS:
        dy = df[df["year"] == year]
        print(f"\n--- {year}  ({len(dy)} candidate scene(s)) ---")
        if dy.empty:
            print("  none")
            continue
        print(dy[["date", "scene_id", "satellite", "path", "row",
                  "cloud_cover", "relaxed"]].to_string(index=False))

    # Build recommendation.
    recommended = []
    print("\n================ RECOMMENDED LIST ================")
    for year in C.YEARS:
        dy = df[df["year"] == year]
        if dy.empty:
            print(f"\n--- {year}: no usable scenes ---")
            continue
        rec = recommend(dy)
        print(f"\n--- {year}  ({len(rec)} recommended) ---")
        print(rec[["date", "scene_id", "satellite", "cloud_cover",
                   "relaxed"]].to_string(index=False))
        for _, r in rec.iterrows():
            recommended.append(
                {
                    "scene_id": r["scene_id"],
                    "date": r["date"],
                    "year": int(r["year"]),
                    "satellite": r["satellite"],
                    "cloud_cover": float(r["cloud_cover"]),
                    "relaxed": bool(r["relaxed"]),
                }
            )

    with open(C.APPROVED_SCENES_JSON, "w") as f:
        json.dump(recommended, f, indent=2)

    print("\n----------------------------------------------------")
    print(f"Full shortlist : {C.SHORTLIST_CSV}")
    print(f"Recommended    : {C.APPROVED_SCENES_JSON}  ({len(recommended)} scenes)")
    print("\nReview the shortlist. Edit approved_scenes.json to add/remove scenes,")
    print("then proceed to Step 2. Nothing has been downloaded.")


if __name__ == "__main__":
    main()
