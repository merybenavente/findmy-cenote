#!/usr/bin/env python3
"""Generate colored NDVI overlay WebP images for the dashboard (dry + wet season)."""

import json
import numpy as np
import rasterio
from PIL import Image

DATA_DIR = "data"

SOURCES = [
    (f"{DATA_DIR}/ndvi_dry.tif", f"{DATA_DIR}/ndvi_dry_overlay.webp", "Dry season"),
    (f"{DATA_DIR}/ndvi_wet.tif", f"{DATA_DIR}/ndvi_wet_overlay.webp", "Wet season"),
]
OUT_BOUNDS = f"{DATA_DIR}/ndvi_overlay_bounds.json"

# NDVI colormap: brown (bare) -> green (dense vegetation)
STOPS = [
    (-0.1, (160, 140, 100)),
    (0.0,  (180, 160, 120)),
    (0.1,  (200, 180, 140)),
    (0.2,  (170, 190, 110)),
    (0.3,  (120, 170, 80)),
    (0.4,  (80, 155, 60)),
    (0.5,  (50, 140, 45)),
    (0.6,  (30, 120, 35)),
    (0.7,  (15, 100, 25)),
    (0.85, (10, 75, 18)),
]


def ndvi_to_rgb(ndvi):
    """Map NDVI array to RGB using color stops."""
    r = np.zeros_like(ndvi, dtype=np.uint8)
    g = np.zeros_like(ndvi, dtype=np.uint8)
    b = np.zeros_like(ndvi, dtype=np.uint8)

    for i in range(len(STOPS) - 1):
        v0, (r0, g0, b0) = STOPS[i]
        v1, (r1, g1, b1) = STOPS[i + 1]
        mask = (ndvi >= v0) & (ndvi < v1)
        if not mask.any():
            continue
        t = (ndvi[mask] - v0) / (v1 - v0)
        r[mask] = (r0 + t * (r1 - r0)).astype(np.uint8)
        g[mask] = (g0 + t * (g1 - g0)).astype(np.uint8)
        b[mask] = (b0 + t * (b1 - b0)).astype(np.uint8)

    # Below first stop
    lo_v, (lr, lg, lb) = STOPS[0]
    mask = ndvi < lo_v
    r[mask], g[mask], b[mask] = lr, lg, lb

    # Above last stop
    hi_v, (hr, hg, hb) = STOPS[-1]
    mask = ndvi >= hi_v
    r[mask], g[mask], b[mask] = hr, hg, hb

    return r, g, b


def process_raster(input_path, output_path, label):
    print(f"\nProcessing {label}: {input_path}")
    with rasterio.open(input_path) as src:
        # Downsample: every 4th pixel for reasonable file size
        step = 4
        out_h = src.height // step
        out_w = src.width // step
        data = src.read(1, out_shape=(out_h, out_w))
        bounds = src.bounds
        nodata = src.nodata
        crs = src.crs

    print(f"  Shape: {data.shape}, CRS: {crs}, bounds: {bounds}")

    # Convert bounds to lat/lon (EPSG:4326) if not already
    if crs and not crs.is_geographic:
        from rasterio.warp import transform_bounds
        west, south, east, north = transform_bounds(crs, "EPSG:4326",
            bounds.left, bounds.bottom, bounds.right, bounds.top)
        from rasterio.coords import BoundingBox
        bounds = BoundingBox(left=west, bottom=south, right=east, top=north)
        print(f"  Reprojected bounds (lat/lon): {bounds}")

    # Valid mask: exclude nodata, NaN, and extreme values
    valid = np.isfinite(data) & (data > -1) & (data < 2)
    if nodata is not None:
        valid &= (data != nodata)

    ndvi = np.clip(data, -0.1, 1.0)
    r, g, b = ndvi_to_rgb(ndvi)
    a = np.where(valid, 180, 0).astype(np.uint8)

    rgba = np.stack([r, g, b, a], axis=-1)
    img = Image.fromarray(rgba, "RGBA")
    img.save(output_path, "WEBP", quality=80)

    import os
    size_kb = os.path.getsize(output_path) / 1024
    print(f"  Saved {output_path}: {img.size[0]}x{img.size[1]} ({size_kb:.0f} KB)")

    return bounds


def main():
    saved_bounds = None
    for input_path, output_path, label in SOURCES:
        bounds = process_raster(input_path, output_path, label)
        if saved_bounds is None:
            saved_bounds = bounds

    # Save bounds (same for both since they come from same Sentinel-2 composite)
    bounds_dict = {
        "south": saved_bounds.bottom,
        "north": saved_bounds.top,
        "west": saved_bounds.left,
        "east": saved_bounds.right,
    }
    with open(OUT_BOUNDS, "w") as f:
        json.dump(bounds_dict, f)
    print(f"\nBounds: {bounds_dict}")


if __name__ == "__main__":
    main()
