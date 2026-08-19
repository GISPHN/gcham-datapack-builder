# Changelog

## 1.1.3 - 2026-08-19

### Added
- Unified dataset selection for population, facilities, transport, roads, disaster, and basemaps in a single workflow.
- `G-CHAMデータパックのデータ` preset that selects the standard data-pack contents while leaving large N13 road data off by default.
- `特定のデータを追加` workflow that clears all selections so users can choose only the required datasets.
- Per-layer selection inside facility, transport, disaster, and basemap groups.
- Population data can now be selected and added independently from the other data groups.
- Municipality-scoped incremental output for selected municipalities, including municipality-coded FlatGeobuf filenames to avoid overwriting prefecture-wide outputs.
- Selection-time temporary caching for N03/e-Stat metadata so municipality/data selection does not require choosing an output folder first.

### Changed
- The plugin now determines the processing path automatically from the selected datasets instead of requiring a separate “supplemental layers only” mode.
- N13 road processing now uses bounding-box filtering, prepared geometry checks, reduced clipping work, progress logging, cancellation checks, and GUI event updates for improved performance.
- The dialog is vertically resizable, keeps the action buttons visible on smaller displays, and provides a larger but flexible processing log area.
- Supplemental selection defaults to the standard G-CHAM data-pack contents; a one-click clear-all control is available for selective additions.

### Fixed
- `自治体を選択...` and `追加データを選択...` no longer open the output-folder chooser.
- Selected municipality scope is respected when adding data to an existing data pack.
- Municipality selections, output-folder text, and dataset selections remain available after completion, cancellation, or errors.
- Internal control results are excluded from municipality filename conversion.

## 1.1.2 - 2026-08-19

### Fixed
- Optimized nationwide N02 railway filtering to avoid long stalls in prefectures such as Shizuoka and Ehime.
- Added a dissolved prefecture boundary layer with a black outline.
- Added dissolved ordinance-designated city boundary layers while retaining individual ward boundaries.
- Fixed Japanese mojibake in P04 medical-facility attributes and labels by preferring GML input and using an explicit CP932 fallback for Shapefiles.
- Added wall-clock elapsed-time display in `mm:ss` and improved GUI responsiveness during long synchronous processing steps.

## 1.1.1 - 2026-08-18

### Fixed
- Resolved all 12 Qt6 compatibility findings reported for v1.1.0 by the QGIS Plugin Repository checker.
- Fixed static-analysis undefined-name findings in supplemental data discovery (`urlparse`).
- Release packaging now excludes `__pycache__`, `.pyc`, and other generated cache files.
- Removed unused imports and exception-handler patterns that could generate avoidable quality/security-scan findings.
- Removed legacy direct enum aliases for `QgsFeatureSink.FastInsert`, `Qt.Checked`, `Qt.Unchecked`, `Qt.ItemIsUserCheckable`, `Qt.ItemIsEnabled`, and `QDialog.Accepted`.
- Replaced the direct legacy `exec_()` call with `exec()` and a dynamic QGIS 3/PyQt5 fallback.
- No functional/data-processing behavior from v1.1.0 was changed.

## 1.1.0 - 2026-08-18

### Added
- Optional `施設` group with National Land Numerical Information P28 (2022), P05 (2022), P04 (2020), A27 (2023), and P29 (2023).
- Optional `交通` group with P11 bus stops (2022), N07 bus routes (2022), and N02 railway stations/routes (2025).
- Separately selectable N13 roads (2024), disabled by default because source downloads can be large.
- Automated N13 code-to-Japanese fields for road type, road classification, road state, width class, and toll class.
- Width-class road styling and prefecture-boundary geometry clipping.
- Optional `災害` group with GSI designated emergency evacuation sites and designated shelters.
- J-SHIS 2024 probabilistic seismic hazard (`T30_P03_SI`, all earthquakes, maximum case), with a 70% opacity WMS fallback when local vector conversion is unavailable.
- Optional `背景地図` group with OpenStreetMap Standard, GSI seamless aerial imagery, and GSI hillshade XYZ tiles.
- Facility, transport, and disaster label definitions are retained but hidden by default to reduce map clutter.

### Changed
- `250mメッシュ人口` is positioned below the `災害` group in the layer tree.
- Supplemental vector outputs use the selected prefecture's JGD2011 Japan Plane Rectangular Coordinate System and FlatGeobuf where applicable.
- GSI shelter-data discovery now follows public-page JavaScript/JSON assets before falling back to official GeoJSON tiles.
- GSI GeoJSON fallback queries only Z10 tiles intersecting the selected prefecture; sparse-tile 404 responses are treated as empty tiles and summarized rather than logged individually.
- Road downloads remain source Shapefiles but are merged, transformed, clipped, and written as FlatGeobuf for QGIS use.
- Background-map XYZ layer creation was updated for QGIS 4.x compatibility.

## 1.0.1 - 2026-08-17

Security hardening release required by the QGIS Official Plugin Repository scanner.

### Security
- Replaced dynamically constructed suppression-validation and base-row-count `SELECT` statements with fixed SQL statements.
- Retained dynamic SQL only where SQLite requires dynamic identifiers; such identifiers are fixed/escaped and documented.
- Removed silent `try/except/pass` paths flagged by Bandit.
- Added Bandit security analysis to GitHub Actions.

## 1.0.0 - 2026-08-17

First stable public release.

### Added
- Automatic download of six 2020 Population Census 250 m JGD2011 mesh-statistics tables from e-Stat.
- G-CHAM data-pack preset based on 128 source attributes, with optional additional Census fields.
- Suppression/aggregation processing using `HTKSYORI`, `HTKSAKI`, and `GASSAN`.
- Derived age-group percentages for ages 0–14, 15–64, and 65+, calculated after suppression merging and rounded to one decimal place using half-up rounding.
- Automatic download/dissolve of 2026 N03 administrative boundaries.
- Municipality assignment by intact mesh-center location, with deterministic boundary fallback rules.
- Municipality and prefecture FlatGeobuf outputs using JGD2011 Japan Plane Rectangular Coordinate Systems.
- Automatic administrative-boundary and population styling.
- Download caching, overwrite/skip handling, progress reporting, and cancellation.

## 0.1.1 - 2026-08-17
- Fixed municipality FlatGeobuf finalization before re-opening the file in QGIS.
- Added projected CRS output and automatic styles.

## 0.1.0 - 2026-08-17
- Initial development build.
