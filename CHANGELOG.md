# Changelog

All notable changes to G-CHAM Data Pack Builder are documented in this file.

The project follows semantic versioning where practical.

## 1.0.0 - 2026-08-17

First public release prepared for the QGIS Official Plugin Repository.

### Added

- Automatic download of six 2020 Population Census 250 m mesh-statistics tables from e-Stat.
- Automatic download of 2026 National Land Numerical Information N03 administrative boundaries.
- G-CHAM preset containing 128 source Census attributes.
- Optional selection of additional Census attributes.
- Two-row e-Stat header handling with Japanese output field names.
- `KEY_CODE` join across the six Census tables.
- Suppressed/aggregated mesh validation and processing using `HTKSYORI`, `HTKSAKI`, and `GASSAN`.
- Derived age-group percentages for ages 0–14, 15–64, and 65+, rounded to one decimal place with half-up rounding.
- N03 dissolve by `N03_007` and municipality naming using `N03_005` or `N03_004`.
- Municipality assignment based on 250 m mesh center points.
- All-municipality and selected-municipality output modes.
- Municipality-level and prefecture-wide FlatGeobuf export.
- ASCII-only generated paths and Japanese QGIS layer names.
- JGD2011 Japan Plane Rectangular Coordinate System output selected by prefecture.
- Automatic QGIS layer-tree grouping.
- Default administrative-boundary styling and municipality labels.
- Municipality-specific Jenks classification for population layers.
- Source archive caching and reuse.
- Overwrite/skip handling for existing outputs.
- Progress, log, and cancel support.

### Compatibility

- Primary target: QGIS 4.x.
- Compatibility code retained for QGIS 3.44 LTR where practical.
