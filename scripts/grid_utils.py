"""Shared utilities for cenote feature extraction scripts."""

import csv
import json
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import rowcol
from rasterio.warp import transform as warp_transform

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DEM_DIR_5M = DATA_DIR / "inegi_5m" / "extracted" / "conjunto_de_datos"
CEM_15M = DATA_DIR / "inegi_dem" / "v4" / "conjunto_de_datos" / "31_Yucatán_r15m_v4.tif"
CENOTE_CSV = DATA_DIR / "cenotes_arcgis.csv"

# Cache open rasterio datasets
_ds_cache = {}


def get_ds(path):
    """Get (or cache) an open rasterio dataset."""
    if path not in _ds_cache:
        _ds_cache[path] = rasterio.open(path)
    return _ds_cache[path]


def load_cenotes(csv_path=None):
    """Load cenotes from CSV, return list of dicts with name, lat, lon, etc."""
    csv_path = csv_path or CENOTE_CSV
    with open(csv_path) as f:
        rows = list(csv.DictReader(f))

    cenotes = []
    for r in rows:
        lat = r.get("lat") or r.get("LATITUDE_")
        lon = r.get("lon") or r.get("LONGITUDE_")
        name = r.get("name") or r.get("NAME")
        if not lat or not lon:
            continue
        cenotes.append({
            "name": name,
            "lat": float(lat),
            "lon": float(lon),
            "depth": r.get("depth_m") or r.get("DEPTH") or "",
            "municipio": r.get("municipio") or r.get("MUNICIPIO", ""),
            "topo": r.get("topo_50k") or r.get("TOPO", ""),
        })
    return cenotes


def cenote_key(c):
    """Generate a unique key for a cenote: 'name|lat|lon'."""
    return f"{c['name']}|{c['lat']}|{c['lon']}"


def build_5m_index():
    """Build spatial index of 5m BIL tiles: {path: (bounds, crs)}."""
    index = {}
    for bil in sorted(DEM_DIR_5M.glob("*.bil")):
        try:
            with rasterio.open(bil) as src:
                index[bil] = (src.bounds, src.crs)
        except Exception:
            pass
    print(f"  5m tile index: {len(index)} tiles")
    return index


def find_5m_tile(lat, lon, index_5m):
    """Find a 5m tile containing the point. Returns (path, x, y) in tile CRS."""
    for path, (bounds, crs) in index_5m.items():
        xs, ys = warp_transform("EPSG:4326", crs, [lon], [lat])
        x, y = xs[0], ys[0]
        if bounds.left <= x <= bounds.right and bounds.bottom <= y <= bounds.top:
            return path, x, y
    return None, None, None


def sample_raster_at_point(src, center_x, center_y, radius_m, res_m):
    """
    Extract raster values within a circle around a point.

    Args:
        src: open rasterio dataset
        center_x, center_y: point in the dataset's CRS
        radius_m: radius in meters
        res_m: pixel resolution in meters

    Returns:
        dict with 'data' (2D array), 'mask' (boolean circle mask),
        'center_row', 'center_col' (local indices), or None if point is outside.
    """
    row_c, col_c = rowcol(src.transform, center_x, center_y)
    if not (0 <= row_c < src.height and 0 <= col_c < src.width):
        return None

    buf_px = int(radius_m / res_m) + 5
    r0 = max(0, row_c - buf_px)
    c0 = max(0, col_c - buf_px)
    r1 = min(src.height, row_c + buf_px + 1)
    c1 = min(src.width, col_c + buf_px + 1)

    window = rasterio.windows.Window(c0, r0, c1 - c0, r1 - r0)
    data = src.read(1, window=window).astype(np.float64)

    lr = row_c - r0
    lc = col_c - c0

    # Check for nodata
    nodata = src.nodata
    if nodata is not None:
        valid = data != nodata
    else:
        valid = data > -999

    if not valid[lr, lc]:
        return None

    # Distance grid in meters
    ri = np.arange(data.shape[0])
    ci = np.arange(data.shape[1])
    cg, rg = np.meshgrid(ci, ri)
    dist = np.sqrt(((rg - lr) * res_m) ** 2 + ((cg - lc) * res_m) ** 2)

    circle_mask = (dist <= radius_m) & valid

    return {
        "data": data,
        "valid": valid,
        "dist": dist,
        "circle_mask": circle_mask,
        "lr": lr,
        "lc": lc,
        "window": window,
        "res_m": res_m,
    }


def save_features(features, output_path):
    """Save feature dict to JSON (keyed by 'name|lat|lon')."""
    output_path = Path(output_path)
    with open(output_path, "w") as f:
        json.dump(features, f, indent=2, ensure_ascii=False)
    print(f"Saved {len(features)} entries → {output_path}")


def load_features(path):
    """Load a feature sidecar JSON."""
    with open(path) as f:
        return json.load(f)


def iter_cenotes_with_dem(cenotes, index_5m, cem_src=None):
    """
    Iterate cenotes, yielding (cenote, src, x, y, res_m) for each.
    Tries 5m tile first, falls back to 15m CEM.
    """
    if cem_src is None:
        cem_src = get_ds(CEM_15M)

    for c in cenotes:
        lat, lon = c["lat"], c["lon"]
        path_5m, ux, uy = find_5m_tile(lat, lon, index_5m)
        if path_5m:
            yield c, get_ds(path_5m), ux, uy, 5.0
        else:
            yield c, cem_src, lon, lat, 15.0
