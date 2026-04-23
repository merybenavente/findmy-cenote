#!/usr/bin/env python3
"""
Compute population/settlement density features for each cenote.

Uses WorldPop population density rasters (free, ~100m resolution).
Downloads the Mexico 2020 population count raster.

Per cenote at 1km/5km: pop_1km, pop_5km, settled_fraction_1km
"""

import math
import os
import urllib.request
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import rowcol

from scripts.grid_utils import DATA_DIR, load_cenotes, cenote_key, save_features

OUTPUT = DATA_DIR / "population_features.json"
POP_RASTER = DATA_DIR / "worldpop_mexico_2020.tif"

# WorldPop Mexico 2020 constrained individual countries dataset (~100m)
WORLDPOP_URL = "https://data.worldpop.org/GIS/Population/Global_2000_2020_Constrained/2020/maxar_v1/MEX/mex_ppp_2020_constrained.tif"

# Study area bbox for cropping
BBOX = [-90.5, 20.0, -87.4, 21.8]


def download_population_raster():
    """Download WorldPop Mexico raster if not present."""
    if POP_RASTER.exists():
        print(f"  Population raster already exists: {POP_RASTER}")
        return

    print(f"  Downloading WorldPop Mexico 2020...")
    print(f"  URL: {WORLDPOP_URL}")
    print(f"  This may take a few minutes (~200MB)...")

    try:
        urllib.request.urlretrieve(WORLDPOP_URL, POP_RASTER)
        print(f"  Saved: {POP_RASTER}")
    except Exception as e:
        print(f"  Download failed: {e}")
        print("  Trying alternative: WorldPop UN-adjusted...")
        alt_url = "https://data.worldpop.org/GIS/Population/Global_2000_2020/2020/MEX/mex_ppp_2020.tif"
        try:
            urllib.request.urlretrieve(alt_url, POP_RASTER)
            print(f"  Saved: {POP_RASTER}")
        except Exception as e2:
            print(f"  Alternative also failed: {e2}")
            raise


def extract_population_features(cenotes, pop_src):
    """Extract population stats within 1km and 5km of each cenote."""
    results = {}

    # Get resolution in meters (approx for geographic CRS)
    res_deg = abs(pop_src.transform.a)  # degrees per pixel
    res_m = res_deg * 111000  # approximate meters at equator

    pop_data = pop_src.read(1).astype(np.float64)
    nodata = pop_src.nodata
    if nodata is not None:
        pop_data[pop_data == nodata] = 0
    pop_data[pop_data < 0] = 0
    pop_data[np.isnan(pop_data)] = 0

    for i, c in enumerate(cenotes):
        lat, lon = c["lat"], c["lon"]

        try:
            row, col = rowcol(pop_src.transform, lon, lat)
        except Exception:
            continue

        if not (0 <= row < pop_src.height and 0 <= col < pop_src.width):
            continue

        features = {}

        for radius_m, key_suffix in [(1000, "1km"), (5000, "5km")]:
            buf_px = int(radius_m / res_m) + 2
            r0 = max(0, row - buf_px)
            r1 = min(pop_src.height, row + buf_px + 1)
            c0 = max(0, col - buf_px)
            c1 = min(pop_src.width, col + buf_px + 1)

            patch = pop_data[r0:r1, c0:c1]

            # Distance mask
            ri = np.arange(patch.shape[0])
            ci = np.arange(patch.shape[1])
            cg, rg = np.meshgrid(ci, ri)
            lr = row - r0
            lc = col - c0

            # Convert pixel distance to meters
            cos_lat = math.cos(math.radians(lat))
            dist_y = (rg - lr) * res_deg * 111000  # meters N-S
            dist_x = (cg - lc) * res_deg * 111000 * cos_lat  # meters E-W
            dist = np.sqrt(dist_x**2 + dist_y**2)

            mask = dist <= radius_m
            pop_in_circle = patch[mask]

            features[f"pop_{key_suffix}"] = round(float(np.sum(pop_in_circle)), 0)

            if key_suffix == "1km":
                # Settled fraction: proportion of pixels with any population
                settled = np.sum(pop_in_circle > 0.1)
                total = mask.sum()
                features["settled_fraction_1km"] = round(float(settled / total), 4) if total > 0 else 0.0

        results[cenote_key(c)] = features

        if (i + 1) % 200 == 0:
            print(f"  {i+1}/{len(cenotes)}")

    return results


def main():
    print("=== Population Density Analysis ===\n")

    print("Loading cenotes...")
    cenotes = load_cenotes()
    print(f"  {len(cenotes)} cenotes")

    print("\nChecking population raster...")
    download_population_raster()

    print("\nOpening population raster...")
    with rasterio.open(POP_RASTER) as pop_src:
        print(f"  Shape: {pop_src.width}x{pop_src.height}")
        print(f"  Resolution: ~{abs(pop_src.transform.a) * 111000:.0f}m")
        print(f"  CRS: {pop_src.crs}")

        print("\nExtracting population features...")
        results = extract_population_features(cenotes, pop_src)

    save_features(results, OUTPUT)

    if results:
        vals = list(results.values())
        pop1 = [v["pop_1km"] for v in vals if "pop_1km" in v]
        pop5 = [v["pop_5km"] for v in vals if "pop_5km" in v]
        stl = [v["settled_fraction_1km"] for v in vals if "settled_fraction_1km" in v]
        print(f"\n── Summary ──")
        print(f"  Cenotes with data: {len(results)}/{len(cenotes)}")
        if pop1:
            zero_pop = sum(1 for p in pop1 if p == 0)
            print(f"  Pop within 1km: mean={np.mean(pop1):.0f}, median={np.median(pop1):.0f}")
            print(f"  Cenotes with zero pop @1km: {zero_pop}/{len(pop1)} ({100*zero_pop/len(pop1):.0f}%)")
        if stl:
            unsettled = sum(1 for s in stl if s == 0)
            print(f"  Fully unsettled @1km: {unsettled}/{len(stl)} ({100*unsettled/len(stl):.0f}%)")


if __name__ == "__main__":
    main()
