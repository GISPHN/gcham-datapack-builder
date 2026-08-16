# G-CHAM Data Pack Builder 1.0.0

First stable public release.

G-CHAM Data Pack Builder automates the creation of municipal G-CHAM FlatGeobuf data packs from Japanese government open data in QGIS.

## Highlights

- Downloads six 2020 Population Census 250 m JGD2011 tables from e-Stat.
- Applies the 128-field G-CHAM preset and supports optional additional Census fields.
- Joins the six tables by `KEY_CODE` and preserves Japanese statistical field labels.
- Validates and processes e-Stat suppressed/aggregated meshes.
- Calculates age-group percentages after suppression processing, rounded to one decimal place.
- Downloads and dissolves 2026 N03 administrative boundaries.
- Assigns intact 250 m meshes to municipalities by mesh-center location.
- Outputs municipality and prefecture-wide FlatGeobuf files with ASCII-only file names.
- Uses JGD2011 Japan Plane Rectangular Coordinate System output.
- Adds styled Japanese-named layers to QGIS automatically.
- Supports all-municipality and selected-municipality workflows.
- Reuses locally cached downloads.

See `README.md`, `CHANGELOG.md`, and `DATA_SOURCES.md` for details.
