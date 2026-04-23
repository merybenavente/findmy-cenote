#!/usr/bin/env python3
"""
Compute thermal anomaly features for each cenote using Landsat 8/9 surface temperature.

Uses Microsoft Planetary Computer STAC API for Landsat Collection 2 Level 2.
Computes seasonal composites and thermal amplitude to detect cave-buffered zones.

Per cenote: lst_dry_mean, lst_amplitude, lst_anomaly
"""

import warnings
from pathlib import Path

import numpy as np

from scripts.grid_utils import DATA_DIR, load_cenotes, cenote_key, save_features

OUTPUT = DATA_DIR / "thermal_features.json"
BBOX = [-90.5, 20.0, -87.4, 21.8]

# Seasons
DRY_MONTHS = [12, 1, 2, 3]   # Dec-Mar (winter dry season)
WET_MONTHS = [6, 7, 8, 9]    # Jun-Sep (summer wet season)


def search_landsat(bbox, date_range, max_cloud=30):
    """Search for Landsat 8/9 Level 2 scenes."""
    import planetary_computer as pc
    import pystac_client

    catalog = pystac_client.Client.open(
        "https://planetarycomputer.microsoft.com/api/stac/v1",
        modifier=pc.sign_inplace,
    )

    search = catalog.search(
        collections=["landsat-c2-l2"],
        bbox=bbox,
        datetime=date_range,
        query={
            "eo:cloud_cover": {"lt": max_cloud},
            "platform": {"in": ["landsat-8", "landsat-9"]},
        },
    )

    items = list(search.items())
    print(f"  Found {len(items)} Landsat scenes for {date_range}")
    return items


def load_lst_composite(items, bbox, months_filter):
    """Load surface temperature composite from Landsat items."""
    import odc.stac

    # Filter by month
    filtered = [
        item for item in items
        if int(item.datetime.strftime("%m")) in months_filter
    ]
    print(f"  Filtered to {len(filtered)} scenes for months {months_filter}")

    if not filtered:
        return None

    # Limit scenes
    if len(filtered) > 40:
        filtered = sorted(filtered, key=lambda i: i.datetime, reverse=True)[:40]
        print(f"  Limited to 40 most recent")

    # Load ST_B10 (Surface Temperature band)
    ds = odc.stac.load(
        filtered,
        bands=["lwir11"],  # Landsat C2 L2 thermal band name
        bbox=bbox,
        resolution=100,  # 100m native resolution
        groupby="solar_day",
        chunks={"x": 1024, "y": 1024},
    )

    if "lwir11" not in ds:
        print(f"  Available bands: {list(ds.data_vars)}")
        # Try alternative band name
        for bname in ["ST_B10", "st_b10", "lwir"]:
            if bname in ds:
                ds = ds.rename({bname: "lwir11"})
                break

    if "lwir11" not in ds:
        print("  WARNING: Could not find thermal band")
        return None

    # Convert to Kelvin: scale factor 0.00341802, offset 149.0
    lst = ds["lwir11"].astype(np.float64) * 0.00341802 + 149.0

    # Filter unreasonable values
    lst = lst.where((lst > 260) & (lst < 340))

    # Median composite
    composite = lst.median(dim="time").compute()
    return composite


def compute_thermal_anomaly(lst_data, window_size_px=10):
    """Compute local thermal anomaly (z-score against 1km neighborhood)."""
    from scipy.ndimage import uniform_filter

    data = lst_data.copy()
    valid = ~np.isnan(data)
    data[~valid] = 0

    count = uniform_filter(valid.astype(float), size=window_size_px)
    count = np.maximum(count, 1e-10)

    local_mean = uniform_filter(data, size=window_size_px) / count * valid.mean()
    local_sq = uniform_filter(data**2, size=window_size_px) / count * valid.mean()
    local_std = np.sqrt(np.maximum(local_sq - local_mean**2, 0))

    anomaly = np.where(
        (local_std > 0.1) & valid,
        (lst_data - local_mean) / local_std,
        0
    )
    anomaly[~valid] = np.nan
    return anomaly


def extract_thermal_features(cenotes, lst_dry, lst_wet, lst_anomaly, transform, crs_str):
    """Extract thermal features at each cenote location."""
    from rasterio.transform import rowcol
    from rasterio.warp import transform as warp_transform

    h, w = lst_dry.shape
    results = {}

    for c in cenotes:
        lat, lon = c["lat"], c["lon"]

        if str(crs_str) != "EPSG:4326":
            xs, ys = warp_transform("EPSG:4326", str(crs_str), [lon], [lat])
            px, py = xs[0], ys[0]
        else:
            px, py = lon, lat

        try:
            row, col = rowcol(transform, px, py)
        except Exception:
            continue

        if not (0 <= row < h and 0 <= col < w):
            continue

        features = {}

        # Dry season LST (in Celsius)
        if not np.isnan(lst_dry[row, col]):
            lst_c = float(lst_dry[row, col]) - 273.15
            features["lst_dry_mean"] = round(lst_c, 2)

        # Thermal amplitude (seasonal range)
        if lst_wet is not None and not np.isnan(lst_wet[row, col]) and not np.isnan(lst_dry[row, col]):
            amplitude = float(lst_wet[row, col] - lst_dry[row, col])
            features["lst_amplitude"] = round(amplitude, 2)

        # Local anomaly
        if lst_anomaly is not None and not np.isnan(lst_anomaly[row, col]):
            features["lst_anomaly"] = round(float(lst_anomaly[row, col]), 3)

        if features:
            results[cenote_key(c)] = features

    return results


def main():
    print("=== Landsat Thermal Anomaly Analysis ===\n")

    print("Loading cenotes...")
    cenotes = load_cenotes()
    print(f"  {len(cenotes)} cenotes")

    # Search for Landsat scenes (2023-2025)
    print("\nSearching for Landsat 8/9 scenes...")
    items = search_landsat(BBOX, "2023-01-01/2025-12-31", max_cloud=25)

    if not items:
        print("ERROR: No Landsat scenes found")
        return

    # Load seasonal composites
    print("\nLoading dry-season composite (Dec-Mar)...")
    lst_dry = load_lst_composite(items, BBOX, DRY_MONTHS)

    print("\nLoading wet-season composite (Jun-Sep)...")
    lst_wet = load_lst_composite(items, BBOX, WET_MONTHS)

    if lst_dry is None:
        print("ERROR: Could not load dry-season LST")
        return

    # Convert to numpy
    lst_dry_arr = lst_dry.values if hasattr(lst_dry, 'values') else lst_dry
    lst_wet_arr = lst_wet.values if lst_wet is not None and hasattr(lst_wet, 'values') else lst_wet

    print(f"\nDry LST: mean={np.nanmean(lst_dry_arr) - 273.15:.1f}°C")
    if lst_wet_arr is not None:
        print(f"Wet LST: mean={np.nanmean(lst_wet_arr) - 273.15:.1f}°C")

    # Compute anomaly on dry-season data
    print("Computing local thermal anomaly...")
    lst_anomaly = compute_thermal_anomaly(lst_dry_arr, window_size_px=10)

    # Get spatial reference
    from rasterio.transform import from_bounds
    if hasattr(lst_dry, 'coords'):
        x = lst_dry.coords["x"].values
        y = lst_dry.coords["y"].values
        h, w = lst_dry_arr.shape
        transform = from_bounds(x.min(), y.min(), x.max(), y.max(), w, h)
        crs_str = str(lst_dry.odc.crs) if hasattr(lst_dry, "odc") else "EPSG:4326"
    else:
        h, w = lst_dry_arr.shape
        transform = from_bounds(BBOX[0], BBOX[1], BBOX[2], BBOX[3], w, h)
        crs_str = "EPSG:4326"

    # Extract features
    print("\nExtracting thermal features at cenote locations...")
    results = extract_thermal_features(
        cenotes, lst_dry_arr, lst_wet_arr, lst_anomaly, transform, crs_str
    )

    save_features(results, OUTPUT)

    if results:
        vals = list(results.values())
        temps = [v["lst_dry_mean"] for v in vals if "lst_dry_mean" in v]
        amps = [v["lst_amplitude"] for v in vals if "lst_amplitude" in v]
        anoms = [v["lst_anomaly"] for v in vals if "lst_anomaly" in v]
        print(f"\n── Summary ──")
        print(f"  Cenotes with data: {len(results)}/{len(cenotes)}")
        if temps:
            print(f"  Dry-season LST: mean={np.mean(temps):.1f}°C, std={np.std(temps):.1f}°C")
        if amps:
            print(f"  Thermal amplitude: mean={np.mean(amps):.2f}K, std={np.std(amps):.2f}K")
        if anoms:
            cold_spots = sum(1 for a in anoms if a < -1.5)
            print(f"  Cold anomalies (z<-1.5): {cold_spots}")


if __name__ == "__main__":
    main()
