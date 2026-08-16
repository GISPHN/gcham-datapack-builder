# G-CHAM Data Pack Builder 1.0.1

This release resolves the blocking Bandit findings reported by the QGIS Official Plugin Repository for version 1.0.0.

- Fixed B608 SQL-injection warnings by using fixed SQL where possible and strictly quoted/whitelisted identifiers where dynamic identifiers are required.
- Removed B110 silent try/except/pass patterns.
- Added Bandit to GitHub Actions.
- No intended change to Census integration, suppression handling, municipality allocation, FlatGeobuf output, CRS conversion, or QGIS styling.
