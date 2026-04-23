#!/usr/bin/env python3
"""
Compute NDVI vegetation anomaly features for each cenote using Sentinel-2 data.

Uses Microsoft Planetary Computer STAC API to access Sentinel-2 L2A imagery.
Computes dry-season (Feb-Apr) vs wet-season (Jul-Sep) NDVI composites at 10m.
Also computes NDMI (Normalized Difference Moisture Index) from SWIR band.

Per cenote: ndvi_dry, ndvi_diff, ndvi_zscore, ndvi_zscore_max_100m, ndmi_dry
"""

import json
import os
import warnings
from pathlib import Path

import numpy as np

from scripts.grid_utils import DATA_DIR, load_cenotes, cenote_key, save_features

OUTPUT = DATA_DIR / "ndvi_features.json"
NDVI_DRY_TIF = DATA_DIR / "ndvi_dry.tif"
NDVI_WET_TIF = DATA_DIR / "ndvi_wet.tif"
NDVI_ZSCORE_TIF = DATA_DIR / "ndvi_zscore.tif"

# Study area bbox [west, south, east, north]
BBOX = [-90.5, 20.0, -87.4, 21.8]

# Seasons (Yucatan)
DRY_MONTHS = [2, 3, 4]   # Feb-Apr
WET_MONTHS = [7, 8, 9]   # Jul-Sep


def search_sentinel2(bbox, date_range, max_cloud=20):
    """Search Planetary Computer for Sentinel-2 L2A scenes."""
    import planetary_computer as pc
    import pystac_client

    catalog = pystac_client.Client.open(
        "https://planetarycomputer.microsoft.com/api/stac/v1",
        modifier=pc.sign_inplace,
    )

    search = catalog.search(
        collections=["sentinel-2-l2a"],
        bbox=bbox,
        datetime=date_range,
        query={"eo:cloud_cover": {"lt": max_cloud}},
    )

    items = list(search.items())
    print(f"  Found {len(items)} scenes for {date_range} (cloud<{max_cloud}%)")
    return items


def load_composite(items, bbox, bands, resolution=10):
    """Load a median composite from STAC items using odc-stac."""
    import odc.stac

    if not items:
        return None

    ds = odc.stac.load(
        items,
        bands=bands,
        bbox=bbox,
        resolution=resolution,
        groupby="solar_day",
        chunks={"x": 2048, "y": 2048},
    )

    # Cloud masking using SCL band
    if "SCL" in ds:
        # SCL values: 4=vegetation, 5=bare soil, 6=water, 7=low cloud prob
        # Mask out: 0=nodata, 1=saturated, 3=shadow, 8-10=clouds
        good = ds["SCL"].isin([4, 5, 6, 7, 11])
        for band in bands:
            if band != "SCL":
                ds[band] = ds[band].where(good)

    # Compute median composite
    composite = ds.median(dim="time").compute()
    return composite


def compute_ndvi(composite, red_band="B04", nir_band="B08"):
    """Compute NDVI from a composite dataset."""
    red = composite[red_band].values.astype(np.float64)
    nir = composite[nir_band].values.astype(np.float64)

    # Scale factor for L2A reflectance
    red = red / 10000.0
    nir = nir / 10000.0

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ndvi = (nir - red) / (nir + red + 1e-10)

    ndvi = np.clip(ndvi, -1, 1)
    ndvi[np.isnan(red) | np.isnan(nir)] = np.nan
    return ndvi


def compute_ndmi(composite, nir_band="B08", swir_band="B11"):
    """Compute NDMI (Normalized Difference Moisture Index)."""
    nir = composite[nir_band].values.astype(np.float64) / 10000.0
    swir = composite[swir_band].values.astype(np.float64) / 10000.0

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ndmi = (nir - swir) / (nir + swir + 1e-10)

    ndmi = np.clip(ndmi, -1, 1)
    ndmi[np.isnan(nir) | np.isnan(swir)] = np.nan
    return ndmi


def compute_local_zscore(data, window_size_px=50):
    """Compute local z-score: how anomalous each pixel is relative to its neighborhood."""
    from scipy.ndimage import uniform_filter

    # Compute local mean and std
    valid = ~np.isnan(data)
    data_filled = data.copy()
    data_filled[~valid] = 0

    count = uniform_filter(valid.astype(float), size=window_size_px)
    local_mean = uniform_filter(data_filled, size=window_size_px)
    local_sq_mean = uniform_filter(data_filled**2, size=window_size_px)

    # Avoid division by zero
    count = np.maximum(count, 1e-10)
    local_mean = local_mean / count * valid.astype(float).mean()
    local_var = local_sq_mean / count * valid.astype(float).mean() - local_mean**2
    local_std = np.sqrt(np.maximum(local_var, 0))

    zscore = np.where(
        (local_std > 0.01) & valid,
        (data - local_mean) / local_std,
        0
    )
    zscore[~valid] = np.nan
    return zscore


def save_geotiff(data, reference_ds, output_path, band_name="B04"):
    """Save a 2D array as GeoTIFF using spatial info from odc-stac dataset."""
    import rasterio
    from rasterio.transform import from_bounds

    h, w = data.shape
    ref = reference_ds[band_name]
    x = ref.coords["x"].values
    y = ref.coords["y"].values

    transform = from_bounds(x.min(), y.min(), x.max(), y.max(), w, h)

    # Get CRS from the dataset
    crs = ref.odc.crs if hasattr(ref, "odc") else "EPSG:4326"

    profile = {
        "driver": "GTiff",
        "dtype": "float32",
        "width": w,
        "height": h,
        "count": 1,
        "crs": str(crs),
        "transform": transform,
        "compress": "lzw",
        "nodata": np.nan,
    }

    with rasterio.open(output_path, "w", **profile) as dst:
        dst.write(data.astype(np.float32), 1)
    print(f"  Saved {output_path}")


def extract_features_at_cenotes(cenotes, ndvi_dry, ndvi_wet, ndvi_zscore, ndmi_dry, composite_ds, band_name="B04"):
    """Extract NDVI features at each cenote location."""
    import rasterio
    from rasterio.transform import from_bounds, rowcol

    ref = composite_ds[band_name]
    x = ref.coords["x"].values
    y = ref.coords["y"].values
    h, w = ndvi_dry.shape

    transform = from_bounds(x.min(), y.min(), x.max(), y.max(), w, h)
    crs_str = str(ref.odc.crs) if hasattr(ref, "odc") else "EPSG:4326"

    # Need to convert cenote lat/lon to raster CRS
    from rasterio.warp import transform as warp_transform

    results = {}
    for c in cenotes:
        lat, lon = c["lat"], c["lon"]

        # Transform to raster CRS
        if crs_str != "EPSG:4326":
            xs, ys = warp_transform("EPSG:4326", crs_str, [lon], [lat])
            px, py = xs[0], ys[0]
        else:
            px, py = lon, lat

        try:
            row, col = rowcol(transform, px, py)
        except Exception:
            continue

        if not (0 <= row < h and 0 <= col < w):
            continue

        features = {}

        # Point values
        if not np.isnan(ndvi_dry[row, col]):
            features["ndvi_dry"] = round(float(ndvi_dry[row, col]), 4)

        if ndvi_wet is not None and not np.isnan(ndvi_wet[row, col]):
            ndvi_diff = float(ndvi_wet[row, col] - ndvi_dry[row, col])
            features["ndvi_diff"] = round(ndvi_diff, 4)

        if ndvi_zscore is not None and not np.isnan(ndvi_zscore[row, col]):
            features["ndvi_zscore"] = round(float(ndvi_zscore[row, col]), 3)

        if ndmi_dry is not None and not np.isnan(ndmi_dry[row, col]):
            features["ndmi_dry"] = round(float(ndmi_dry[row, col]), 4)

        # Max zscore within 100m (~10 pixels at 10m)
        if ndvi_zscore is not None:
            buf = 10
            r0, r1 = max(0, row - buf), min(h, row + buf + 1)
            c0, c1 = max(0, col - buf), min(w, col + buf + 1)
            patch = ndvi_zscore[r0:r1, c0:c1]
            valid_patch = patch[~np.isnan(patch)]
            if len(valid_patch) > 0:
                features["ndvi_zscore_max_100m"] = round(float(np.max(valid_patch)), 3)

        if features:
            results[cenote_key(c)] = features

    return results


def main():
    print("=== Sentinel-2 NDVI Anomaly Analysis ===\n")

    print("Loading cenotes...")
    cenotes = load_cenotes()
    print(f"  {len(cenotes)} cenotes")

    # Search for imagery
    print("\nSearching Planetary Computer for Sentinel-2 scenes...")

    # Use 2024-2025 for good coverage
    dry_items = search_sentinel2(BBOX, "2024-02-01/2025-04-30", max_cloud=15)
    # Filter to dry months only
    dry_items = [
        item for item in dry_items
        if int(item.datetime.strftime("%m")) in DRY_MONTHS
    ]
    print(f"  Dry season scenes (Feb-Apr): {len(dry_items)}")

    wet_items = search_sentinel2(BBOX, "2024-07-01/2025-09-30", max_cloud=30)
    wet_items = [
        item for item in wet_items
        if int(item.datetime.strftime("%m")) in WET_MONTHS
    ]
    print(f"  Wet season scenes (Jul-Sep): {len(wet_items)}")

    # Limit scenes to avoid memory issues — take most recent
    max_scenes = 50
    if len(dry_items) > max_scenes:
        dry_items = sorted(dry_items, key=lambda i: i.datetime, reverse=True)[:max_scenes]
        print(f"  Limited dry scenes to {max_scenes}")
    if len(wet_items) > max_scenes:
        wet_items = sorted(wet_items, key=lambda i: i.datetime, reverse=True)[:max_scenes]
        print(f"  Limited wet scenes to {max_scenes}")

    # Load composites
    bands_10m = ["B04", "B08", "SCL"]   # Red, NIR, Scene Classification
    bands_20m = ["B08", "B11", "SCL"]    # NIR, SWIR (20m native)

    print("\nLoading dry-season composite (10m)...")
    dry_composite = load_composite(dry_items, BBOX, bands_10m, resolution=10)
    if dry_composite is None:
        print("ERROR: No dry-season data available")
        return

    print("Loading wet-season composite (10m)...")
    wet_composite = load_composite(wet_items, BBOX, bands_10m, resolution=10)

    # NDMI uses B11 (SWIR) at 20m — load separately at 20m then we'll extract at point level
    print("Loading dry-season SWIR composite (20m for NDMI)...")
    dry_swir = load_composite(dry_items, BBOX, bands_20m, resolution=20)

    # Compute indices
    print("\nComputing NDVI...")
    ndvi_dry = compute_ndvi(dry_composite)
    print(f"  Dry NDVI: mean={np.nanmean(ndvi_dry):.3f}, range=[{np.nanmin(ndvi_dry):.3f}, {np.nanmax(ndvi_dry):.3f}]")

    ndvi_wet = None
    if wet_composite is not None:
        ndvi_wet = compute_ndvi(wet_composite)
        print(f"  Wet NDVI: mean={np.nanmean(ndvi_wet):.3f}")

    ndmi_dry = None
    if dry_swir is not None:
        ndmi_dry = compute_ndmi(dry_swir)
        print(f"  Dry NDMI: mean={np.nanmean(ndmi_dry):.3f}")

    # Local z-score (~500m window = 50 pixels at 10m)
    print("Computing local NDVI z-score...")
    ndvi_zscore = compute_local_zscore(ndvi_dry, window_size_px=50)
    print(f"  Z-score range: [{np.nanmin(ndvi_zscore):.2f}, {np.nanmax(ndvi_zscore):.2f}]")

    # Save rasters
    print("\nSaving rasters...")
    save_geotiff(ndvi_dry, dry_composite, NDVI_DRY_TIF)
    if ndvi_wet is not None:
        save_geotiff(ndvi_wet, dry_composite, NDVI_WET_TIF)
    save_geotiff(ndvi_zscore, dry_composite, NDVI_ZSCORE_TIF)

    # Extract per-cenote features
    print("\nExtracting features at cenote locations...")
    results = extract_features_at_cenotes(
        cenotes, ndvi_dry, ndvi_wet, ndvi_zscore, ndmi_dry, dry_composite
    )

    save_features(results, OUTPUT)

    # Summary
    if results:
        vals = list(results.values())
        ndvi_vals = [v["ndvi_dry"] for v in vals if "ndvi_dry" in v]
        zscore_vals = [v["ndvi_zscore"] for v in vals if "ndvi_zscore" in v]
        print(f"\n── Summary ──")
        print(f"  Cenotes with NDVI data: {len(ndvi_vals)}/{len(cenotes)}")
        if ndvi_vals:
            print(f"  Dry NDVI at cenotes: mean={np.mean(ndvi_vals):.3f}, std={np.std(ndvi_vals):.3f}")
        if zscore_vals:
            high_z = sum(1 for z in zscore_vals if abs(z) > 2)
            print(f"  High anomaly (|z|>2): {high_z} cenotes")


if __name__ == "__main__":
    main()
