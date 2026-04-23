<p align="center">
  <img src="design/banner.png" alt="FindMy Cenote — Ring of Cenotes" width="100%">
</p>

# Find My Cenote

An open data project to map and enrich every cenote in the Yucatan Peninsula. The **Cenote Atlas** dataset aggregates 1,369 cenotes from 10 open data sources with terrain analysis, vegetation indices, fracture proximity, and more.

[Live Explorer](TODO) | [Cenote Atlas on HuggingFace](TODO) | [Cenote Atlas on Zenodo](TODO)

## Why

I'm a freediver. The deepest cenote in the Yucatan suitable for depth freediving is Ucil, at just under 100m (328ft) of vertical drop. I wanted to find out if there could be another one — deeper, undiscovered — hiding somewhere in the peninsula. So I set out to explore whether AI and open data could reveal patterns in where deep cenotes form, and point to the most likely areas to find one with even better conditions.

For now, this round publishes only the aggregated dataset — I don't have a conclusive method yet for predicting depth from surface features. If you're working on something similar, or if you're open to running field expeditions on land, reach out at hi@merybenavente.me — that kind of ground-truth data could help narrow down the search areas significantly.

## What's in the dataset

Each cenote is enriched with 52 columns across 10 categories:

| Category | What it captures |
|---|---|
| **Base attributes** | Name, municipality, coordinates, known depth/length |
| **Terrain** | Elevation, depression profile at 50–500m, slope, roughness |
| **Hydrology** | Sink depth, flow accumulation, depression detection |
| **Geology** | Lithology, geological age (Eocene/Neogene/Cenozoic) |
| **Fractures** | Distance to nearest lineament, count within 500m, dominant azimuth |
| **Vegetation** | NDVI dry/wet season, seasonal anomaly z-score |
| **Canopy** | Canopy height, gap fraction (1m resolution) |
| **Thermal** | Land surface temperature anomaly |
| **Infrastructure** | Distance to nearest road, coast distance |
| **Spatial** | Nearest neighbor distance, cenote density at 1/3/5 km |

Full source attribution and licenses in [SOURCES.md](SOURCES.md).

## How it was built

The pipeline starts by downloading 5m and 15m LiDAR DEMs from INEGI, then runs nine independent feature extraction scripts — each pulling from a different remote sensing source (Sentinel-2, Landsat, Meta/WRI canopy, Macrostrat, OpenStreetMap, WorldPop) and computing per-cenote metrics within defined radii. A final build script merges all features into a single unified JSON dataset.

```
scripts/
  download/    Data acquisition from INEGI
  features/    Per-cenote metric computation (9 scripts)
  overlays/    Map tile generation for the dashboard
  build_unified_dataset.py
  grid_utils.py
```

## Design

The Yucatan Peninsula holds a ring of thousands of cenotes — natural sinkholes formed along the fracture zone of the Chicxulub asteroid impact crater, 66 million years ago. The branding plays on this: the "FindMy" naming meets the cenote ring, with scattered dots echoing the real spatial distribution of cenotes around the crater center.

Logo and visual identity designed with Claude. Explorations and source files in [`design/`](design/).


## Next steps

Surface-level remote sensing (satellite imagery, LiDAR DEMs, vegetation indices) can characterize cenote locations but cannot predict subsurface depth — cenote depth depends on fracture geometry, karst dissolution, and water table structure that are invisible from above. Possible directions for a future round:

- **Ground truth**: measure depth at cenotes currently without data (only 26 of 1,369 have known depth)
- **Gravimetry / GPR**: subsurface geophysics data could reveal void geometry where satellite data cannot
- **Expand coverage**: the current dataset only covers Yucatan state — Quintana Roo and Campeche have cenotes too

## License

This dataset is published under the [Open Database License (ODbL) v1.0](https://opendatacommons.org/licenses/odbl/1-0/), as required by the inclusion of OpenStreetMap and WorldPop data. See [SOURCES.md](SOURCES.md) for per-source attribution.
