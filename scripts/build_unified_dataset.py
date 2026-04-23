#!/usr/bin/env python3
"""
Build cenotes_unified.json — a single clean dataset merging all sources.

Base: ArcGIS CSV (1,367 cenotes, full-precision coords)
Enrichment: terrain analysis CSV (763), sidecar feature JSONs (~1,360 each),
            neighbor JSON (~761), preserved geology/road fields from slim JSON.

Outputs human-readable field names. Drops: population, curvature, NDMI, composite score.
"""

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

# ── Input files ──────────────────────────────────────────────────────────────

ARCGIS_CSV = DATA_DIR / "cenotes_arcgis.csv"
TERRAIN_CSV = DATA_DIR / "cenote_terrain_analysis.csv"
NEIGHBORS_JSON = DATA_DIR / "cenote_neighbors.json"
EXISTING_SLIM = DATA_DIR / "cenotes_slim.json"

# Sidecar feature files: (path, {source_key: unified_key})
SIDECAR_FILES = [
    (DATA_DIR / "hydrology_features.json", {
        "sink_depth_max_100m": "sink_depth",
        "sink_depth_mean_250m": "sink_depth_mean",
        "in_depression": "in_depression",
        "depression_area_m2": "depression_area",
        "flow_accum_at_point": "flow_accum",
        "flow_accum_max_250m": "flow_accum_max",
    }),
    (DATA_DIR / "lineament_features.json", {
        "lineament_dist_min": "lineament_dist_min",
        "lineament_count_500m": "lineament_count_500m",
        "lineament_dominant_az": "lineament_azimuth",
        "on_lineament": "on_lineament",
    }),
    (DATA_DIR / "ndvi_features.json", {
        "ndvi_dry": "ndvi_dry",
        "ndvi_diff": "ndvi_diff",
        "ndvi_zscore": "ndvi_zscore",
        "ndvi_zscore_max_100m": "ndvi_zscore_max",
    }),
    (DATA_DIR / "canopy_features.json", {
        "canopy_mean": "canopy_height",
        "canopy_min": "canopy_height_min",
        "canopy_std": "canopy_height_std",
        "canopy_gap_fraction": "canopy_gap_fraction",
    }),
    (DATA_DIR / "thermal_features.json", {
        "lst_anomaly": "lst_anomaly",
    }),
]

# Fields preserved from existing slim JSON (computed interactively, no script yet)
# Maps slim abbreviated key -> unified human-readable key
PRESERVED_FIELDS = {
    "lth": "lithology",
    "age": "geology_age",
    "ta": "age_ma_top",
    "ba": "age_ma_bottom",
    "cst": "coast_distance_km",
    "rd": "road_distance_km",
    "rdt": "road_type",
}

NEIGHBOR_FIELDS = {
    "nn_dist": "nearest_neighbor_km",
    "nn3_dist": "third_nearest_km",
    "n_1km": "neighbors_1km",
    "n_3km": "neighbors_3km",
    "n_5km": "neighbors_5km",
    "nn_bearing": "nearest_bearing",
}


def try_float(v, decimals=2):
    """Convert to float and round; return None for empty/invalid."""
    if v is None or v == "":
        return None
    try:
        return round(float(v), decimals)
    except (ValueError, TypeError):
        return v


def make_key(name, lat, lon):
    """Build lookup key matching sidecar file format: 'name|lat|lon'."""
    return f"{name}|{lat}|{lon}"


def main():
    # ── Step 1a: Load ArcGIS base (all 1,367) ───────────────────────────
    print("Loading ArcGIS CSV...")
    with open(ARCGIS_CSV) as f:
        arcgis_rows = list(csv.DictReader(f))
    print(f"  {len(arcgis_rows)} cenotes")

    # Build base entries
    entries = []
    for row in arcgis_rows:
        lat_str = row.get("LATITUDE_", "").strip()
        lon_str = row.get("LONGITUDE_", "").strip()
        if not lat_str or not lon_str:
            continue

        depth_raw = try_float(row.get("DEPTH"), 1)
        length_raw = try_float(row.get("LENGTH"), 1)

        entries.append({
            "name": row.get("NAME", "").strip(),
            "alt_names": row.get("ALT_NAMES", "").strip() or None,
            "lat": float(lat_str),
            "lon": float(lon_str),
            "municipio": row.get("MUNICIPIO", "").strip() or None,
            "state": row.get("STATE", "").strip() or None,
            "depth": depth_raw if depth_raw and depth_raw > 0 else None,
            "length": length_raw if length_raw and length_raw > 0 else None,
            "topo": row.get("TOPO", "").strip() or None,
            "elevation": try_float(row.get("ELEV"), 1),
            "has_terrain": False,
        })

    print(f"  {len(entries)} valid entries")

    # Index by name+lat+lon for merging (use string representations)
    # ArcGIS has full precision like "20.7172475"
    entry_by_key = {}
    for e in entries:
        key = make_key(e["name"], e["lat"], e["lon"])
        entry_by_key[key] = e

    # ── Step 1b: Merge terrain analysis (763) ────────────────────────────
    print("\nLoading terrain analysis CSV...")
    with open(TERRAIN_CSV) as f:
        terrain_rows = list(csv.DictReader(f))
    print(f"  {len(terrain_rows)} cenotes")

    terrain_matched = 0
    terrain_by_key = {}  # also keep for sidecar lookups
    for row in terrain_rows:
        name = row["name"]
        lat = row["lat"]
        lon = row["lon"]
        tkey = make_key(name, lat, lon)
        terrain_by_key[tkey] = row

        # Match to ArcGIS entry
        entry = entry_by_key.get(tkey)
        if not entry:
            # Try matching by name + rounded coords
            for e in entries:
                if e["name"] == name and abs(e["lat"] - float(lat)) < 0.001 and abs(e["lon"] - float(lon)) < 0.001:
                    entry = e
                    break

        if entry:
            terrain_matched += 1
            entry["has_terrain"] = True
            entry["dem_resolution"] = row.get("dem_resolution", "").strip() or None
            # Override elevation with DEM-derived value
            elev = try_float(row.get("center_elev_m"), 1)
            if elev is not None:
                entry["elevation"] = elev
            # Depression profile
            entry["depression_50m"] = try_float(row.get("depression_50m"))
            entry["depression_100m"] = try_float(row.get("depression_100m"))
            entry["depression_250m"] = try_float(row.get("depression_250m"))
            entry["depression_500m"] = try_float(row.get("depression_500m"))
            # Slope and terrain
            entry["mean_slope"] = try_float(row.get("mean_slope_100m_deg"))
            entry["max_slope"] = try_float(row.get("max_slope_100m_deg"))
            entry["roughness"] = try_float(row.get("roughness_250m"))
            entry["elev_percentile"] = try_float(row.get("elev_percentile_500m"))
            entry["min_elev_250m"] = try_float(row.get("min_elev_250m"))
            entry["max_elev_250m"] = try_float(row.get("max_elev_250m"))
            entry["ring_mean_250m"] = try_float(row.get("ring_mean_250m"))

    # Add terrain-only cenotes not found in ArcGIS (e.g., from other sources)
    terrain_only = 0
    for row in terrain_rows:
        name = row["name"]
        lat = float(row["lat"])
        lon = float(row["lon"])
        tkey = make_key(name, row["lat"], row["lon"])
        # Check if already matched
        matched = any(
            e["name"] == name and abs(e["lat"] - lat) < 0.001 and abs(e["lon"] - lon) < 0.001
            for e in entries
        )
        if not matched:
            terrain_only += 1
            entry = {
                "name": name,
                "lat": lat,
                "lon": lon,
                "municipio": row.get("municipio", "").strip() or None,
                "state": "Yucatan",
                "depth": try_float(row.get("depth_m"), 1),
                "topo": row.get("topo_50k", "").strip() or None,
                "has_terrain": True,
                "dem_resolution": row.get("dem_resolution", "").strip() or None,
            }
            elev = try_float(row.get("center_elev_m"), 1)
            if elev is not None:
                entry["elevation"] = elev
            entry["depression_50m"] = try_float(row.get("depression_50m"))
            entry["depression_100m"] = try_float(row.get("depression_100m"))
            entry["depression_250m"] = try_float(row.get("depression_250m"))
            entry["depression_500m"] = try_float(row.get("depression_500m"))
            entry["mean_slope"] = try_float(row.get("mean_slope_100m_deg"))
            entry["max_slope"] = try_float(row.get("max_slope_100m_deg"))
            entry["roughness"] = try_float(row.get("roughness_250m"))
            entry["elev_percentile"] = try_float(row.get("elev_percentile_500m"))
            entry["min_elev_250m"] = try_float(row.get("min_elev_250m"))
            entry["max_elev_250m"] = try_float(row.get("max_elev_250m"))
            entry["ring_mean_250m"] = try_float(row.get("ring_mean_250m"))
            entries.append(entry)
            akey = make_key(name, lat, lon)
            entry_by_key[akey] = entry

    if terrain_only:
        print(f"  Added {terrain_only} terrain-only cenotes not in ArcGIS")

    print(f"  Matched {terrain_matched} to ArcGIS entries")

    # ── Step 1c: Merge sidecar feature files ─────────────────────────────
    # Sidecar keys use the terrain CSV format: "name|lat|lon" with full precision
    # We need to try both the ArcGIS key and the terrain key for each entry

    sidecar_data = {}
    for path, mapping in SIDECAR_FILES:
        if path.exists():
            print(f"\nLoading {path.name}...")
            with open(path) as f:
                sidecar_data[path] = json.load(f)
            print(f"  {len(sidecar_data[path])} entries")
        else:
            print(f"  Skipping {path.name} (not found)")

    # Build a reverse lookup: for each ArcGIS entry, find its terrain key
    # (sidecar files use terrain CSV coordinates as keys)
    arcgis_to_terrain_key = {}
    for row in terrain_rows:
        name = row["name"]
        lat = row["lat"]
        lon = row["lon"]
        tkey = make_key(name, lat, lon)
        # Find matching ArcGIS entry
        for e in entries:
            if e["name"] == name and abs(e["lat"] - float(lat)) < 0.001 and abs(e["lon"] - float(lon)) < 0.001:
                akey = make_key(e["name"], e["lat"], e["lon"])
                arcgis_to_terrain_key[akey] = tkey
                break

    # Now also check: sidecar files might use ArcGIS-precision keys directly
    # (some scripts load from cenotes_arcgis.csv via grid_utils.load_cenotes)
    for entry in entries:
        akey = make_key(entry["name"], entry["lat"], entry["lon"])
        tkey = arcgis_to_terrain_key.get(akey)

        for path, mapping in SIDECAR_FILES:
            if path not in sidecar_data:
                continue
            data = sidecar_data[path]

            # Try ArcGIS key first, then terrain key
            feat = data.get(akey) or (data.get(tkey) if tkey else None)
            if not feat:
                continue

            for src_key, unified_key in mapping.items():
                val = feat.get(src_key)
                if isinstance(val, bool):
                    entry[unified_key] = val
                elif isinstance(val, (int, float)):
                    entry[unified_key] = round(val, 2) if isinstance(val, float) else val
                else:
                    entry[unified_key] = val

    # Count sidecar coverage
    for path, mapping in SIDECAR_FILES:
        if path in sidecar_data:
            first_key = list(mapping.values())[0]
            count = sum(1 for e in entries if first_key in e and e[first_key] is not None)
            print(f"  {path.name}: matched {count}/{len(entries)}")

    # ── Step 1d: Merge preserved fields from existing slim JSON ──────────
    print("\nLoading existing slim JSON for preserved fields...")
    if EXISTING_SLIM.exists():
        with open(EXISTING_SLIM) as f:
            existing = json.load(f)
        print(f"  {len(existing)} entries")

        # Index slim by name (for fuzzy matching) and by rounded coords
        slim_by_name = {}
        slim_by_coords = {}
        for c in existing:
            slim_by_name[c.get("n", "")] = c
            lat2 = round(c.get("la", 0), 2)
            lon2 = round(c.get("lo", 0), 2)
            slim_by_coords[(lat2, lon2)] = c

        preserved_count = 0
        for entry in entries:
            # Match by 2-decimal coords (slim truncated to 2 decimals)
            lat2 = round(entry["lat"], 2)
            lon2 = round(entry["lon"], 2)
            slim = slim_by_coords.get((lat2, lon2)) or slim_by_name.get(entry["name"])
            if not slim:
                continue

            any_found = False
            for slim_key, unified_key in PRESERVED_FIELDS.items():
                if slim_key in slim and slim[slim_key] is not None:
                    entry[unified_key] = slim[slim_key]
                    any_found = True
            if any_found:
                preserved_count += 1

        print(f"  Preserved geology/road fields for {preserved_count} cenotes")

    # ── Step 1e: Merge neighbor data ─────────────────────────────────────
    print("\nLoading neighbor data...")
    with open(NEIGHBORS_JSON) as f:
        neighbors = json.load(f)
    print(f"  {len(neighbors)} entries")

    nb_matched = 0
    for entry in entries:
        akey = make_key(entry["name"], entry["lat"], entry["lon"])
        tkey = arcgis_to_terrain_key.get(akey)

        nb = neighbors.get(akey) or (neighbors.get(tkey) if tkey else None)
        if not nb:
            continue

        nb_matched += 1
        for src_key, unified_key in NEIGHBOR_FIELDS.items():
            entry[unified_key] = nb.get(src_key)

    print(f"  Matched {nb_matched} cenotes")

    # ── Step 1f: Clean up and write output ───────────────────────────────
    # Remove None values to keep JSON compact
    result = []
    for entry in entries:
        clean = {k: v for k, v in entry.items() if v is not None}
        result.append(clean)

    output_path = DATA_DIR / "cenotes_unified.json"
    with open(output_path, "w") as f:
        json.dump(result, f, ensure_ascii=False, separators=(",", ":"))

    file_size_kb = output_path.stat().st_size / 1024
    print(f"\nSaved {len(result)} cenotes -> {output_path} ({file_size_kb:.0f} KB)")

    # ── Summary ──────────────────────────────────────────────────────────
    has_terrain = sum(1 for e in result if e.get("has_terrain"))
    has_depth = sum(1 for e in result if e.get("depth"))
    has_lineament = sum(1 for e in result if "lineament_dist_min" in e)
    has_ndvi = sum(1 for e in result if "ndvi_dry" in e)
    has_geology = sum(1 for e in result if "lithology" in e)
    has_neighbors = sum(1 for e in result if "nearest_neighbor_km" in e)

    print(f"\n-- Coverage Summary --")
    print(f"  Total cenotes:    {len(result)}")
    print(f"  With terrain:     {has_terrain}")
    print(f"  With depth:       {has_depth}")
    print(f"  With lineaments:  {has_lineament}")
    print(f"  With NDVI:        {has_ndvi}")
    print(f"  With geology:     {has_geology}")
    print(f"  With neighbors:   {has_neighbors}")

    # Show sample
    if result:
        sample = result[0]
        print(f"\nSample entry ({len(sample)} fields):")
        print(json.dumps(sample, indent=2, ensure_ascii=False)[:600])


if __name__ == "__main__":
    main()
