#!/usr/bin/env python3
"""
Compute canopy height features for each cenote using Meta/WRI Global Canopy Height (1m).

Data source: AWS S3 s3://dataforgood-fb-data/forests/v1/alsgedi_global_v6_float/
No auth needed (--no-sign-request).

Per cenote at 100m radius: canopy_mean, canopy_min, canopy_std, canopy_gap_fraction
"""

import json
import os
import subprocess
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import rowcol
from rasterio.merge import merge
from rasterio.warp import transform as warp_transform

from scripts.grid_utils import DATA_DIR, load_cenotes, cenote_key, save_features

OUTPUT = DATA_DIR / "canopy_features.json"
CANOPY_DIR = DATA_DIR / "canopy_meta"
TILES_INDEX = CANOPY_DIR / "tiles.geojson"
BBOX = [-90.5, 20.0, -87.4, 21.8]  # west, south, east, north
RADIUS_M = 100


def download_tile_index():
    """Download the tile index GeoJSON from AWS S3 via HTTPS."""
    CANOPY_DIR.mkdir(parents=True, exist_ok=True)
    if TILES_INDEX.exists():
        print("  Tile index already exists")
        return

    import urllib.request
    url = "https://dataforgood-fb-data.s3.amazonaws.com/forests/v1/alsgedi_global_v6_float/tiles.geojson"
    print(f"  Downloading tile index...")
    urllib.request.urlretrieve(url, TILES_INDEX)
    print(f"  Saved: {TILES_INDEX}")


def find_yucatan_tiles():
    """Find tile quadkeys that overlap with our bounding box."""
    with open(TILES_INDEX) as f:
        data = json.load(f)

    tiles = []
    for feature in data["features"]:
        geom = feature["geometry"]
        props = feature["properties"]

        # Get quadkey from properties
        quadkey = props.get("tile", props.get("quadkey", props.get("name", "")))

        # Check if tile bbox overlaps with our area
        if geom["type"] == "Polygon":
            coords = geom["coordinates"][0]
            lons = [c[0] for c in coords]
            lats = [c[1] for c in coords]
            tile_bbox = [min(lons), min(lats), max(lons), max(lats)]

            # Check overlap
            if (tile_bbox[0] <= BBOX[2] and tile_bbox[2] >= BBOX[0] and
                tile_bbox[1] <= BBOX[3] and tile_bbox[3] >= BBOX[1]):
                tiles.append(quadkey)

    return tiles


def download_canopy_tile(quadkey):
    """Download a single canopy height tile via HTTPS."""
    local_path = CANOPY_DIR / f"{quadkey}.tif"
    if local_path.exists():
        return local_path

    import urllib.request
    url = f"https://dataforgood-fb-data.s3.amazonaws.com/forests/v1/alsgedi_global_v6_float/chm/{quadkey}.tif"
    try:
        urllib.request.urlretrieve(url, local_path)
    except Exception as e:
        print(f"    Failed to download {quadkey}: {e}")
        return None

    return local_path if local_path.exists() else None


def extract_canopy_features(cenotes, canopy_tiles):
    """Extract canopy height stats within radius of each cenote."""
    results = {}

    for i, c in enumerate(cenotes):
        lat, lon = c["lat"], c["lon"]

        # Find which tile contains this point
        best_patch = None
        for tile_path in canopy_tiles:
            try:
                src = rasterio.open(tile_path)
            except Exception:
                continue

            # Transform point to tile CRS
            if str(src.crs) != "EPSG:4326":
                xs, ys = warp_transform("EPSG:4326", src.crs, [lon], [lat])
                px, py = xs[0], ys[0]
            else:
                px, py = lon, lat

            try:
                row, col = rowcol(src.transform, px, py)
            except Exception:
                continue

            if not (0 <= row < src.height and 0 <= col < src.width):
                continue

            # Read a window around the point
            res_m = abs(src.transform.a)
            if res_m < 0.01:  # Degrees — convert to approximate meters
                res_m = res_m * 111000

            buf_px = int(RADIUS_M / res_m) + 5
            r0 = max(0, row - buf_px)
            r1 = min(src.height, row + buf_px + 1)
            c0 = max(0, col - buf_px)
            c1 = min(src.width, col + buf_px + 1)

            window = rasterio.windows.Window(c0, r0, c1 - c0, r1 - r0)
            patch = src.read(1, window=window).astype(np.float64)

            lr = row - r0
            lc = col - c0

            # Distance mask
            ri = np.arange(patch.shape[0])
            ci = np.arange(patch.shape[1])
            cg, rg = np.meshgrid(ci, ri)
            dist = np.sqrt(((rg - lr) * res_m) ** 2 + ((cg - lc) * res_m) ** 2)
            mask = dist <= RADIUS_M

            # Valid pixels (positive height, not nodata)
            nodata = src.nodata or 0
            valid = mask & (patch > 0) & (patch < 200) & (patch != nodata)
            vals = patch[valid]

            if len(vals) == 0:
                continue

            all_in_circle = mask.sum()
            gap_pixels = mask & ((patch < 2) | (patch == nodata) | (patch <= 0))

            results[cenote_key(c)] = {
                "canopy_mean": round(float(np.mean(vals)), 1),
                "canopy_min": round(float(np.min(vals)), 1),
                "canopy_std": round(float(np.std(vals)), 2),
                "canopy_gap_fraction": round(float(gap_pixels.sum() / all_in_circle), 3),
            }
            break  # Found the tile, move to next cenote

        if (i + 1) % 200 == 0:
            print(f"  {i+1}/{len(cenotes)}")

    return results


def main():
    print("=== Canopy Height Analysis (Meta/WRI 1m) ===\n")

    print("Loading cenotes...")
    cenotes = load_cenotes()
    print(f"  {len(cenotes)} cenotes")

    print("\nDownloading tile index...")
    download_tile_index()

    print("\nFinding tiles covering study area...")
    quadkeys = find_yucatan_tiles()
    print(f"  {len(quadkeys)} tiles overlap with study area")

    if not quadkeys:
        print("ERROR: No tiles found for study area")
        return

    print(f"\nDownloading canopy height tiles...")
    tile_paths = []
    for qi, qk in enumerate(quadkeys):
        print(f"  [{qi+1}/{len(quadkeys)}] Downloading {qk}...")
        path = download_canopy_tile(qk)
        if path:
            tile_paths.append(path)

    print(f"  {len(tile_paths)} tiles downloaded")

    if not tile_paths:
        print("ERROR: No tiles downloaded")
        return

    # Quick stats on first tile
    with rasterio.open(tile_paths[0]) as src:
        print(f"  Tile CRS: {src.crs}, Resolution: {src.transform.a}")

    print("\nExtracting canopy features at cenote locations...")
    results = extract_canopy_features(cenotes, tile_paths)
    save_features(results, OUTPUT)

    if results:
        vals = list(results.values())
        means = [v["canopy_mean"] for v in vals]
        gaps = [v["canopy_gap_fraction"] for v in vals]
        print(f"\n── Summary ──")
        print(f"  Cenotes with data: {len(results)}/{len(cenotes)}")
        if means:
            print(f"  Canopy height: mean={np.mean(means):.1f}m, std={np.std(means):.1f}m")
        if gaps:
            print(f"  Gap fraction: mean={np.mean(gaps):.3f}, max={np.max(gaps):.3f}")


if __name__ == "__main__":
    main()
