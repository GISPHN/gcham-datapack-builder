# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Ryo Horiike / GISPHN

from __future__ import annotations

import gc
import time
import zipfile
from pathlib import Path

from qgis.PyQt.QtCore import QCoreApplication, Qt
from qgis.core import QgsFeature, QgsField, QgsFields, QgsGeometry, QgsProject, QgsVectorLayer

from . import dialog as dialog_module
from . import processor as processor_module
from . import qgis_io
from . import supplemental
from . import v112_patches
from .constants import plane_rectangular_epsg

_APPLIED = False
_LAST_PUMP = 0.0
_PUMPING = False


def _pump_gui(force: bool = False) -> None:
    """Keep the QGIS event queue responsive during synchronous build loops.

    The elapsed-time label is driven by QElapsedTimer/QTimer. The build remains
    synchronous because many QgsProject/QgsVectorLayer operations must stay on
    the GUI thread, so long Python loops periodically yield to Qt. The displayed
    time itself is wall-clock elapsed time and is not derived from progress %.
    """
    global _LAST_PUMP, _PUMPING
    now = time.monotonic()
    if _PUMPING:
        return
    if not force and now - _LAST_PUMP < 0.08:
        return
    _PUMPING = True
    try:
        QCoreApplication.processEvents()
        _LAST_PUMP = now
    finally:
        _PUMPING = False


def _patch_elapsed_heartbeat() -> None:
    cls = dialog_module.GCHAMDataPackDialog
    original_build_ui = cls._build_ui
    if getattr(original_build_ui, "_gcham_v112_followup", False):
        return

    def _build_ui(self):
        original_build_ui(self)
        # A short timer interval makes the visible counter recover immediately
        # whenever the Qt event queue is yielded to. The value is still shown as mm:ss.
        if hasattr(self, "_elapsed_timer"):
            self._elapsed_timer.setInterval(250)
            timer_type = getattr(getattr(Qt, "TimerType", Qt), "PreciseTimer", None)
            if timer_type is not None:
                self._elapsed_timer.setTimerType(timer_type)

    _build_ui._gcham_v112_followup = True
    cls._build_ui = _build_ui

    original_check = processor_module.DataPackProcessor.check_cancelled

    def check_cancelled(self):
        _pump_gui()
        return original_check(self)

    processor_module.DataPackProcessor.check_cancelled = check_cancelled

    original_supp_check = supplemental.SupplementalBuilder.check_cancelled

    def supplemental_check_cancelled(self):
        _pump_gui()
        return original_supp_check(self)

    supplemental.SupplementalBuilder.check_cancelled = supplemental_check_cancelled

    original_assign = qgis_io.MunicipalityIndex.assign

    def assign(self, key_code):
        _pump_gui()
        return original_assign(self, key_code)

    qgis_io.MunicipalityIndex.assign = assign


def _patch_download_heartbeat() -> None:
    original_download = qgis_io.download_file
    if getattr(original_download, "_gcham_v112_followup", False):
        return

    def download_file(
        url,
        destination,
        log=None,
        progress=None,
        force_refresh=True,
    ):
        def heartbeat(received, total):
            _pump_gui(force=True)
            if progress is not None:
                progress(received, total)

        return original_download(
            url,
            destination,
            log=log,
            progress=heartbeat,
            force_refresh=force_refresh,
        )

    download_file._gcham_v112_followup = True
    qgis_io.download_file = download_file
    # Both modules imported download_file directly, so replace those aliases too.
    if hasattr(processor_module, "download_file"):
        processor_module.download_file = download_file
    supplemental.download_file = download_file


def _responsive_extract_zip(zip_path: Path, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.infolist():
            target = (destination / member.filename).resolve()
            if root not in target.parents and target != root:
                raise RuntimeError(f"不正なZIPパスを検出しました: {member.filename}")
            zf.extract(member, destination)
            _pump_gui()
    return destination


def _patch_extract_heartbeat() -> None:
    if getattr(qgis_io.safe_extract_zip, "_gcham_v112_followup", False):
        return
    _responsive_extract_zip._gcham_v112_followup = True
    qgis_io.safe_extract_zip = _responsive_extract_zip
    if hasattr(processor_module, "safe_extract_zip"):
        processor_module.safe_extract_zip = _responsive_extract_zip
    supplemental.safe_extract_zip = _responsive_extract_zip


def _designated_city_groups(municipalities):
    """Return designated-city parent groups inferred from N03 ward records.

    N03_004 contains the city name and N03_005 contains the ward name for
    ordinance-designated cities. Requiring multiple ward records avoids treating
    ordinary municipalities as parent-city boundaries.
    """
    grouped: dict[str, dict] = {}
    for municipality in municipalities:
        attributes = municipality.attributes
        city_name = str(attributes.get("N03_004") or "").strip()
        ward_name = str(attributes.get("N03_005") or "").strip()
        code = str(municipality.code).strip()
        if not city_name or not ward_name or not city_name.endswith("市"):
            continue
        if len(code) != 5 or not code.isdigit():
            continue
        city_code = code[:3] + "00"
        entry = grouped.setdefault(
            city_code,
            {"name": city_name, "wards": [], "geometries": []},
        )
        if entry["name"] != city_name:
            # A shared three-digit prefix with conflicting parent names is not a
            # valid designated-city grouping; mark it unusable rather than guess.
            entry["conflict"] = True
            continue
        entry["wards"].append(code)
        entry["geometries"].append(QgsGeometry(municipality.geometry))

    result = {}
    for city_code, entry in grouped.items():
        if entry.get("conflict") or len(set(entry["wards"])) < 2:
            continue
        result[city_code] = entry
    return result


def _write_designated_city_boundary(
    path: Path,
    city_code: str,
    city_name: str,
    geometries,
    target_epsg: int,
) -> None:
    geometry = QgsGeometry.unaryUnion([QgsGeometry(g) for g in geometries])
    if geometry.isNull() or geometry.isEmpty():
        raise RuntimeError(f"政令指定都市境界を作成できませんでした: {city_name}")
    if not geometry.isMultipart():
        geometry.convertToMultiType()

    fields = QgsFields()
    fields.append(QgsField("CITY_CODE", qgis_io.qmeta_string()))
    fields.append(QgsField("CITY_NAME", qgis_io.qmeta_string()))

    qgis_io.remove_existing_layer_for_path(path)
    path.unlink(missing_ok=True)
    writer = qgis_io.create_fgb_writer(path, fields, target_epsg)
    feature = QgsFeature(fields)
    feature.setGeometry(
        qgis_io.transform_geometry(
            geometry,
            qgis_io.geometry_transformer(target_epsg),
        )
    )
    feature.setAttributes([city_code, city_name])
    try:
        if not writer.addFeature(feature):
            raise RuntimeError(f"政令指定都市境界FGBへの書き込みに失敗しました: {path}")
        if hasattr(writer, "flushBuffer"):
            writer.flushBuffer()
    finally:
        del writer
        gc.collect()


def _add_designated_city_layer(path: Path, city_name: str, index: int):
    qgis_io.remove_existing_layer_for_path(path)
    layer = QgsVectorLayer(
        str(path),
        f"{city_name}_行政区域_国土数値情報（政令指定都市境界）",
        "ogr",
    )
    if not layer.isValid():
        raise RuntimeError(f"政令指定都市境界FGBをQGISへ追加できません: {path}")
    # Same visual hierarchy as the prefecture outline: transparent fill, black border.
    v112_patches._style_prefecture_admin(layer)
    project = QgsProject.instance()
    root = project.layerTreeRoot()
    group = root.findGroup("行政区域") or root.addGroup("行政区域")
    project.addMapLayer(layer, False)
    group.insertLayer(index, layer)
    return layer


def _patch_designated_city_boundaries() -> None:
    original_build = processor_module.DataPackProcessor.build
    if getattr(original_build, "_gcham_v112_followup_city", False):
        return

    def build(self, options, confirm_existing=None):
        result = original_build(self, options, confirm_existing)
        n03_vector = self.ensure_n03(
            options.pref_code,
            options.output_dir,
            options.reuse_downloads,
        )
        all_municipalities, _fields = qgis_io.load_and_dissolve_n03(n03_vector)
        groups = _designated_city_groups(all_municipalities)
        selected_codes = set(result.get("admin_paths", {}).keys())
        target_epsg = plane_rectangular_epsg(options.pref_code)
        city_paths = {}

        display_index = 1  # prefecture outline is inserted at index 0 by v1.1.2 patch
        for city_code in sorted(groups):
            entry = groups[city_code]
            ward_codes = set(entry["wards"])
            if not options.all_municipalities and not (
                city_code in selected_codes or ward_codes.intersection(selected_codes)
            ):
                continue
            city_name = entry["name"]
            path = (
                options.output_dir
                / "admin"
                / f"n03_{city_code}_designated_city_admin.fgb"
            )
            _write_designated_city_boundary(
                path,
                city_code,
                city_name,
                entry["geometries"],
                target_epsg,
            )
            _add_designated_city_layer(path, city_name, display_index)
            city_paths[city_code] = path
            display_index += 1
            self.log(
                f"政令指定都市境界を追加: {city_name} ({city_code}) / "
                f"{len(ward_codes)}区をディゾルブ"
            )
            _pump_gui(force=True)

        result["designated_city_admin"] = city_paths
        return result

    build._gcham_v112_followup_city = True
    processor_module.DataPackProcessor.build = build


def apply_followup_patches() -> None:
    global _APPLIED
    if _APPLIED:
        return
    _patch_elapsed_heartbeat()
    _patch_download_heartbeat()
    _patch_extract_heartbeat()
    _patch_designated_city_boundaries()
    _APPLIED = True
