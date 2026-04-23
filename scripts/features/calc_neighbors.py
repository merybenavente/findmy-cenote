"""Calculate nearest-neighbor distances and density stats for cenotes."""

import csv, json, math, statistics
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
INPUT = DATA_DIR / "cenote_terrain_analysis.csv"
OUTPUT = DATA_DIR / "cenote_neighbors.json"

R_EARTH = 6371.0  # km


def haversine(lat1, lon1, lat2, lon2):
    """Distance in km between two lat/lon points."""
    φ1, φ2 = math.radians(lat1), math.radians(lat2)
    dφ = math.radians(lat2 - lat1)
    dλ = math.radians(lon2 - lon1)
    a = math.sin(dφ / 2) ** 2 + math.cos(φ1) * math.cos(φ2) * math.sin(dλ / 2) ** 2
    return 2 * R_EARTH * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def bearing(lat1, lon1, lat2, lon2):
    """Initial bearing in degrees [0, 360) from point 1 to point 2."""
    φ1, φ2 = math.radians(lat1), math.radians(lat2)
    dλ = math.radians(lon2 - lon1)
    x = math.sin(dλ) * math.cos(φ2)
    y = math.cos(φ1) * math.sin(φ2) - math.sin(φ1) * math.cos(φ2) * math.cos(dλ)
    θ = math.atan2(x, y)
    return (math.degrees(θ) + 360) % 360


# ── Load data ────────────────────────────────────────────────────────────
rows = []
with open(INPUT, newline="") as f:
    for r in csv.DictReader(f):
        rows.append(
            {
                "name": r["name"],
                "lat": float(r["lat"]),
                "lon": float(r["lon"]),
                "municipio": r["municipio"],
            }
        )

n = len(rows)
print(f"Loaded {n} cenotes")

# ── Pairwise distances (n is small, brute-force is fine) ─────────────────
results = {}
nn_dists = []  # for summary stats
muni_counts: dict[str, int] = {}

for i, c in enumerate(rows):
    muni_counts[c["municipio"]] = muni_counts.get(c["municipio"], 0) + 1

    dists = []
    for j, o in enumerate(rows):
        if i == j:
            continue
        d = haversine(c["lat"], c["lon"], o["lat"], o["lon"])
        dists.append((d, j))
    dists.sort()

    nn_dist, nn_idx = dists[0]
    nn3_dist = dists[2][0] if len(dists) >= 3 else None

    n_1km = sum(1 for d, _ in dists if d <= 1.0)
    n_3km = sum(1 for d, _ in dists if d <= 3.0)
    n_5km = sum(1 for d, _ in dists if d <= 5.0)

    nn_bear = bearing(c["lat"], c["lon"], rows[nn_idx]["lat"], rows[nn_idx]["lon"])

    key = f"{c['name']}|{c['lat']}|{c['lon']}"
    results[key] = {
        "nn_dist": round(nn_dist, 4),
        "nn3_dist": round(nn3_dist, 4) if nn3_dist is not None else None,
        "n_1km": n_1km,
        "n_3km": n_3km,
        "n_5km": n_5km,
        "nn_bearing": round(nn_bear, 1),
    }
    nn_dists.append(nn_dist)

# ── Save JSON ────────────────────────────────────────────────────────────
with open(OUTPUT, "w") as f:
    json.dump(results, f, indent=2, ensure_ascii=False)
print(f"Saved {len(results)} entries → {OUTPUT}")

# ── Summary stats ────────────────────────────────────────────────────────
print("\n── Summary Statistics ──────────────────────────────")
print(f"Mean nearest-neighbor distance:   {statistics.mean(nn_dists):.3f} km")
print(f"Median nearest-neighbor distance: {statistics.median(nn_dists):.3f} km")
print(f"Min nearest-neighbor distance:    {min(nn_dists):.4f} km")
print(f"Max nearest-neighbor distance:    {max(nn_dists):.3f} km")
print(f"Std dev:                          {statistics.stdev(nn_dists):.3f} km")

# Density by municipality: cenotes per municipality
muni_sorted = sorted(muni_counts.items(), key=lambda x: x[1], reverse=True)
print(f"\n── Municipality Density (cenote count) ─────────────")
print("Highest density:")
for m, cnt in muni_sorted[:5]:
    print(f"  {m}: {cnt} cenotes")
print("Lowest density:")
for m, cnt in muni_sorted[-5:]:
    print(f"  {m}: {cnt} cenotes")
