#!/usr/bin/env python3
"""
Compute hydrology features for each cenote using WhiteboxTools.

For each 5m DEM tile:
  - depth_in_sink: depression depth (filled DEM - raw DEM)
  - breach_depressions + d_inf_flow_accumulation: flow convergence

Per cenote: sink depth stats, whether it's in a depression, flow accumulation.
Falls back to 15m CEM for cenotes outside 5m coverage.
"""

import json
import os
import shutil
import tempfile
from pathlib import Path

import numpy as np
import rasterio
import whitebox
from rasterio.warp import transform as warp_transform

from scripts.grid_utils import (
    DATA_DIR, DEM_DIR_5M, CEM_15M,
    load_cenotes, cenote_key, build_5m_index, find_5m_tile,
    get_ds, save_features,
)

OUTPUT = DATA_DIR / "hydrology_features.json"
RADII = [100, 250]

# Cache for processed tiles: {tile_path: (sink_depth_array, flow_accum_array, src_profile)}
_tile_cache = {}


def bil_to_tif(bil_path, tif_path):
    """Convert BIL to GeoTIFF for WhiteboxTools."""
    with rasterio.open(bil_path) as src:
        profile = src.profile.copy()
        profile.update(driver="GTiff", compress="lzw")
        data = src.read(1)
        with rasterio.open(tif_path, "w", **profile) as dst:
            dst.write(data, 1)
    return data


def process_tile(tile_path, tmpdir):
    """Run WhiteboxTools hydrology on a single tile. Returns (sink_depth, flow_accum) arrays."""
    if tile_path in _tile_cache:
        return _tile_cache[tile_path]

    tile_id = tile_path.stem
    tif = os.path.join(tmpdir, f"{tile_id}_dem.tif")
    sink_out = os.path.join(tmpdir, f"{tile_id}_sink.tif")
    breached_out = os.path.join(tmpdir, f"{tile_id}_breached.tif")
    flow_out = os.path.join(tmpdir, f"{tile_id}_flow.tif")

    # Convert BIL → GeoTIFF
    bil_to_tif(tile_path, tif)

    wbt = whitebox.WhiteboxTools()
    wbt.verbose = False

    # Sink depth: filled DEM minus raw DEM
    wbt.depth_in_sink(tif, sink_out, zero_background=True)

    # Flow accumulation: breach depressions first, then D-infinity
    wbt.breach_depressions_least_cost(
        tif, breached_out, dist=50, max_cost=None, flat_increment=0.001
    )
    wbt.d_inf_flow_accumulation(
        breached_out, flow_out, out_type="Specific Contributing Area"
    )

    sink_depth = None
    flow_accum = None

    if os.path.exists(sink_out):
        with rasterio.open(sink_out) as src:
            sink_depth = src.read(1).astype(np.float64)

    if os.path.exists(flow_out):
        with rasterio.open(flow_out) as src:
            flow_accum = src.read(1).astype(np.float64)
            # Replace nodata sentinels
            flow_accum[flow_accum < -1e30] = 0

    # Clean up temp files for this tile
    for f in [tif, sink_out, breached_out, flow_out]:
        if os.path.exists(f):
            os.remove(f)

    _tile_cache[tile_path] = (sink_depth, flow_accum)
    return sink_depth, flow_accum


def process_tile_15m(tmpdir):
    """Run hydrology on the 15m CEM. Returns (sink_depth, flow_accum)."""
    cache_key = CEM_15M
    if cache_key in _tile_cache:
        return _tile_cache[cache_key]

    tif = str(CEM_15M)
    sink_out = os.path.join(tmpdir, "cem_sink.tif")
    breached_out = os.path.join(tmpdir, "cem_breached.tif")
    flow_out = os.path.join(tmpdir, "cem_flow.tif")

    wbt = whitebox.WhiteboxTools()
    wbt.verbose = False

    print("  Processing 15m CEM (this may take a while)...")
    wbt.depth_in_sink(tif, sink_out, zero_background=True)
    wbt.breach_depressions_least_cost(
        tif, breached_out, dist=50, max_cost=None, flat_increment=0.001
    )
    wbt.d_inf_flow_accumulation(
        breached_out, flow_out, out_type="Specific Contributing Area"
    )

    sink_depth = None
    flow_accum = None

    if os.path.exists(sink_out):
        with rasterio.open(sink_out) as src:
            sink_depth = src.read(1).astype(np.float64)

    if os.path.exists(flow_out):
        with rasterio.open(flow_out) as src:
            flow_accum = src.read(1).astype(np.float64)
            flow_accum[flow_accum < -1e30] = 0

    for f in [sink_out, breached_out, flow_out]:
        if os.path.exists(f):
            os.remove(f)

    _tile_cache[cache_key] = (sink_depth, flow_accum)
    return sink_depth, flow_accum


def extract_hydro_features(src, sink_depth, flow_accum, center_x, center_y, res_m):
    """Extract hydrology features at a point from pre-computed rasters."""
    from rasterio.transform import rowcol

    row_c, col_c = rowcol(src.transform, center_x, center_y)
    if not (0 <= row_c < src.height and 0 <= col_c < src.width):
        return None

    features = {}

    for radius in RADII:
        buf_px = int(radius / res_m) + 5
        r0 = max(0, row_c - buf_px)
        c0 = max(0, col_c - buf_px)
        r1 = min(src.height, row_c + buf_px + 1)
        c1 = min(src.width, col_c + buf_px + 1)

        lr = row_c - r0
        lc = col_c - c0

        # Distance grid
        ri = np.arange(r1 - r0)
        ci = np.arange(c1 - c0)
        cg, rg = np.meshgrid(ci, ri)
        dist = np.sqrt(((rg - lr) * res_m) ** 2 + ((cg - lc) * res_m) ** 2)
        mask = dist <= radius

        if sink_depth is not None:
            sd = sink_depth[r0:r1, c0:c1]
            sd_masked = sd[mask]
            sd_valid = sd_masked[sd_masked >= 0]

            if radius == 100:
                features["sink_depth_max_100m"] = float(np.max(sd_valid)) if len(sd_valid) > 0 else 0.0
                # Is the cenote itself in a depression?
                features["in_depression"] = bool(sd[lr, lc] > 0.1)
                # Area of the depression at center (connected component)
                if sd[lr, lc] > 0.1:
                    from scipy.ndimage import label
                    labeled, _ = label(sd > 0.1)
                    center_label = labeled[lr, lc]
                    if center_label > 0:
                        features["depression_area_m2"] = float(
                            np.sum(labeled == center_label) * res_m * res_m
                        )
                    else:
                        features["depression_area_m2"] = 0.0
                else:
                    features["depression_area_m2"] = 0.0

            if radius == 250:
                features["sink_depth_mean_250m"] = float(np.mean(sd_valid)) if len(sd_valid) > 0 else 0.0

        if flow_accum is not None:
            fa = flow_accum[r0:r1, c0:c1]
            fa_masked = fa[mask]
            fa_valid = fa_masked[fa_masked >= 0]

            if radius == 250:
                features["flow_accum_max_250m"] = float(np.max(fa_valid)) if len(fa_valid) > 0 else 0.0

            if radius == 100:
                features["flow_accum_at_point"] = float(fa[lr, lc]) if fa[lr, lc] >= 0 else 0.0

    return features


def main():
    print("Building 5m tile index...")
    index_5m = build_5m_index()

    print("Loading cenotes...")
    cenotes = load_cenotes()
    print(f"  {len(cenotes)} cenotes")

    tmpdir = tempfile.mkdtemp(prefix="cenote_hydro_")
    print(f"  Temp dir: {tmpdir}")

    # Group cenotes by which tile they fall in
    tile_cenotes = {}  # {tile_path: [(cenote, x, y)]}
    cem_cenotes = []   # [(cenote, lon, lat)]

    for c in cenotes:
        path_5m, ux, uy = find_5m_tile(c["lat"], c["lon"], index_5m)
        if path_5m:
            tile_cenotes.setdefault(path_5m, []).append((c, ux, uy))
        else:
            cem_cenotes.append((c, c["lon"], c["lat"]))

    print(f"  {sum(len(v) for v in tile_cenotes.values())} cenotes on 5m tiles ({len(tile_cenotes)} tiles)")
    print(f"  {len(cem_cenotes)} cenotes on 15m CEM fallback")

    results = {}

    # Process 5m tiles
    for i, (tile_path, cenote_list) in enumerate(tile_cenotes.items()):
        print(f"  [{i+1}/{len(tile_cenotes)}] {tile_path.name} ({len(cenote_list)} cenotes)...")
        sink_depth, flow_accum = process_tile(tile_path, tmpdir)
        src = get_ds(tile_path)

        for c, cx, cy in cenote_list:
            # Get pixel coords in tile's CRS
            feats = extract_hydro_features(src, sink_depth, flow_accum, cx, cy, 5.0)
            if feats:
                results[cenote_key(c)] = feats

    # Process 15m CEM fallback
    if cem_cenotes:
        print(f"  Processing 15m CEM for {len(cem_cenotes)} cenotes...")
        sink_depth, flow_accum = process_tile_15m(tmpdir)
        cem_src = get_ds(CEM_15M)

        for c, cx, cy in cem_cenotes:
            feats = extract_hydro_features(cem_src, sink_depth, flow_accum, cx, cy, 15.0)
            if feats:
                results[cenote_key(c)] = feats

    # Cleanup
    shutil.rmtree(tmpdir, ignore_errors=True)

    save_features(results, OUTPUT)

    # Summary stats
    if results:
        vals = list(results.values())
        sd_vals = [v["sink_depth_max_100m"] for v in vals if "sink_depth_max_100m" in v]
        in_dep = sum(1 for v in vals if v.get("in_depression"))
        print(f"\n── Summary ──")
        print(f"  Cenotes in a depression: {in_dep}/{len(vals)} ({100*in_dep/len(vals):.0f}%)")
        if sd_vals:
            print(f"  Sink depth max @100m: mean={np.mean(sd_vals):.2f}m, max={np.max(sd_vals):.2f}m")


if __name__ == "__main__":
    main()
