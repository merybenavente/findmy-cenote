#!/usr/bin/env python3
"""Generate a colored canopy height overlay WebP for the dashboard.

Reads Meta/WRI 1m canopy height tiles, merges them, downsamples to a
manageable resolution, and produces a color-mapped RGBA overlay.

Color scale: teal-based, matching the brand palette.
  0m (no canopy) → transparent
  1-5m (low)     → light mint
  5-15m (medium) → jade
  15-25m (tall)  → deep teal
  25m+ (very tall) → sun gold (anomalous)
"""

import json
import os
import numpy as np
import rasterio
from rasterio.merge import merge
from rasterio.warp import calculate_default_transform, reproject, Resampling
from rasterio.coords import BoundingBox
from PIL import Image
import tempfile

DATA_DIR = "data"
CANOPY_DIR = os.path.join(DATA_DIR, "canopy_meta")
OUTPUT = os.path.join(DATA_DIR, "canopy_overlay.webp")
OUT_BOUNDS = os.path.join(DATA_DIR, "canopy_overlay_bounds.json")

# Yucatan bounding box (lat/lon) — clip to area of interest
YUCATAN_BBOX = (-91.0, 19.5, -87.0, 21.7)

# Color stops: anomaly_m → (R, G, B)
# Positive = taller than neighbors, negative = shorter
STOPS = [
    (-4, (232, 106, 75)),    # coral — much shorter than neighbors
    (-2, (243, 236, 220)),   # stone
    (0,  (14, 111, 107)),    # teal — normal
    (2,  (31, 163, 142)),    # jade — somewhat taller
    (4,  (79, 209, 197)),    # turq — tall
    (6,  (244, 181, 68)),    # sun — anomalously tall
]


def height_to_rgba(data):
    """Map canopy height to RGBA."""
    h, w = data.shape
    r = np.zeros((h, w), dtype=np.uint8)
    g = np.zeros((h, w), dtype=np.uint8)
    b = np.zeros((h, w), dtype=np.uint8)
    a = np.zeros((h, w), dtype=np.uint8)

    # Only color pixels where there's actual canopy data nearby
    has_canopy = np.abs(data) > 0.5

    for i in range(len(STOPS) - 1):
        v0, (r0, g0, b0) = STOPS[i]
        v1, (r1, g1, b1) = STOPS[i + 1]
        mask = has_canopy & (data >= v0) & (data < v1)
        if not mask.any():
            continue
        t = (data[mask] - v0) / (v1 - v0)
        r[mask] = (r0 + t * (r1 - r0)).astype(np.uint8)
        g[mask] = (g0 + t * (g1 - g0)).astype(np.uint8)
        b[mask] = (b0 + t * (b1 - b0)).astype(np.uint8)

    # Above last stop
    hi_v, (hr, hg, hb) = STOPS[-1]
    mask = has_canopy & (data >= hi_v)
    r[mask], g[mask], b[mask] = hr, hg, hb

    # Below first stop but > 0
    lo_v, (lr, lg, lb) = STOPS[0]
    mask = has_canopy & (data < lo_v)
    r[mask], g[mask], b[mask] = lr, lg, lb

    # Alpha: 0 for no canopy, 180 for canopy
    a[has_canopy] = 180

    return r, g, b, a


def main():
    tiles = sorted([
        os.path.join(CANOPY_DIR, f)
        for f in os.listdir(CANOPY_DIR)
        if f.endswith('.tif')
    ])
    print(f"Found {len(tiles)} canopy tiles")

    if not tiles:
        print("No tiles found!")
        return

    # Open all tiles
    datasets = [rasterio.open(t) for t in tiles]

    # Merge tiles
    print("Merging tiles...")
    merged, merged_transform = merge(datasets, method='max')
    merged_data = merged[0]  # single band
    src_crs = datasets[0].crs
    src_h, src_w = merged_data.shape
    print(f"  Merged shape: {src_w}x{src_h}, CRS: {src_crs}")

    # Calculate bounds in EPSG:4326
    from rasterio.warp import transform_bounds
    src_bounds = rasterio.transform.array_bounds(src_h, src_w, merged_transform)
    west, south, east, north = transform_bounds(
        src_crs, "EPSG:4326",
        src_bounds[0], src_bounds[1], src_bounds[2], src_bounds[3]
    )

    # Clip to Yucatan
    west = max(west, YUCATAN_BBOX[0])
    south = max(south, YUCATAN_BBOX[1])
    east = min(east, YUCATAN_BBOX[2])
    north = min(north, YUCATAN_BBOX[3])
    print(f"  Output bounds: {south:.2f}N to {north:.2f}N, {west:.2f}E to {east:.2f}E")

    # Target resolution: ~100m per pixel for dashboard overlay
    res_deg = 0.001  # ~111m
    out_w = int((east - west) / res_deg)
    out_h = int((north - south) / res_deg)
    print(f"  Output size: {out_w}x{out_h}")

    dst_transform = rasterio.transform.from_bounds(west, south, east, north, out_w, out_h)
    dst_data = np.zeros((out_h, out_w), dtype=np.float32)

    print("Reprojecting...")
    reproject(
        source=merged_data,
        destination=dst_data,
        src_transform=merged_transform,
        src_crs=src_crs,
        dst_transform=dst_transform,
        dst_crs="EPSG:4326",
        resampling=Resampling.average,
    )

    for ds in datasets:
        ds.close()

    print(f"  Canopy range: {dst_data[dst_data > 0].min():.1f} - {dst_data[dst_data > 0].max():.1f}m")

    # Compute local anomaly: how much taller than the 25-pixel neighborhood
    from scipy.ndimage import uniform_filter
    local_mean = uniform_filter(dst_data.astype(np.float64), size=25)
    anomaly = dst_data - local_mean
    print(f"  Anomaly range: {anomaly.min():.1f} to {anomaly.max():.1f}m")

    # Generate colored overlay from anomaly
    r, g, b, a = height_to_rgba(anomaly)
    rgba = np.stack([r, g, b, a], axis=-1)
    img = Image.fromarray(rgba, "RGBA")
    img.save(OUTPUT, "WEBP", quality=80)

    size_kb = os.path.getsize(OUTPUT) / 1024
    print(f"  Saved {OUTPUT}: {img.size[0]}x{img.size[1]} ({size_kb:.0f} KB)")

    # Save bounds
    bounds_dict = {"south": south, "north": north, "west": west, "east": east}
    with open(OUT_BOUNDS, "w") as f:
        json.dump(bounds_dict, f)
    print(f"  Bounds: {bounds_dict}")


if __name__ == "__main__":
    main()
