# Data Sources & Attribution

This dataset aggregates multiple open data sources to create an enriched catalog of cenotes in the Yucatan Peninsula. Each column in the unified dataset traces back to a specific source listed below.

## License

This dataset is published under the [Open Database License (ODbL) v1.0](https://opendatacommons.org/licenses/odbl/1-0/), as required by the inclusion of OpenStreetMap and WorldPop data.

You are free to share, modify, and use this dataset for any purpose, provided you:
1. Attribute the sources listed below
2. Share any derived databases under the same ODbL license

---

## 1. Cenote Locations & Base Attributes

**Columns:** `name`, `alt_names`, `municipio`, `state`, `topo`, `lat`, `lon`, `depth`, `length`

**Source:** "Yuc_caves_Projected" Feature Service by BWaldo8 (ArcGIS, 2020)
- URL: https://services1.arcgis.com/AXaYBvnJsB5Q7sDF/arcgis/rest/services/Yuc_caves_Projected/FeatureServer/0
- 1,367 cenote locations with coordinates, names, municipalities, and depth/length where available

2 additional cenotes from **OpenStreetMap** contributors.
- License: ODbL v1.0
- https://www.openstreetmap.org/copyright

## 2. Terrain & Depression Metrics

**Columns:** `elevation`, `dem_resolution`, `depression_50m`, `depression_100m`, `depression_250m`, `depression_500m`, `mean_slope`, `max_slope`, `roughness`, `elev_percentile`, `min_elev_250m`, `max_elev_250m`, `ring_mean_250m`, `has_terrain`

**Source:** Fuente: INEGI, Continuo de Elevaciones Mexicano (CEM 3.0/4.0), 5m and 15m resolution.
- https://www.inegi.org.mx/app/geo2/elevacionesmex/
- Used under INEGI's Terminos de Libre Uso. All terrain analysis and derived metrics were computed independently and do not represent official INEGI products.

## 3. Hydrological Features

**Columns:** `sink_depth`, `sink_depth_mean`, `in_depression`, `depression_area`, `flow_accum`, `flow_accum_max`

**Source:** Derived from INEGI CEM (see above) using WhiteboxTools.
- Sink depth, flow accumulation, and depression detection computed independently; not an official INEGI product.

## 4. Geological Age & Lithology

**Columns:** `lithology`, `geology_age`, `age_ma_top`, `age_ma_bottom`

**Source:** Macrostrat geological database.
- Peters, S.E. et al., 2018
- https://macrostrat.org

## 5. Lineament / Fracture Proximity

**Columns:** `lineament_dist_min`, `lineament_count_500m`, `lineament_azimuth`, `on_lineament`

**Source:** Extracted from INEGI CEM 5m (see section 2) using multi-azimuth hillshade edge detection and probabilistic Hough transform. Not an official INEGI product.

## 6. Vegetation (NDVI)

**Columns:** `ndvi_dry`, `ndvi_diff`, `ndvi_zscore`, `ndvi_zscore_max`

**Source:** Copernicus Sentinel-2 L2A imagery (2024-2025) accessed via Microsoft Planetary Computer.
- Contains modified Copernicus Sentinel data
- https://planetarycomputer.microsoft.com

## 7. Canopy Height

**Columns:** `canopy_height`, `canopy_height_min`, `canopy_height_std`, `canopy_gap_fraction`

**Source:** Meta and World Resources Institute (WRI), High Resolution Canopy Height Maps (2024), 1m resolution. Source imagery (c) 2016 Maxar.
- License: CC BY 4.0
- https://registry.opendata.aws/dataforgood-fb-forests/

## 8. Land Surface Temperature

**Columns:** `lst_anomaly`

**Source:** USGS Landsat 8/9 Collection 2 Level 2 (2023-2025) accessed via Microsoft Planetary Computer.
- https://planetarycomputer.microsoft.com

## 9. Roads & Coast Distance

**Columns:** `road_distance_km`, `road_type`, `coast_distance_km`

**Source:** Road network from OpenStreetMap contributors (ODbL).
- https://www.openstreetmap.org/copyright

Coast distance calculated from natural coastline geometry.

## 10. Spatial Neighbor Metrics

**Columns:** `nearest_neighbor_km`, `nearest_bearing`, `third_nearest_km`, `neighbors_1km`, `neighbors_3km`, `neighbors_5km`

**Source:** Computed from cenote coordinates.
