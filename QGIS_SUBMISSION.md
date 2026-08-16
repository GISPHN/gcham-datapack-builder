# QGIS Official Plugin Repository submission checklist

Package name: `gcham_datapack_builder`  
Plugin name: `G-CHAM Data Pack Builder`  
Version: `1.0.0`  
Author: `GISPHN (Ryo Horiike)`  
Email: `ryo.horiike@naramed-u.ac.jp`

## Before upload

- [x] One ASCII-only top-level plugin folder: `gcham_datapack_builder`
- [x] `metadata.txt` included and populated
- [x] `__init__.py` included
- [x] `LICENSE` included with no extension
- [x] Public repository URL specified in metadata
- [x] Public issue tracker URL specified in metadata
- [x] Homepage URL specified in metadata
- [x] Custom icon included
- [x] `experimental=False`
- [x] Unique version `1.0.0`
- [x] Minimal documentation included
- [x] Source data are not bundled in the plugin package
- [x] Automated package structure validation passes

## Repository URLs expected by metadata

- Repository: https://github.com/GISPHN/gcham-datapack-builder
- Tracker: https://github.com/GISPHN/gcham-datapack-builder/issues
- Homepage: https://github.com/GISPHN/gcham-datapack-builder#readme

The public GitHub repository must exist before submitting the plugin to the QGIS repository, otherwise the metadata links will fail review.

## QGIS upload

Upload `GCHAM_Data_Pack_Builder_1.0.0.zip` using the official QGIS plugin repository account associated with your OSGeo ID.

After upload, wait for the automated security scan. If it passes, the version proceeds to manual approval unless the uploader has trusted fast-track permission and explicitly opts into automatic publication after the scan.
