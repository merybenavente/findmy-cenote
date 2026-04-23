#!/usr/bin/env python3
"""Generate a colored DEM overlay PNG for the Leaflet dashboard."""
import json
import numpy as np
import rasterio
from PIL import Image

DEM = "data/inegi_dem/v4/conjunto_de_datos/31_Yucatán_r15m_v4.tif"
OUT_PNG = "data/dem_overlay.png"
OUT_BOUNDS = "data/dem_overlay_bounds.json"

# Terrain colormap: elevation (m) -> RGBA
# Dark blue-green (low) -> green -> yellow -> orange -> red-brown (high)
STOPS = [
    (0,   (20, 40, 80)),
    (5,   (30, 80, 100)),
    (10,  (40, 120, 80)),
    (15,  (80, 150, 60)),
    (20,  (120, 170, 50)),
    (30,  (180, 180, 40)),
    (50,  (200, 140, 40)),
    (80,  (180, 100, 40)),
    (120, (140, 60, 40)),
    (200, (100, 40, 30)),
]


def elev_to_rgb(elev):
    """Map elevation array to RGB using color stops."""
    r = np.zeros_like(elev, dtype=np.uint8)
    g = np.zeros_like(elev, dtype=np.uint8)
    b = np.zeros_like(elev, dtype=np.uint8)

    for i in range(len(STOPS) - 1):
        e0, (r0, g0, b0) = STOPS[i]
        e1, (r1, g1, b1) = STOPS[i + 1]
        mask = (elev >= e0) & (elev < e1)
        if not mask.any():
            continue
        t = (elev[mask] - e0) / (e1 - e0)
        r[mask] = (r0 + t * (r1 - r0)).astype(np.uint8)
        g[mask] = (g0 + t * (g1 - g0)).astype(np.uint8)
        b[mask] = (b0 + t * (b1 - b0)).astype(np.uint8)

    # Above last stop
    last_e, (lr, lg, lb) = STOPS[-1]
    mask = elev >= last_e
    r[mask], g[mask], b[mask] = lr, lg, lb

    return r, g, b


def main():
    print("Reading DEM...")
    with rasterio.open(DEM) as src:
        # Downsample for reasonable file size: every 4th pixel -> ~60m effective
        step = 4
        data = src.read(1, out_shape=(src.height // step, src.width // step))
        bounds = src.bounds
        nodata = src.nodata

    print(f"  Shape: {data.shape}, bounds: {bounds}")

    # Create RGBA image
    valid = (data > -999) & (data < 9999)
    elev = np.clip(data, 0, 250)

    r, g, b = elev_to_rgb(elev)
    a = np.where(valid, 180, 0).astype(np.uint8)  # semi-transparent

    # Stack to RGBA
    rgba = np.stack([r, g, b, a], axis=-1)

    # Save PNG
    img = Image.fromarray(rgba, 'RGBA')
    img.save(OUT_PNG, optimize=True)
    print(f"  Saved {OUT_PNG}: {img.size[0]}x{img.size[1]}")

    # Save bounds
    bounds_dict = {
        "south": bounds.bottom,
        "north": bounds.top,
        "west": bounds.left,
        "east": bounds.right,
    }
    with open(OUT_BOUNDS, "w") as f:
        json.dump(bounds_dict, f)
    print(f"  Bounds: {bounds_dict}")

    import os
    print(f"  PNG size: {os.path.getsize(OUT_PNG) // 1024}KB")


if __name__ == "__main__":
    main()
