# G-CHAM Data Pack Builder 1.1.1

## Release purpose

This release is the corrected QGIS Plugin Repository submission package for the 1.1.x feature update.

## Fixes

- Fixed all previously reported QGIS Qt6 compatibility checker findings.
- Fixed the `urlparse` undefined-name (`F821`) issue in `supplemental.py`.
- Removed unused imports detected during release linting.
- Removed avoidable `try/except/continue` patterns that can trigger Bandit quality warnings.
- Rebuilt the package from a clean staging directory.
- Explicitly excludes `__pycache__`, `.pyc`, `.pyo`, compiled libraries, hidden development directories, and executable files from the release ZIP.
- Package metadata remains version `1.1.1`, stable (`experimental=False`), compatible with QGIS 3.44 through QGIS 4.x (`qgisMaximumVersion=4.99`).

## Validation

The final ZIP was unpacked and revalidated after packaging.

- ZIP integrity: PASS
- Required QGIS files: PASS
- No `__pycache__` / compiled Python files: PASS
- Python in-memory syntax compilation: PASS
- Undefined-name check (`F821` equivalent): 0 findings
- Unused-import check (`F401` equivalent): 0 findings
- Previously reported Qt6 compatibility patterns: 0 findings
- Core regression tests: 4/4 PASS
- Total local release checks: 31/31 PASS

The QGIS Plugin Repository server-side validation for this package also passed on 2026-08-18.
