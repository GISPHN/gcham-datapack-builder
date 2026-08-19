# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Ryo Horiike / GISPHN

from __future__ import annotations

import gc
from pathlib import Path

from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsFeatureRequest,
    QgsFeatureSink,
    QgsGeometry,
    QgsVectorLayer,
    QgsWkbTypes,
)

from . import dialog as dialog_module
from . import qgis_io
from . import supplemental
from . import v112_patches
from . import v113_layer_selection

_APPLIED = False


def _no_default_layers(_dialog) -> set[str]:
    """Start every newly opened dialog with all supplemental layers unchecked."""
    return set()


def _patch_default_selection() -> None:
    v113_layer_selection.DEFAULT_LAYER_KEYS = set()
    v113_layer_selection._load_layer_selection = _no_default_layers


def _patch_dialog_sizes() -> None:
    cls = dialog_module.GCHAMDataPackDialog
    original = cls._build_ui
    if getattr(original, "_gcham_v113_roadfix", False):
        return

    def _build_ui(self):
        original(self)
        self.resize(940, 920)
        if hasattr(self, "supplemental_tree"):
            self.supplemental_tree.setMinimumHeight(180)
            self.supplemental_tree.setMaximumHeight(270)
        self.log_box.setMinimumHeight(230)
        layout = self.layout()
        if layout is not None and hasattr(layout, "setStretchFactor"):
            layout.setStretchFactor(self.log_box, 3)

    _build_ui._gcham_v113_roadfix = True
    cls._build_ui = _build_ui


def _geometry_engine_contains(engine, pref_geometry: QgsGeometry, feature_geometry: QgsGeometry) -> bool:
    if engine is not None:
        try:
            return bool(engine.contains(feature_geometry.constGet()))
        except Exception:
            return bool(pref_geometry.contains(feature_geometry))
    return bool(pref_geometry.contains(feature_geometry))


def _geometry_engine_intersects(engine, pref_geometry: QgsGeometry, feature_geometry: QgsGeometry) -> bool:
    if engine is not None:
        try:
            return bool(engine.intersects(feature_geometry.constGet()))
        except Exception:
            return bool(feature_geometry.intersects(pref_geometry))
    return bool(feature_geometry.intersects(pref_geometry))


def _source_extent_geometry(layer: QgsVectorLayer) -> QgsGeometry:
    extent = layer.extent()
    if extent.isNull() or extent.isEmpty():
        return QgsGeometry()
    geom = QgsGeometry.fromRect(extent)
    to_geo = supplemental._geo_transform(layer.crs())
    if to_geo is not None:
        geom.transform(to_geo)
    return geom


def _write_roads_fast(
    sources: list[Path],
    out_path: Path,
    target_epsg: int,
    pref_geometry: QgsGeometry,
    log,
    check_cancelled,
) -> Path:
    if not sources:
        raise RuntimeError("道路N13の入力ベクタがありません。")

    first = QgsVectorLayer(str(sources[0]), "road_source", "ogr")
    if not first.isValid():
        raise RuntimeError(f"道路入力データを開けません: {sources[0]}")

    extras = tuple(supplemental.ROAD_MAPS.keys())
    base_names = [field.name() for field in first.fields()]
    out_fields = supplemental._copy_fields(first.fields(), extras)
    writer_wkb = QgsWkbTypes.multiType(first.wkbType())
    writer = supplemental._create_writer(out_path, out_fields, writer_wkb, target_epsg)

    pref_check, engine = v112_patches._prepared_prefecture_geometry(pref_geometry)
    geo_crs = QgsCoordinateReferenceSystem.fromEpsgId(6668)
    geo_to_target = supplemental._transform(geo_crs, target_epsg)

    scanned = 0
    candidates = 0
    contained = 0
    clipped = 0
    written = 0

    try:
        total_sources = len(sources)
        for source_index, source_path in enumerate(sources, start=1):
            check_cancelled()
            layer = QgsVectorLayer(str(source_path), "road_source", "ogr")
            if not layer.isValid():
                raise RuntimeError(f"道路入力データを開けません: {source_path}")

            field_names = [field.name() for field in layer.fields()]
            to_target = supplemental._transform(layer.crs(), target_epsg)
            to_geo = supplemental._geo_transform(layer.crs())
            source_extent = _source_extent_geometry(layer)
            source_fully_inside = (
                not source_extent.isNull()
                and not source_extent.isEmpty()
                and _geometry_engine_contains(engine, pref_check, source_extent)
            )

            request = QgsFeatureRequest()
            if not source_fully_inside:
                try:
                    request.setFilterRect(
                        v112_patches._source_filter_rect(pref_check, layer.crs())
                    )
                except Exception as exc:
                    log(
                        f"道路N13 {source_path.name}: bbox事前抽出を適用できないため全件走査します: {exc}"
                    )

            source_total = layer.featureCount()
            mode = "県内メッシュ・クリップ省略" if source_fully_inside else "県境候補のみ抽出"
            log(
                f"道路N13処理 {source_index}/{total_sources}: {source_path.name} / "
                f"{source_total:,}件 / {mode}"
            )

            for src in layer.getFeatures(request):
                scanned += 1
                candidates += 1
                if scanned % 2000 == 0:
                    QCoreApplication.processEvents()
                    check_cancelled()
                    log(
                        "道路N13処理中: "
                        f"候補 {candidates:,}件 / 県内 {contained:,}件 / "
                        f"境界クリップ {clipped:,}件 / 出力 {written:,}件"
                    )

                if not src.hasGeometry() or src.geometry().isEmpty():
                    continue

                if source_fully_inside:
                    geom = supplemental._copy_geom(src.geometry(), to_target)
                    contained += 1
                else:
                    check_geom = supplemental._copy_geom(src.geometry(), to_geo)
                    if _geometry_engine_contains(engine, pref_check, check_geom):
                        geom = QgsGeometry(check_geom)
                        if geo_to_target is not None:
                            geom.transform(geo_to_target)
                        contained += 1
                    else:
                        if not _geometry_engine_intersects(engine, pref_check, check_geom):
                            continue
                        geom = check_geom.intersection(pref_check)
                        if geom.isNull() or geom.isEmpty():
                            continue
                        if geo_to_target is not None:
                            geom.transform(geo_to_target)
                        clipped += 1

                if not geom.isMultipart():
                    geom.convertToMultiType()

                feat = QgsFeature(out_fields)
                feat.setGeometry(geom)
                attrs = [src[name] if name in field_names else None for name in base_names]
                for _new_name, (source_name, mapping) in supplemental.ROAD_MAPS.items():
                    raw = src[source_name] if source_name in field_names else None
                    try:
                        key = int(raw) if raw is not None and str(raw).strip() else None
                    except (TypeError, ValueError):
                        key = None
                    attrs.append(mapping.get(key))
                feat.setAttributes(attrs)
                if not writer.addFeature(
                    feat,
                    getattr(getattr(QgsFeatureSink, "Flag", QgsFeatureSink), "FastInsert"),
                ):
                    raise RuntimeError(f"道路FGB書き込みに失敗しました: {out_path}")
                written += 1
    finally:
        del writer
        gc.collect()

    if written == 0:
        raise RuntimeError(f"対象道路地物が0件でした: {out_path.name}")

    log(
        "道路N13完了: "
        f"候補 {candidates:,}件 / 県内 {contained:,}件 / "
        f"境界クリップ {clipped:,}件 / 出力 {written:,}件"
    )
    return out_path


def _patch_roads() -> None:
    original = supplemental.SupplementalBuilder.build_roads
    if getattr(original, "_gcham_v113_roadfix", False):
        return

    def build_roads(self):
        road_sources = []
        mesh_codes = supplemental.first_mesh_codes(self.pref_geometry)
        self.log("道路N13対象メッシュ: " + ", ".join(mesh_codes))
        for code in mesh_codes:
            self.check_cancelled()
            road_sources.extend(
                self._ksj_vectors("N13", "24", f"N13-24_{code}_SHP.zip")
            )

        road_out = self.data_dir / f"n13_2024_{self.pref_code}_roads.fgb"
        qgis_io.remove_existing_layer_for_path(road_out)
        road_out.unlink(missing_ok=True)
        _write_roads_fast(
            road_sources,
            road_out,
            self.target_epsg,
            self.pref_geometry,
            self.log,
            self.check_cancelled,
        )
        return [
            supplemental.SupplementalResult(
                road_out,
                "道路_2024_国土数値情報",
                "交通",
                "road",
            )
        ]

    build_roads._gcham_v113_roadfix = True
    supplemental.SupplementalBuilder.build_roads = build_roads


def apply_v113_roadfix() -> None:
    global _APPLIED
    if _APPLIED:
        return
    _patch_default_selection()
    _patch_roads()
    _patch_dialog_sizes()
    _APPLIED = True
