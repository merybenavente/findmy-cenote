#!/usr/bin/env python3
"""
Extract geological lineaments from DEM using multi-azimuth hillshade + edge/line detection.

Algorithm:
1. For each 5m DEM tile: apply vertical exaggeration, generate hillshades at 8 azimuths
2. Canny edge detection on each hillshade
3. Probabilistic Hough transform to extract line segments
4. Cluster and merge nearby parallel segments
5. Compute per-cenote features: distance to nearest lineament, count, dominant direction

Output: data/lineament_features.json (per-cenote) + data/lineaments.json (all lineament geometries)
"""

import json
import math
import os
import tempfile
import shutil
from pathlib import Path
from collections import defaultdict

import numpy as np
import rasterio
from rasterio.transform import rowcol, xy
from rasterio.warp import transform as warp_transform
from skimage.feature import canny
from skimage.transform import probabilistic_hough_line

from scripts.grid_utils import (
    DATA_DIR, DEM_DIR_5M, CEM_15M,
    load_cenotes, cenote_key, build_5m_index, find_5m_tile,
    get_ds, save_features,
)

OUTPUT_FEATURES = DATA_DIR / "lineament_features.json"
OUTPUT_LINEAMENTS = DATA_DIR / "lineaments.json"

# Hillshade azimuths (4 directions, sufficient for lineament detection)
AZIMUTHS = [0, 45, 90, 135]
SUN_ALTITUDE = 15  # Low sun angle to emphasize subtle features
VERT_EXAG = 10     # Vertical exaggeration factor

# Hough parameters (higher threshold = fewer, more confident lines)
HOUGH_THRESHOLD = 15
HOUGH_LINE_LENGTH = 30   # pixels (= 150m at 5m resolution)
HOUGH_LINE_GAP = 3       # pixels

# Canny parameters
CANNY_SIGMA = 2.0

# Feature extraction radii
LINEAMENT_NEAR_DIST_M = 50   # "on lineament" threshold
LINEAMENT_COUNT_RADIUS_M = 500


def hillshade(dem, azimuth_deg, altitude_deg, res_m):
    """Compute hillshade from DEM array."""
    az = math.radians(360 - azimuth_deg + 90)  # Convert to math convention
    alt = math.radians(altitude_deg)

    gy, gx = np.gradient(dem * VERT_EXAG, res_m)
    slope = np.arctan(np.sqrt(gx**2 + gy**2))
    aspect = np.arctan2(-gx, gy)

    shade = (
        np.sin(alt) * np.cos(slope)
        + np.cos(alt) * np.sin(slope) * np.cos(az - aspect)
    )
    return np.clip(shade, 0, 1)


def extract_lines_from_tile(dem_data, res_m):
    """Extract line segments from a DEM tile using multi-azimuth hillshade + Hough."""
    all_lines = []

    for az in AZIMUTHS:
        hs = hillshade(dem_data, az, SUN_ALTITUDE, res_m)
        # Normalize to 0-1
        hs_norm = (hs - hs.min()) / (hs.max() - hs.min() + 1e-10)

        edges = canny(hs_norm, sigma=CANNY_SIGMA)

        lines = probabilistic_hough_line(
            edges,
            threshold=HOUGH_THRESHOLD,
            line_length=HOUGH_LINE_LENGTH,
            line_gap=HOUGH_LINE_GAP,
        )
        all_lines.extend(lines)

    return all_lines


def line_orientation(p0, p1):
    """Orientation in degrees [0, 180) of a line segment."""
    dx = p1[0] - p0[0]
    dy = p1[1] - p0[1]
    angle = math.degrees(math.atan2(dy, dx)) % 180
    return angle


def line_length_m(p0, p1, res_m):
    """Length of a line segment in meters."""
    dx = (p1[0] - p0[0]) * res_m
    dy = (p1[1] - p0[1]) * res_m
    return math.sqrt(dx**2 + dy**2)


def cluster_lines(lines, res_m, angle_tol=15, dist_tol_px=5):
    """
    Simple clustering: merge nearby parallel line segments.
    Returns list of representative lines (midpoint + orientation + length).
    """
    if not lines:
        return []

    # Convert to (midpoint_col, midpoint_row, orientation, length_m)
    segments = []
    for (c0, r0), (c1, r1) in lines:
        mc = (c0 + c1) / 2
        mr = (r0 + r1) / 2
        ori = line_orientation((c0, r0), (c1, r1))
        length = line_length_m((c0, r0), (c1, r1), res_m)
        segments.append((mc, mr, ori, length, (c0, r0), (c1, r1)))

    # Sort by orientation for efficient clustering
    segments.sort(key=lambda s: s[2])

    clustered = []
    used = set()

    for i, s in enumerate(segments):
        if i in used:
            continue
        cluster = [s]
        used.add(i)

        for j in range(i + 1, len(segments)):
            if j in used:
                continue
            sj = segments[j]

            # Orientation difference (handle wrap at 180)
            ori_diff = abs(s[2] - sj[2])
            if ori_diff > 90:
                ori_diff = 180 - ori_diff
            if ori_diff > angle_tol:
                break  # sorted by orientation, so no more matches

            # Spatial distance
            dist = math.sqrt((s[0] - sj[0])**2 + (s[1] - sj[1])**2)
            if dist <= dist_tol_px:
                cluster.append(sj)
                used.add(j)

        # Take the longest segment as representative
        rep = max(cluster, key=lambda c: c[3])
        clustered.append(rep)

    return clustered


def pixel_to_latlon(src, row, col):
    """Convert pixel coordinates to lat/lon."""
    x, y = xy(src.transform, row, col)
    if src.crs.to_epsg() != 4326:
        lons, lats = warp_transform(src.crs, "EPSG:4326", [x], [y])
        return lats[0], lons[0]
    return y, x


def haversine_m(lat1, lon1, lat2, lon2):
    """Distance in meters between two lat/lon points."""
    R = 6371000
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def point_to_segment_dist_m(plat, plon, lat1, lon1, lat2, lon2):
    """Approximate distance from point to line segment in meters."""
    # Project onto segment using flat-earth approximation (fine at this scale)
    cos_lat = math.cos(math.radians(plat))
    px = (plon - lon1) * cos_lat
    py = plat - lat1
    sx = (lon2 - lon1) * cos_lat
    sy = lat2 - lat1

    seg_len_sq = sx**2 + sy**2
    if seg_len_sq < 1e-12:
        return haversine_m(plat, plon, lat1, lon1)

    t = max(0, min(1, (px * sx + py * sy) / seg_len_sq))
    closest_lon = lon1 + t * (lon2 - lon1)
    closest_lat = lat1 + t * (lat2 - lat1)
    return haversine_m(plat, plon, closest_lat, closest_lon)


def main():
    print("Building 5m tile index...")
    index_5m = build_5m_index()

    print("Loading cenotes...")
    cenotes = load_cenotes()
    print(f"  {len(cenotes)} cenotes")

    # Process tiles and collect lineaments in geographic coordinates
    all_lineaments = []  # [{lat1, lon1, lat2, lon2, orientation, length_m, tile}]

    tiles = sorted(DEM_DIR_5M.glob("*.bil"))
    print(f"\nExtracting lineaments from {len(tiles)} tiles...")

    for i, bil in enumerate(tiles):
        try:
            src = get_ds(bil)
        except Exception:
            continue

        data = src.read(1).astype(np.float64)
        nodata = src.nodata
        if nodata is not None:
            data[data == nodata] = np.nan

        # Skip tiles that are mostly nodata
        valid_frac = np.sum(~np.isnan(data)) / data.size
        if valid_frac < 0.3:
            continue

        # Fill NaN with local mean for edge detection
        from scipy.ndimage import uniform_filter
        data_filled = data.copy()
        nan_mask = np.isnan(data_filled)
        data_filled[nan_mask] = 0
        data_filled = uniform_filter(data_filled, size=5)
        data_filled[~nan_mask] = data[~nan_mask]

        lines = extract_lines_from_tile(data_filled, 5.0)

        # Convert raw lines directly (skip slow clustering)
        for (c0, r0), (c1, r1) in lines:
            ori = line_orientation((c0, r0), (c1, r1))
            length = line_length_m((c0, r0), (c1, r1), 5.0)
            mc, mr = (c0 + c1) / 2, (r0 + r1) / 2
            lat1, lon1 = pixel_to_latlon(src, int(r0), int(c0))
            lat2, lon2 = pixel_to_latlon(src, int(r1), int(c1))
            all_lineaments.append({
                "la1": round(lat1, 6),
                "lo1": round(lon1, 6),
                "la2": round(lat2, 6),
                "lo2": round(lon2, 6),
                "ori": round(ori, 1),
                "len": round(length, 1),
                "tile": bil.stem,
            })

        if (i + 1) % 10 == 0 or i == len(tiles) - 1:
            print(f"  [{i+1}/{len(tiles)}] {len(all_lineaments)} lineaments so far")

    print(f"\nTotal lineaments: {len(all_lineaments)}")

    # Save lineament geometries
    with open(OUTPUT_LINEAMENTS, "w") as f:
        json.dump(all_lineaments, f, separators=(",", ":"))
    print(f"Saved lineaments → {OUTPUT_LINEAMENTS}")

    # Build spatial grid index for fast lineament lookup
    # Grid cells of ~0.01 degrees (~1.1 km) — only check nearby cells
    print("\nBuilding spatial index for lineaments...")
    GRID_SIZE = 0.01  # degrees
    grid = defaultdict(list)
    for lin in all_lineaments:
        # Index by midpoint cell
        mid_lat = (lin["la1"] + lin["la2"]) / 2
        mid_lon = (lin["lo1"] + lin["lo2"]) / 2
        cell = (int(mid_lat / GRID_SIZE), int(mid_lon / GRID_SIZE))
        grid[cell].append(lin)
    print(f"  {len(grid)} grid cells")

    # Search radius in grid cells (500m ~ 0.005 deg, so check ±1 cell is enough)
    SEARCH_CELLS = 1

    # Compute per-cenote features using spatial index
    print("\nComputing per-cenote lineament features...")
    results = {}

    for ci, c in enumerate(cenotes):
        clat, clon = c["lat"], c["lon"]
        cell_r = int(clat / GRID_SIZE)
        cell_c = int(clon / GRID_SIZE)

        min_dist = float("inf")
        count_500m = 0
        nearby_orientations = []

        # Only check lineaments in nearby grid cells
        for dr in range(-SEARCH_CELLS, SEARCH_CELLS + 1):
            for dc in range(-SEARCH_CELLS, SEARCH_CELLS + 1):
                for lin in grid.get((cell_r + dr, cell_c + dc), []):
                    dist = point_to_segment_dist_m(
                        clat, clon, lin["la1"], lin["lo1"], lin["la2"], lin["lo2"]
                    )
                    if dist < min_dist:
                        min_dist = dist
                    if dist <= LINEAMENT_COUNT_RADIUS_M:
                        count_500m += 1
                        nearby_orientations.append(lin["ori"])

        # Dominant orientation of nearby lineaments
        dominant_az = None
        if nearby_orientations:
            angles_rad = [math.radians(2 * a) for a in nearby_orientations]
            mean_sin = np.mean([math.sin(a) for a in angles_rad])
            mean_cos = np.mean([math.cos(a) for a in angles_rad])
            dominant_az = round(math.degrees(math.atan2(mean_sin, mean_cos)) / 2 % 180, 1)

        results[cenote_key(c)] = {
            "lineament_dist_min": round(min_dist, 1) if min_dist < float("inf") else None,
            "lineament_count_500m": count_500m,
            "lineament_dominant_az": dominant_az,
            "on_lineament": min_dist <= LINEAMENT_NEAR_DIST_M if min_dist < float("inf") else False,
        }

        if (ci + 1) % 200 == 0:
            print(f"  {ci+1}/{len(cenotes)}")

    save_features(results, OUTPUT_FEATURES)

    # Summary
    if results:
        vals = list(results.values())
        dists = [v["lineament_dist_min"] for v in vals if v["lineament_dist_min"] is not None]
        on_lin = sum(1 for v in vals if v["on_lineament"])
        counts = [v["lineament_count_500m"] for v in vals]
        print(f"\n── Summary ──")
        print(f"  Cenotes on a lineament (<{LINEAMENT_NEAR_DIST_M}m): {on_lin}/{len(vals)}")
        if dists:
            print(f"  Distance to nearest lineament: mean={np.mean(dists):.0f}m, median={np.median(dists):.0f}m")
        print(f"  Lineaments within 500m: mean={np.mean(counts):.1f}, max={max(counts)}")


if __name__ == "__main__":
    main()
