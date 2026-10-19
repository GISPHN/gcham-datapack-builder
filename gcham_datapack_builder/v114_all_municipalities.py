# SPDX-License-Identifier: GPL-2.0-or-later
"""Prefecture-wide undissolved municipality boundary layer."""
from __future__ import annotations

import gc
from pathlib import Path

from qgis.core import QgsFeature, QgsVectorLayer, QgsProject

from . import processor as processor_module
from . import qgis_io
from . import v112_patches
from .constants import plane_rectangular_epsg

_APPLIED = False


def _build_all_municipality_layer(processor, options):
    vector = processor.ensure_n03(
        options.pref_code, options.output_dir, options.reuse_downloads
    )
    municipalities, fields = qgis_io.load_and_dissolve_n03(vector)
    target_epsg = plane_rectangular_epsg(options.pref_code)
    pref = str(options.pref_code).zfill(2)
    path = options.output_dir / "admin" / f"n03_{pref}_all_municipalities.fgb"
    path.parent.mkdir(parents=True, exist_ok=True)

    # Preserve individual municipality/ward geometries, not a prefecture dissolve.
    qgis_io.remove_existing_layer_for_path(path)
    path.unlink(missing_ok=True)
    writer = qgis_io.create_fgb_writer(path, fields, target_epsg)
    transform = qgis_io.geometry_transformer(target_epsg)
    count = 0
    failed = False
    try:
        for municipality in municipalities:
            processor.check_cancelled()
            feature = QgsFeature(fields)
            feature.setGeometry(
                qgis_io.transform_geometry(municipality.geometry, transform)
            )
            feature.setAttributes([
                municipality.attributes.get(field.name()) for field in fields
            ])
            if not writer.addFeature(feature):
                raise RuntimeError(
                    f"全市区町村行政区域FGB書き込み失敗: {municipality.code}"
                )
            count += 1
        if hasattr(writer, "flushBuffer"):
            writer.flushBuffer()
    except Exception:
        failed = True
        raise
    finally:
        del writer
        gc.collect()
        if failed:
            path.unlink(missing_ok=True)

    if count != len(municipalities):
        raise RuntimeError("全市区町村行政区域の地物数が一致しません。")

    display = f"{options.pref_name}_全市区町村行政区域_国土数値情報"
    layer = QgsVectorLayer(str(path), display, "ogr")
    if not layer.isValid() or layer.featureCount() != count:
        raise RuntimeError("統合行政区域FGBの検証に失敗しました。")
    qgis_io.style_admin_layer(layer)
    # Boundary outlines only. Avoid labels duplicating individual layers.
    layer.setLabelsEnabled(False)

    project = QgsProject.instance()
    root = project.layerTreeRoot()
    group = root.findGroup("行政区域") or root.addGroup("行政区域")
    project.addMapLayer(layer, False)

    # Ensure top two positions: prefecture outer boundary, then all municipalities.
    prefecture_name = f"{options.pref_name}_行政区域_国土数値情報"
    prefecture_node = next(
        (node for node in group.findLayers()
         if node.layer() and node.layer().name() == prefecture_name),
        None,
    )
    group.insertLayer(1 if prefecture_node else 0, layer)

    # Existing individual municipality layers remain available but start hidden.
    for node in group.findLayers():
        other = node.layer()
        if other is None or other.id() == layer.id():
            continue
        other_path = Path(other.source().split("|", 1)[0]).name.lower()
        # Only files corresponding to individual N03 municipality/ward codes.
        if other_path.startswith("n03_") and other_path.endswith("_admin.fgb"):
            code = other_path[len("n03_"):-len("_admin.fgb")]
            if len(code) == 5 and code.isdigit():
                node.setItemVisibilityChecked(False)
    processor.log(f"全市区町村行政区域を追加: {count}地物 / {path.name}")
    return path


def apply_v114_all_municipalities():
    global _APPLIED
    if _APPLIED:
        return
    original = processor_module.DataPackProcessor.build
    if getattr(original, "_gcham_v114_all_municipalities", False):
        return

    def build(self, options, confirm_existing=None):
        result = original(self, options, confirm_existing)
        path = _build_all_municipality_layer(self, options)
        result["all_municipalities_admin"] = path
        return result

    build._gcham_v114_all_municipalities = True
    processor_module.DataPackProcessor.build = build
    _APPLIED = True
