# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Ryo Horiike / GISPHN

from __future__ import annotations

import gc
from pathlib import Path

from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import QgsFeature, QgsFeatureRequest, QgsGeometry, QgsVectorLayer, QgsWkbTypes

from . import dialog as dialog_module
from . import qgis_io
from . import supplemental
from . import v112_patches
from . import v113_layer_selection

_APPLIED = False
_ACTIVE_ALL_MUNICIPALITIES = True
_ACTIVE_MUNICIPALITY_CODES: set[str] = set()


def _point_geometry_type():
    value = getattr(QgsWkbTypes, "PointGeometry", None)
    if value is not None:
        return value
    scope = getattr(QgsWkbTypes, "GeometryType", QgsWkbTypes)
    return getattr(scope, "Point")


def _apply_layer_only_state(dialog) -> None:
    """Keep municipality controls usable while population controls are disabled."""
    if not hasattr(dialog, "layer_only_check"):
        return
    layer_only = dialog.layer_only_check.isChecked()
    available = not dialog._running

    dialog.radio_all.setEnabled(available)
    dialog.radio_selected.setEnabled(available)
    for widget in (
        dialog.preset_check,
        dialog.extra_button,
        dialog.reset_extra_button,
    ):
        widget.setEnabled(available and not layer_only)

    dialog.muni_button.setEnabled(available and dialog.radio_selected.isChecked())
    dialog.create_button.setText(
        "選択した追加レイヤを追加" if layer_only else "データパックを作成"
    )


def _scope_municipalities(all_municipalities):
    if _ACTIVE_ALL_MUNICIPALITIES:
        return list(all_municipalities)
    selected = [
        muni for muni in all_municipalities
        if muni.code in _ACTIVE_MUNICIPALITY_CODES
    ]
    missing = sorted(
        _ACTIVE_MUNICIPALITY_CODES - {muni.code for muni in selected}
    )
    if missing:
        raise RuntimeError(
            "選択した自治体コードをN03で確認できません: " + ", ".join(missing)
        )
    if not selected:
        raise RuntimeError("追加レイヤの対象自治体が選択されていません。")
    return selected


def _scope_geometry(municipalities) -> QgsGeometry:
    geometry = QgsGeometry.unaryUnion(
        [QgsGeometry(muni.geometry) for muni in municipalities]
    )
    if geometry.isNull() or geometry.isEmpty():
        raise RuntimeError("選択自治体の行政区域を作成できませんでした。")
    return geometry


def _write_p04_scoped(
    sources: list[Path],
    out_path: Path,
    target_epsg: int,
    log,
    check_cancelled,
    scope_geometry: QgsGeometry,
    encoding: str | None = None,
):
    if not sources:
        raise RuntimeError("P04医療機関の入力ベクタがありません。")
    first = v112_patches._open_source_layer(sources[0], "p04_source", encoding)
    base_names = [field.name() for field in first.fields()]
    out_fields = supplemental._copy_fields(first.fields())
    writer = supplemental._create_writer(
        out_path, out_fields, first.wkbType(), target_epsg
    )
    prepared_scope, engine = v112_patches._prepared_prefecture_geometry(scope_geometry)
    written = 0
    sample_name = None
    try:
        for source_path in sources:
            check_cancelled()
            layer = v112_patches._open_source_layer(
                source_path, "p04_source", encoding
            )
            to_target = supplemental._transform(layer.crs(), target_epsg)
            to_geo = supplemental._geo_transform(layer.crs())
            request = QgsFeatureRequest()
            try:
                request.setFilterRect(
                    v112_patches._source_filter_rect(prepared_scope, layer.crs())
                )
            except Exception as exc:
                log(f"P04医療機関: bbox事前抽出を適用できません: {exc}")
            field_names = [field.name() for field in layer.fields()]
            for source_feature in layer.getFeatures(request):
                if (
                    not source_feature.hasGeometry()
                    or source_feature.geometry().isEmpty()
                ):
                    continue
                check_geometry = supplemental._copy_geom(
                    source_feature.geometry(), to_geo
                )
                if not v112_patches._intersects_prefecture(
                    engine, prepared_scope, check_geometry
                ):
                    continue
                feature = QgsFeature(out_fields)
                feature.setGeometry(
                    supplemental._copy_geom(
                        source_feature.geometry(), to_target
                    )
                )
                feature.setAttributes(
                    [
                        source_feature[name] if name in field_names else None
                        for name in base_names
                    ]
                )
                if not writer.addFeature(feature):
                    raise RuntimeError(
                        f"FGB書き込みに失敗しました: {out_path}"
                    )
                if sample_name is None and "P04_002" in field_names:
                    value = source_feature["P04_002"]
                    if value not in (None, ""):
                        sample_name = str(value)
                written += 1
                if written % 500 == 0:
                    QCoreApplication.processEvents()
                    check_cancelled()
    finally:
        del writer
        gc.collect()

    if written == 0:
        raise RuntimeError(f"対象地物が0件でした: {out_path.name}")
    source_kind = (
        "GML優先"
        if all(path.suffix.lower() == ".gml" for path in sources)
        else "Shapefile CP932"
    )
    log(f"P04医療機関: 選択自治体内 {written:,}件 / {source_kind}")
    if sample_name:
        log(f"P04文字列確認 P04_002: {sample_name}")
    return out_path


def _patch_supplemental_only_scope() -> None:
    original_build = v113_layer_selection._build_supplemental_only
    original_loader = qgis_io.load_and_dissolve_n03
    original_write = supplemental._write_merged_vectors
    original_p04 = v112_patches._write_p04_vectors

    def build_supplemental_only(
        processor,
        output: Path,
        pref_code: str,
        pref_name: str,
        reuse: bool,
    ):
        scope_holder = {"geometry": None, "municipalities": None}

        def scoped_loader(path):
            municipalities, fields = original_loader(path)
            selected = _scope_municipalities(municipalities)
            scope_holder["municipalities"] = selected
            scope_holder["geometry"] = _scope_geometry(selected)
            if _ACTIVE_ALL_MUNICIPALITIES:
                processor.log(
                    f"追加レイヤ対象範囲: {pref_name} 全域 ({len(selected)}自治体)"
                )
            else:
                names = ", ".join(
                    f"{muni.code} {muni.name}" for muni in selected
                )
                processor.log(
                    f"追加レイヤ対象範囲: 選択自治体 {len(selected)}件 / {names}"
                )
            return selected, fields

        def scoped_write(
            sources,
            out_path,
            target_epsg,
            pref_geometry=None,
            extra_maps=None,
            clip_to_pref=False,
        ):
            if (
                not _ACTIVE_ALL_MUNICIPALITIES
                and pref_geometry is None
                and scope_holder["geometry"] is not None
            ):
                pref_geometry = scope_holder["geometry"]
                first = QgsVectorLayer(str(sources[0]), "scope_type", "ogr")
                if first.isValid():
                    geometry_type = QgsWkbTypes.geometryType(first.wkbType())
                    clip_to_pref = geometry_type != _point_geometry_type()
            return original_write(
                sources,
                out_path,
                target_epsg,
                pref_geometry,
                extra_maps,
                clip_to_pref,
            )

        def scoped_p04(
            sources,
            out_path,
            target_epsg,
            log,
            check_cancelled,
            encoding=None,
        ):
            if (
                _ACTIVE_ALL_MUNICIPALITIES
                or scope_holder["geometry"] is None
            ):
                return original_p04(
                    sources,
                    out_path,
                    target_epsg,
                    log,
                    check_cancelled,
                    encoding,
                )
            return _write_p04_scoped(
                sources,
                out_path,
                target_epsg,
                log,
                check_cancelled,
                scope_holder["geometry"],
                encoding,
            )

        qgis_io.load_and_dissolve_n03 = scoped_loader
        supplemental._write_merged_vectors = scoped_write
        v112_patches._write_p04_vectors = scoped_p04
        try:
            return original_build(
                processor, output, pref_code, pref_name, reuse
            )
        finally:
            qgis_io.load_and_dissolve_n03 = original_loader
            supplemental._write_merged_vectors = original_write
            v112_patches._write_p04_vectors = original_p04

    v113_layer_selection._build_supplemental_only = build_supplemental_only


def _patch_run_scope() -> None:
    cls = dialog_module.GCHAMDataPackDialog
    original_run = cls._run_build
    if getattr(original_run, "_gcham_v113_municipality_scope", False):
        return

    def _run_build(self):
        global _ACTIVE_ALL_MUNICIPALITIES, _ACTIVE_MUNICIPALITY_CODES
        layer_only = (
            hasattr(self, "layer_only_check")
            and self.layer_only_check.isChecked()
        )
        if layer_only and self.radio_selected.isChecked():
            if not self._selected_muni_codes:
                self._choose_municipalities()
            if not self._selected_muni_codes:
                return None

        _ACTIVE_ALL_MUNICIPALITIES = self.radio_all.isChecked()
        _ACTIVE_MUNICIPALITY_CODES = set(self._selected_muni_codes)
        try:
            return original_run(self)
        finally:
            _ACTIVE_ALL_MUNICIPALITIES = True
            _ACTIVE_MUNICIPALITY_CODES = set()

    _run_build._gcham_v113_municipality_scope = True
    cls._run_build = _run_build


def apply_v113_municipality_scope() -> None:
    global _APPLIED
    if _APPLIED:
        return
    v113_layer_selection._apply_layer_only_state = _apply_layer_only_state
    _patch_supplemental_only_scope()
    _patch_run_scope()
    _APPLIED = True
