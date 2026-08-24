# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Ryo Horiike / GISPHN

from __future__ import annotations

import gc
from pathlib import Path

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsFeatureSink,
    QgsVectorLayer,
    QgsWkbTypes,
)

from . import qgis_io
from . import supplemental
from . import v113_layer_selection
from .constants import GEOGRAPHIC_CRS_EPSG

_APPLIED = False


def _enum_member(owner, nested_name: str, member_name: str):
    nested = getattr(owner, nested_name, None)
    if nested is not None and hasattr(nested, member_name):
        return getattr(nested, member_name)
    return getattr(owner, member_name)


def _geometry_type(wkb_type):
    return QgsWkbTypes.geometryType(wkb_type)


def _write_merged_vectors_resilient(
    sources: list[Path],
    out_path: Path,
    target_epsg: int,
    pref_geometry=None,
    extra_maps=None,
    clip_to_pref: bool = False,
) -> Path:
    """Write merged vectors while ignoring boundary-touch intersections of the wrong dimension."""
    if not sources:
        raise RuntimeError("入力ベクタがありません。")

    first = QgsVectorLayer(str(sources[0]), "source", "ogr")
    if not first.isValid():
        raise RuntimeError(f"入力データを開けません: {sources[0]}")

    extras = tuple((extra_maps or {}).keys())
    base_names = [field.name() for field in first.fields()]
    out_fields = supplemental._copy_fields(first.fields(), extras)
    writer_wkb = first.wkbType()
    if clip_to_pref:
        writer_wkb = QgsWkbTypes.multiType(writer_wkb)
    expected_geometry_type = _geometry_type(writer_wkb)

    writer = supplemental._create_writer(
        out_path, out_fields, writer_wkb, target_epsg
    )
    written = 0
    failed = False
    try:
        for source_path in sources:
            layer = QgsVectorLayer(str(source_path), "source", "ogr")
            if not layer.isValid():
                raise RuntimeError(f"入力データを開けません: {source_path}")
            to_target = supplemental._transform(layer.crs(), target_epsg)
            to_geo = (
                supplemental._geo_transform(layer.crs())
                if pref_geometry is not None
                else None
            )
            field_names = [field.name() for field in layer.fields()]

            for src in layer.getFeatures():
                if not src.hasGeometry() or src.geometry().isEmpty():
                    continue

                check_geom = None
                if pref_geometry is not None:
                    check_geom = supplemental._copy_geom(src.geometry(), to_geo)
                    if not check_geom.intersects(pref_geometry):
                        continue

                feature = QgsFeature(out_fields)
                if clip_to_pref and check_geom is not None:
                    geom = check_geom.intersection(pref_geometry)
                    if geom.isEmpty():
                        continue

                    # Polygon/line datasets can merely touch the selected municipality
                    # boundary. In that case intersection() may return a lower-dimensional
                    # geometry (e.g. polygon -> line), which cannot be written to the
                    # source-typed FlatGeobuf. Treat that as no matching feature.
                    if _geometry_type(geom.wkbType()) != expected_geometry_type:
                        continue

                    geo_crs = QgsCoordinateReferenceSystem.fromEpsgId(
                        GEOGRAPHIC_CRS_EPSG
                    )
                    geo_to_target = supplemental._transform(geo_crs, target_epsg)
                    if geo_to_target is not None:
                        geom.transform(geo_to_target)
                    if not geom.isMultipart():
                        geom.convertToMultiType()
                else:
                    geom = supplemental._copy_geom(src.geometry(), to_target)

                feature.setGeometry(geom)
                attrs = [
                    src[name] if name in field_names else None
                    for name in base_names
                ]
                for _new_name, (source_name, mapping) in (extra_maps or {}).items():
                    raw = src[source_name] if source_name in field_names else None
                    try:
                        key = (
                            int(raw)
                            if raw is not None and str(raw).strip()
                            else None
                        )
                    except (TypeError, ValueError):
                        key = None
                    attrs.append(mapping.get(key))
                feature.setAttributes(attrs)

                if not writer.addFeature(
                    feature,
                    _enum_member(QgsFeatureSink, "Flag", "FastInsert"),
                ):
                    raise RuntimeError(
                        f"FGB書き込みに失敗しました: {out_path}"
                    )
                written += 1
    except Exception:
        failed = True
        raise
    finally:
        del writer
        gc.collect()
        if failed:
            qgis_io.remove_existing_layer_for_path(out_path)
            out_path.unlink(missing_ok=True)

    if written == 0:
        qgis_io.remove_existing_layer_for_path(out_path)
        out_path.unlink(missing_ok=True)
        raise RuntimeError(f"対象地物が0件でした: {out_path.name}")
    return out_path


def _patch_vector_writer() -> None:
    if getattr(supplemental._write_merged_vectors, "_gcham_v114", False):
        return
    _write_merged_vectors_resilient._gcham_v114 = True
    supplemental._write_merged_vectors = _write_merged_vectors_resilient


def _patch_facility_independence() -> None:
    original = supplemental.SupplementalBuilder.build_facilities
    if getattr(original, "_gcham_v114", False):
        return

    def build_facilities(self):
        selection = v113_layer_selection._CURRENT_SELECTION
        if selection is None:
            wanted_datasets = {
                spec[0] for spec in supplemental.FACILITY_SPECS
            }
        else:
            wanted_datasets = {
                dataset
                for key, dataset in v113_layer_selection.FACILITY_KEYS.items()
                if key in selection
            }

        if not wanted_datasets:
            return []

        all_specs = tuple(supplemental.FACILITY_SPECS)
        results = []
        try:
            for spec in all_specs:
                dataset, _yy, _year, _filename_tpl, title, out_tpl, _style = spec
                if dataset not in wanted_datasets:
                    continue
                self.check_cancelled()
                supplemental.FACILITY_SPECS = (spec,)
                try:
                    partial = original(self)
                    results.extend(partial)
                except qgis_io.CancelledError:
                    raise
                except Exception as exc:
                    out = self.data_dir / out_tpl.format(pref=self.pref_code)
                    qgis_io.remove_existing_layer_for_path(out)
                    out.unlink(missing_ok=True)
                    self.log(
                        f"追加データ警告 [施設/{title}]: {exc} "
                        "このレイヤをスキップして他の施設データを続行します。"
                    )
        finally:
            supplemental.FACILITY_SPECS = all_specs
        return results

    build_facilities._gcham_v114 = True
    supplemental.SupplementalBuilder.build_facilities = build_facilities


def apply_v114_facility_resilience() -> None:
    global _APPLIED
    if _APPLIED:
        return
    _patch_vector_writer()
    _patch_facility_independence()
    _APPLIED = True
