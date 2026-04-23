#!/usr/bin/env python3
"""
Compute plan and profile curvature for each cenote using WhiteboxTools.

Uses 5x5 polynomial window (more robust on flat terrain than 3x3).
Falls back to 15m CEM for cenotes outside 5m coverage.
"""

import os
import shutil
import tempfile
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import rowcol

import whitebox

from scripts.grid_utils import (
    DATA_DIR, DEM_DIR_5M, CEM_15M,
    load_cenotes, cenote_key, build_5m_index, find_5m_tile,
    get_ds, save_features,
)

OUTPUT = DATA_DIR / "curvature_features.json"
RADIUS_M = 100  # extraction radius around each cenote

_tile_cache = {}


def bil_to_tif(bil_path, tif_path):
    """Convert BIL to GeoTIFF for WhiteboxTools."""
    with rasterio.open(bil_path) as src:
        profile = src.profile.copy()
        profile.update(driver="GTiff", compress="lzw")
        data = src.read(1)
        with rasterio.open(tif_path, "w", **profile) as dst:
            dst.write(data, 1)


def process_tile_curvature(tile_path, tmpdir, is_tif=False):
    """Run plan + profile curvature on a tile. Returns (plan_array, profile_array)."""
    if tile_path in _tile_cache:
        return _tile_cache[tile_path]

    tile_id = tile_path.stem
    if is_tif:
        tif = str(tile_path)
    else:
        tif = os.path.join(tmpdir, f"{tile_id}_dem.tif")
        bil_to_tif(tile_path, tif)

    plan_out = os.path.join(tmpdir, f"{tile_id}_plan.tif")
    prof_out = os.path.join(tmpdir, f"{tile_id}_prof.tif")

    wbt = whitebox.WhiteboxTools()
    wbt.verbose = False

    wbt.plan_curvature(tif, plan_out)
    wbt.profile_curvature(tif, prof_out)

    plan_curv = None
    prof_curv = None

    if os.path.exists(plan_out):
        with rasterio.open(plan_out) as src:
            plan_curv = src.read(1).astype(np.float64)
    if os.path.exists(prof_out):
        with rasterio.open(prof_out) as src:
            prof_curv = src.read(1).astype(np.float64)

    # Cleanup temp files
    for f in [plan_out, prof_out]:
        if os.path.exists(f):
            os.remove(f)
    if not is_tif:
        tif_p = os.path.join(tmpdir, f"{tile_id}_dem.tif")
        if os.path.exists(tif_p):
            os.remove(tif_p)

    _tile_cache[tile_path] = (plan_curv, prof_curv)
    return plan_curv, prof_curv


def extract_curvature_features(src, plan_curv, prof_curv, center_x, center_y, res_m):
    """Extract curvature stats within radius around a point."""
    row_c, col_c = rowcol(src.transform, center_x, center_y)
    if not (0 <= row_c < src.height and 0 <= col_c < src.width):
        return None

    buf_px = int(RADIUS_M / res_m) + 5
    r0 = max(0, row_c - buf_px)
    c0 = max(0, col_c - buf_px)
    r1 = min(src.height, row_c + buf_px + 1)
    c1 = min(src.width, col_c + buf_px + 1)

    lr = row_c - r0
    lc = col_c - c0

    ri = np.arange(r1 - r0)
    ci = np.arange(c1 - c0)
    cg, rg = np.meshgrid(ci, ri)
    dist = np.sqrt(((rg - lr) * res_m) ** 2 + ((cg - lc) * res_m) ** 2)
    mask = dist <= RADIUS_M

    features = {}

    if plan_curv is not None:
        pc = plan_curv[r0:r1, c0:c1]
        pc_vals = pc[mask]
        # Filter out nodata (very large values)
        pc_vals = pc_vals[np.abs(pc_vals) < 1e6]
        if len(pc_vals) > 0:
            features["plan_curv_mean"] = float(np.mean(pc_vals))
            features["plan_curv_min"] = float(np.min(pc_vals))

    if prof_curv is not None:
        prc = prof_curv[r0:r1, c0:c1]
        prc_vals = prc[mask]
        prc_vals = prc_vals[np.abs(prc_vals) < 1e6]
        if len(prc_vals) > 0:
            features["profile_curv_mean"] = float(np.mean(prc_vals))
            features["profile_curv_min"] = float(np.min(prc_vals))

    return features if features else None


def main():
    print("Building 5m tile index...")
    index_5m = build_5m_index()

    print("Loading cenotes...")
    cenotes = load_cenotes()
    print(f"  {len(cenotes)} cenotes")

    tmpdir = tempfile.mkdtemp(prefix="cenote_curv_")
    print(f"  Temp dir: {tmpdir}")

    # Group cenotes by tile
    tile_cenotes = {}
    cem_cenotes = []

    for c in cenotes:
        path_5m, ux, uy = find_5m_tile(c["lat"], c["lon"], index_5m)
        if path_5m:
            tile_cenotes.setdefault(path_5m, []).append((c, ux, uy))
        else:
            cem_cenotes.append((c, c["lon"], c["lat"]))

    print(f"  {sum(len(v) for v in tile_cenotes.values())} cenotes on 5m tiles ({len(tile_cenotes)} tiles)")
    print(f"  {len(cem_cenotes)} cenotes on 15m CEM")

    results = {}

    # Process 5m tiles
    for i, (tile_path, cenote_list) in enumerate(tile_cenotes.items()):
        print(f"  [{i+1}/{len(tile_cenotes)}] {tile_path.name} ({len(cenote_list)} cenotes)...")
        plan_curv, prof_curv = process_tile_curvature(tile_path, tmpdir)
        src = get_ds(tile_path)

        for c, cx, cy in cenote_list:
            feats = extract_curvature_features(src, plan_curv, prof_curv, cx, cy, 5.0)
            if feats:
                results[cenote_key(c)] = feats

    # 15m CEM fallback
    if cem_cenotes:
        print(f"  Processing 15m CEM for {len(cem_cenotes)} cenotes...")
        plan_curv, prof_curv = process_tile_curvature(CEM_15M, tmpdir, is_tif=True)
        cem_src = get_ds(CEM_15M)

        for c, cx, cy in cem_cenotes:
            feats = extract_curvature_features(cem_src, plan_curv, prof_curv, cx, cy, 15.0)
            if feats:
                results[cenote_key(c)] = feats

    shutil.rmtree(tmpdir, ignore_errors=True)
    save_features(results, OUTPUT)

    # Summary
    if results:
        vals = list(results.values())
        plan_means = [v["plan_curv_mean"] for v in vals if "plan_curv_mean" in v]
        if plan_means:
            print(f"\n── Summary ──")
            print(f"  Plan curvature mean: {np.mean(plan_means):.4f} (neg=concave)")
            print(f"  Plan curvature range: [{np.min(plan_means):.4f}, {np.max(plan_means):.4f}]")


if __name__ == "__main__":
    main()
