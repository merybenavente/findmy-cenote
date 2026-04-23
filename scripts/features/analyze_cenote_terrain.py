#!/usr/bin/env python3
"""
Analyze terrain characteristics around each cenote using 5m and 15m DEMs.
For each cenote: extract elevation window, compute depression depth, slope, roughness.
"""
import csv
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import rowcol
from rasterio.warp import transform as warp_transform

ROOT = Path(__file__).parent.parent
DEM_DIR_5M = ROOT / "data" / "inegi_5m" / "extracted" / "conjunto_de_datos"
CENOTE_CSV = ROOT / "data" / "cenotes_arcgis.csv"
OUTPUT_CSV = ROOT / "data" / "cenote_terrain_analysis.csv"
OUTPUT_MD = ROOT / "data" / "cenote_terrain_analysis.md"

RADII = [50, 100, 250, 500]

# Pre-open 15m CEM file (geographic CRS — lat/lon directly usable)
CEM_15M = ROOT / "data" / "inegi_dem" / "v4" / "conjunto_de_datos" / "31_Yucatán_r15m_v4.tif"

# Cache open datasets
_ds_cache = {}


def get_ds(path):
    if path not in _ds_cache:
        _ds_cache[path] = rasterio.open(path)
    return _ds_cache[path]


def build_5m_index():
    """Build spatial index of 5m BIL tiles."""
    index = {}
    for bil in sorted(DEM_DIR_5M.glob("*.bil")):
        try:
            with rasterio.open(bil) as src:
                index[bil] = (src.bounds, src.crs)
        except:
            pass
    return index


def find_5m_tile(lat, lon, index_5m):
    """Find a 5m tile containing the point."""
    for path, (bounds, crs) in index_5m.items():
        xs, ys = warp_transform("EPSG:4326", crs, [lon], [lat])
        x, y = xs[0], ys[0]
        if bounds.left <= x <= bounds.right and bounds.bottom <= y <= bounds.top:
            return path, x, y
    return None, None, None


def analyze_point(src, center_x, center_y, res_m):
    """Analyze terrain around a point. center_x/y must be in the dataset's CRS."""
    row_c, col_c = rowcol(src.transform, center_x, center_y)
    if not (0 <= row_c < src.height and 0 <= col_c < src.width):
        return None

    # Window: 600m radius in pixels
    buf_px = int(600 / res_m) + 5
    r0 = max(0, row_c - buf_px)
    c0 = max(0, col_c - buf_px)
    r1 = min(src.height, row_c + buf_px + 1)
    c1 = min(src.width, col_c + buf_px + 1)

    window = rasterio.windows.Window(c0, r0, c1 - c0, r1 - r0)
    data = src.read(1, window=window).astype(np.float64)

    lr = row_c - r0
    lc = col_c - c0

    valid = data > -999
    if not valid[lr, lc]:
        return None

    center_elev = data[lr, lc]
    results = {"center_elev_m": float(center_elev)}

    # Distance grid
    ri = np.arange(data.shape[0])
    ci = np.arange(data.shape[1])
    cg, rg = np.meshgrid(ci, ri)
    dist = np.sqrt(((rg - lr) * res_m) ** 2 + ((cg - lc) * res_m) ** 2)

    for radius in RADII:
        ring_inner = max(0, radius - 50)
        ring_mask = (dist >= ring_inner) & (dist <= radius) & valid
        circle_mask = (dist <= radius) & valid
        if circle_mask.sum() == 0:
            continue

        cd = data[circle_mask]
        rd = data[ring_mask] if ring_mask.sum() > 0 else cd

        results[f"mean_elev_{radius}m"] = float(np.mean(cd))
        results[f"min_elev_{radius}m"] = float(np.min(cd))
        results[f"max_elev_{radius}m"] = float(np.max(cd))
        results[f"std_elev_{radius}m"] = float(np.std(cd))
        results[f"ring_mean_{radius}m"] = float(np.mean(rd))
        results[f"depression_{radius}m"] = float(np.mean(rd) - center_elev)

    # Slope
    sm = (dist <= 100) & valid
    if sm.sum() > 10:
        gy, gx = np.gradient(data, res_m)
        slope = np.degrees(np.arctan(np.sqrt(gx**2 + gy**2)))
        results["mean_slope_100m_deg"] = float(np.mean(slope[sm]))
        results["max_slope_100m_deg"] = float(np.max(slope[sm]))
        results["std_slope_100m_deg"] = float(np.std(slope[sm]))

    # Roughness
    rm = (dist <= 250) & valid
    if rm.sum() > 10:
        results["roughness_250m"] = float(np.std(data[rm]))

    # Percentile
    fm = (dist <= 500) & valid
    if fm.sum() > 10:
        results["elev_percentile_500m"] = float(
            np.sum(data[fm] <= center_elev) / fm.sum() * 100
        )

    return results


def main():
    print("Building 5m tile index...")
    index_5m = build_5m_index()
    print(f"  {len(index_5m)} tiles")

    print("Opening 15m CEM...")
    cem = get_ds(CEM_15M)
    # CEM is in geographic coords — resolution in degrees, need meters
    # At ~20.5°N, 1 degree lat ≈ 110.9 km, 1 degree lon ≈ 103.6 km
    cem_res_m = 15.0  # nominal

    print("Loading cenotes...")
    with open(CENOTE_CSV) as f:
        cenotes = list(csv.DictReader(f))

    deep = [c for c in cenotes if c["DEPTH"] and c["DEPTH"] not in ("", "0")]
    deep_tiles = set(c["TOPO"] for c in deep if c["TOPO"])
    study = [c for c in cenotes if c["TOPO"] in deep_tiles]
    print(f"  {len(deep)} deep, {len(study)} in study area")

    all_results = []
    failed = 0

    for i, c in enumerate(study):
        lat = float(c["LATITUDE_"])
        lon = float(c["LONGITUDE_"])
        name = c["NAME"]
        depth = c["DEPTH"] if c["DEPTH"] and c["DEPTH"] not in ("", "0") else ""

        # Try 5m first
        path_5m, ux, uy = find_5m_tile(lat, lon, index_5m)
        if path_5m:
            src = get_ds(path_5m)
            stats = analyze_point(src, ux, uy, 5.0)
            dem_res = "5m"
        else:
            # Fallback to 15m CEM (geographic CRS — use lon, lat as x, y)
            stats = analyze_point(cem, lon, lat, cem_res_m)
            dem_res = "15m"

        if stats is None:
            failed += 1
            continue

        result = {
            "name": name,
            "depth_m": depth,
            "lat": lat,
            "lon": lon,
            "municipio": c["MUNICIPIO"],
            "topo_50k": c["TOPO"],
            "dem_resolution": dem_res,
            **stats,
        }
        all_results.append(result)

        if depth:
            d250 = stats.get("depression_250m", 0)
            slp = stats.get("mean_slope_100m_deg", 0)
            print(f"  {name:40s} depth={depth:>4s}m  elev={stats['center_elev_m']:>6.1f}m  "
                  f"dep@250={d250:>5.1f}m  slope={slp:>4.1f}°  [{dem_res}]")

        if (i + 1) % 100 == 0:
            print(f"  ... {i+1}/{len(study)}")

    print(f"\nAnalyzed {len(all_results)} cenotes ({failed} failed)")

    # Write CSV
    if all_results:
        fieldnames = list(all_results[0].keys())
        with open(OUTPUT_CSV, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(all_results)
        print(f"Saved CSV: {OUTPUT_CSV}")

    # Write markdown
    deep_results = sorted(
        [r for r in all_results if r["depth_m"]],
        key=lambda r: int(r["depth_m"]),
        reverse=True,
    )
    no_depth = [r for r in all_results if not r["depth_m"]]

    with open(OUTPUT_MD, "w") as f:
        f.write("# Deep Cenote Terrain Analysis\n\n")
        f.write(f"Analyzed {len(deep_results)} cenotes with known depth + "
                f"{len(no_depth)} nearby without depth data.\n\n")
        f.write("DEM: INEGI 5m terrain (where available), 15m CEM 4.0 fallback.\n\n")

        f.write("## Summary Table — Deep Cenotes\n\n")
        f.write("| Name | Depth | Elev | Dep @100m | Dep @250m | Dep @500m | "
                "Slope | Rough | %ile | DEM |\n")
        f.write("|------|-------|------|----------|----------|----------|"
                "-------|-------|------|-----|\n")
        for r in deep_results:
            f.write(
                f"| {r['name']} | {r['depth_m']}m "
                f"| {r['center_elev_m']:.1f}m "
                f"| {r.get('depression_100m', 0):.1f}m "
                f"| {r.get('depression_250m', 0):.1f}m "
                f"| {r.get('depression_500m', 0):.1f}m "
                f"| {r.get('mean_slope_100m_deg', 0):.1f}° "
                f"| {r.get('roughness_250m', 0):.1f}m "
                f"| {r.get('elev_percentile_500m', 0):.0f}% "
                f"| {r['dem_resolution']} |\n"
            )

        f.write("\n## Individual Profiles\n\n")
        for r in deep_results:
            f.write(f"### {r['name']} — {r['depth_m']}m deep\n\n")
            f.write(f"- **Location:** {r['lat']:.4f}°N, {r['lon']:.4f}°W | "
                    f"{r['municipio']} | {r['topo_50k']} | DEM: {r['dem_resolution']}\n")
            f.write(f"- **Surface elevation:** {r['center_elev_m']:.1f}m\n")
            for radius in RADII:
                dep = r.get(f"depression_{radius}m")
                ring = r.get(f"ring_mean_{radius}m")
                if dep is not None:
                    f.write(f"- **@{radius}m:** {dep:.1f}m below surroundings "
                            f"(ring: {ring:.1f}m, min: {r.get(f'min_elev_{radius}m',0):.1f}m, "
                            f"max: {r.get(f'max_elev_{radius}m',0):.1f}m)\n")
            slp = r.get("mean_slope_100m_deg", 0)
            mslp = r.get("max_slope_100m_deg", 0)
            f.write(f"- **Slope (100m):** mean {slp:.1f}°, max {mslp:.1f}°\n")
            f.write(f"- **Roughness:** {r.get('roughness_250m', 0):.2f}m\n")
            pct = r.get("elev_percentile_500m", 50)
            f.write(f"- **Elev percentile (500m):** {pct:.0f}%\n")

            dep250 = r.get("depression_250m", 0)
            if dep250 > 3 and pct < 15:
                f.write("- **Signature: STRONG** — clear topographic depression\n")
            elif dep250 > 1:
                f.write("- **Signature: MODERATE** — subtle but detectable low\n")
            elif dep250 < 0.5 and slp < 1.5:
                f.write("- **Signature: FLAT** — no visible depression in DEM\n")
            else:
                f.write("- **Signature: WEAK** — ambiguous surface expression\n")
            f.write("\n")

        # Stats comparison
        f.write("## Statistical Comparison: Deep vs Unmeasured\n\n")
        for label, group in [("Deep (measured)", deep_results), ("No depth data", no_depth)]:
            if not group:
                continue
            f.write(f"### {label} (n={len(group)})\n\n")
            f.write("| Metric | Mean | Median | Min | Max |\n")
            f.write("|--------|------|--------|-----|-----|\n")
            for mname, key in [
                ("Depression @250m (m)", "depression_250m"),
                ("Mean slope 100m (°)", "mean_slope_100m_deg"),
                ("Roughness 250m (m)", "roughness_250m"),
                ("Elev percentile (%)", "elev_percentile_500m"),
                ("Surface elev (m)", "center_elev_m"),
            ]:
                vals = np.array([r.get(key, 0) for r in group])
                f.write(f"| {mname} | {np.mean(vals):.1f} | {np.median(vals):.1f} "
                        f"| {np.min(vals):.1f} | {np.max(vals):.1f} |\n")
            f.write("\n")

    print(f"Saved MD: {OUTPUT_MD}")


if __name__ == "__main__":
    main()
