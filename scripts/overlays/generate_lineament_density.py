#!/usr/bin/env python3
"""Generate a lineament density heatmap overlay for the dashboard."""

import json
import numpy as np
from PIL import Image

DATA_DIR = "data"
INPUT = f"{DATA_DIR}/lineaments_display.json"
OUT_IMG = f"{DATA_DIR}/lineament_density_overlay.webp"
OUT_BOUNDS = f"{DATA_DIR}/lineament_density_bounds.json"

# Grid resolution in degrees (~0.02 deg ≈ 2.2 km)
CELL_SIZE = 0.02

# Colormap: transparent -> yellow -> orange -> red (calibrated to actual density range)
STOPS = [
    (0,    (0, 0, 0, 0)),          # transparent
    (0.1,  (255, 255, 180, 60)),   # faint yellow
    (0.5,  (255, 230, 100, 120)),  # yellow
    (1.0,  (255, 180, 50, 160)),   # orange
    (1.5,  (240, 120, 30, 190)),   # red-orange
    (2.0,  (220, 60, 15, 210)),    # red
    (3.0,  (180, 20, 10, 230)),    # dark red
    (5.0,  (140, 10, 5, 250)),     # very dark red
]


def density_to_rgba(density):
    """Map density array to RGBA."""
    r = np.zeros_like(density, dtype=np.uint8)
    g = np.zeros_like(density, dtype=np.uint8)
    b = np.zeros_like(density, dtype=np.uint8)
    a = np.zeros_like(density, dtype=np.uint8)

    for i in range(len(STOPS) - 1):
        v0, (r0, g0, b0, a0) = STOPS[i]
        v1, (r1, g1, b1, a1) = STOPS[i + 1]
        mask = (density >= v0) & (density < v1)
        if not mask.any():
            continue
        t = (density[mask] - v0) / (v1 - v0)
        r[mask] = (r0 + t * (r1 - r0)).astype(np.uint8)
        g[mask] = (g0 + t * (g1 - g0)).astype(np.uint8)
        b[mask] = (b0 + t * (b1 - b0)).astype(np.uint8)
        a[mask] = (a0 + t * (a1 - a0)).astype(np.uint8)

    # Above last stop
    hi_v, (hr, hg, hb, ha) = STOPS[-1]
    mask = density >= hi_v
    r[mask], g[mask], b[mask], a[mask] = hr, hg, hb, ha

    return r, g, b, a


def main():
    print("Loading lineaments...")
    with open(INPUT) as f:
        lineaments = json.load(f)
    print(f"  {len(lineaments)} segments")

    # Compute midpoints
    lats = []
    lons = []
    for seg in lineaments:
        lats.append((seg["la1"] + seg["la2"]) / 2)
        lons.append((seg["lo1"] + seg["lo2"]) / 2)

    lats = np.array(lats)
    lons = np.array(lons)

    # Grid bounds (with small padding)
    lat_min = np.floor(lats.min() / CELL_SIZE) * CELL_SIZE - CELL_SIZE
    lat_max = np.ceil(lats.max() / CELL_SIZE) * CELL_SIZE + CELL_SIZE
    lon_min = np.floor(lons.min() / CELL_SIZE) * CELL_SIZE - CELL_SIZE
    lon_max = np.ceil(lons.max() / CELL_SIZE) * CELL_SIZE + CELL_SIZE

    n_rows = int((lat_max - lat_min) / CELL_SIZE)
    n_cols = int((lon_max - lon_min) / CELL_SIZE)
    print(f"  Grid: {n_rows} x {n_cols} cells ({CELL_SIZE} deg)")

    # Count midpoints per cell
    grid = np.zeros((n_rows, n_cols), dtype=np.float32)
    row_idx = ((lat_max - lats) / CELL_SIZE).astype(int)  # top-down
    col_idx = ((lons - lon_min) / CELL_SIZE).astype(int)

    # Clamp to valid range
    row_idx = np.clip(row_idx, 0, n_rows - 1)
    col_idx = np.clip(col_idx, 0, n_cols - 1)

    for ri, ci in zip(row_idx, col_idx):
        grid[ri, ci] += 1

    # Light Gaussian-like smoothing: average with neighbors for less blocky look
    from scipy.ndimage import uniform_filter
    grid_smooth = uniform_filter(grid, size=3)

    print(f"  Density range: [{grid_smooth.min():.1f}, {grid_smooth.max():.1f}]")
    print(f"  Non-zero cells: {(grid_smooth > 0).sum()} / {grid.size}")

    # Render to RGBA
    r, g, b, a = density_to_rgba(grid_smooth)
    rgba = np.stack([r, g, b, a], axis=-1)

    # Upscale for smoother appearance (4x)
    img = Image.fromarray(rgba, "RGBA")
    img = img.resize((n_cols * 4, n_rows * 4), Image.BILINEAR)
    img.save(OUT_IMG, "WEBP", quality=80)

    import os
    size_kb = os.path.getsize(OUT_IMG) / 1024
    print(f"\n  Saved {OUT_IMG}: {img.size[0]}x{img.size[1]} ({size_kb:.0f} KB)")

    # Save bounds (convert numpy types to float for JSON)
    bounds = {
        "south": float(lat_min),
        "north": float(lat_max),
        "west": float(lon_min),
        "east": float(lon_max),
    }
    with open(OUT_BOUNDS, "w") as f:
        json.dump(bounds, f)
    print(f"  Bounds: {bounds}")


if __name__ == "__main__":
    main()
