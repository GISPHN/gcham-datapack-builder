# SPDX-License-Identifier: GPL-2.0-or-later
"""Produce a single prefecture-wide N03 municipality layer and set visibility."""
from __future__ import annotations
import gc
from pathlib import Path
from qgis.core import QgsFeature, QgsProject, QgsVectorLayer
from . import processor as processor_module, qgis_io
from .constants import plane_rectangular_epsg

_APPLIED = False

def _write_combined(path, municipalities, fields, epsg):
    path.parent.mkdir(parents=True, exist_ok=True)
    qgis_io.remove_existing_layer_for_path(path)
    path.unlink(missing_ok=True)
    writer = qgis_io.create_fgb_writer(path, fields, epsg)
    transformer = qgis_io.geometry_transformer(epsg)
    count = 0
    failed = False
    try:
        for muni in municipalities:
            feature = QgsFeature(fields)
            feature.setGeometry(qgis_io.transform_geometry(muni.geometry, transformer))
            feature.setAttributes([muni.attributes.get(field.name()) for field in fields])
            if not writer.addFeature(feature):
                raise RuntimeError('全市区町村行政区域FGBの書き込みに失敗: ' + str(path))
            count += 1
        if hasattr(writer, 'flushBuffer'):
            writer.flushBuffer()
    except Exception:
        failed = True
        raise
    finally:
        # Release the writer before removing a partially written FGB.
        writer = None
        gc.collect()
        if failed:
            path.unlink(missing_ok=True)
    if count != len(municipalities):
        raise RuntimeError('全市区町村行政区域の地物数が一致しません')
    return count

def _add_combined(path, pref_name):
    project = QgsProject.instance()
    root = project.layerTreeRoot()
    group = root.findGroup('行政区域') or root.addGroup('行政区域')
    qgis_io.remove_existing_layer_for_path(path)
    layer = QgsVectorLayer(str(path), f'{pref_name}_全市区町村行政区域_国土数値情報', 'ogr')
    if not layer.isValid():
        raise RuntimeError('統合行政区域FGBを開けません: ' + str(path))
    qgis_io.style_admin_layer(layer)
    # Use precisely the same labels as the individual municipality layers.
    layer.setLabelsEnabled(True)
    project.addMapLayer(layer, False)
    group.insertLayer(1, layer)
    return layer

def _visibility(group, combined_id, individual_paths):
    individual_names = {str(Path(p).resolve()).casefold() for p in individual_paths}
    for node in group.findLayers():
        layer = node.layer()
        if layer is None:
            continue
        if layer.id() == combined_id:
            node.setItemVisibilityChecked(True)
        else:
            try:
                source = str(Path(layer.source().split('|', 1)[0]).resolve()).casefold()
            except (OSError, ValueError):
                continue
            if source in individual_names:
                node.setItemVisibilityChecked(False)

def apply_v114_combined_admin():
    global _APPLIED
    if _APPLIED:
        return
    old_build = processor_module.DataPackProcessor.build
    def build(self, options, confirm_existing=None):
        result = old_build(self, options, confirm_existing)
        # Independently reload the full N03 boundary set, not the selected municipality subset.
        n03_path = self.ensure_n03(options.pref_code, options.output_dir, options.reuse_downloads)
        all_municipalities, n03_fields = qgis_io.load_and_dissolve_n03(n03_path)
        path = options.output_dir / 'admin' / f'n03_{str(options.pref_code).zfill(2)}_all_municipalities.fgb'
        count = _write_combined(path, all_municipalities, n03_fields, plane_rectangular_epsg(options.pref_code))
        layer = _add_combined(path, options.pref_name)
        group = QgsProject.instance().layerTreeRoot().findGroup('行政区域')
        # Ensure prefecture border is first, combined municipality layer second.
        prefecture_path = options.output_dir / 'admin' / f'n03_{str(options.pref_code).zfill(2)}_pref_admin.fgb'
        pref_nodes = [node for node in group.findLayers() if node.layer() and Path(node.layer().source().split('|',1)[0]).resolve() == prefecture_path.resolve()]
        if pref_nodes and group.children().index(pref_nodes[0]) != 0:
            # Move layer-tree node by cloning it, avoiding layer ownership changes.
            clone = pref_nodes[0].clone()
            group.insertChildNode(0, clone)
            group.removeChildNode(pref_nodes[0])
        combined_node = group.findLayer(layer.id())
        if combined_node and group.children().index(combined_node) != 1:
            clone = combined_node.clone()
            group.insertChildNode(1, clone)
            group.removeChildNode(combined_node)
        _visibility(group, layer.id(), result.get('admin_paths', {}).values())
        self.log(f'全市区町村行政区域を追加: {options.pref_name} / {count}地物 / {path.name}')
        result['all_municipalities_admin'] = path
        return result
    processor_module.DataPackProcessor.build = build
    _APPLIED = True
