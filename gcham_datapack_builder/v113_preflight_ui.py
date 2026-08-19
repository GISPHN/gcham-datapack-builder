# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Ryo Horiike / GISPHN

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from qgis.PyQt.QtCore import QStandardPaths
from qgis.PyQt.QtWidgets import QMessageBox

from . import dialog as dialog_module
from . import processor as processor_module
from .core_logic import estat_archive_name, n03_archive_name
from .qgis_io import valid_zip

_APPLIED = False


def _standard_cache_location() -> Path:
    scope = getattr(QStandardPaths, "StandardLocation", QStandardPaths)
    cache_location = getattr(scope, "CacheLocation")
    base = QStandardPaths.writableLocation(cache_location)
    if not base:
        base = tempfile.gettempdir()
    path = Path(base) / "gcham_datapack_builder" / "selection_cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _copy_if_valid_zip(source: Path, destination: Path) -> None:
    if not valid_zip(source):
        return
    if valid_zip(destination):
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _seed_n03_from_preflight(pref_code: str, output_dir: Path) -> None:
    preflight_root = _standard_cache_location()
    try:
        if preflight_root.resolve() == Path(output_dir).resolve():
            return
    except OSError:
        pass
    archive = n03_archive_name(pref_code)
    source = preflight_root / "_cache" / "n03" / archive
    destination = Path(output_dir) / "_cache" / "n03" / archive
    _copy_if_valid_zip(source, destination)


def _seed_estat_from_preflight(pref_code: str, output_dir: Path) -> None:
    preflight_root = _standard_cache_location()
    try:
        if preflight_root.resolve() == Path(output_dir).resolve():
            return
    except OSError:
        pass
    source_dir = preflight_root / "_cache" / "estat" / pref_code
    destination_dir = Path(output_dir) / "_cache" / "estat" / pref_code
    for stats_id, _table_name in processor_module.STAT_TABLES:
        archive = estat_archive_name(stats_id, pref_code)
        _copy_if_valid_zip(source_dir / archive, destination_dir / archive)


def _patch_processor_cache_reuse() -> None:
    cls = processor_module.DataPackProcessor

    original_n03 = cls.ensure_n03
    if not getattr(original_n03, "_gcham_v113_preflight", False):
        def ensure_n03(self, pref_code, output_dir, reuse=True):
            if reuse:
                _seed_n03_from_preflight(pref_code, Path(output_dir))
            return original_n03(self, pref_code, output_dir, reuse)

        ensure_n03._gcham_v113_preflight = True
        cls.ensure_n03 = ensure_n03

    original_estat = cls.ensure_estat_archives
    if not getattr(original_estat, "_gcham_v113_preflight", False):
        def ensure_estat_archives(self, pref_code, output_dir, reuse=True):
            if reuse:
                _seed_estat_from_preflight(pref_code, Path(output_dir))
            return original_estat(self, pref_code, output_dir, reuse)

        ensure_estat_archives._gcham_v113_preflight = True
        cls.ensure_estat_archives = ensure_estat_archives


def _patch_selection_actions() -> None:
    cls = dialog_module.GCHAMDataPackDialog

    def _choose_municipalities(self):
        code, _name = self._pref_data()
        cache_root = _standard_cache_location()
        try:
            self._set_progress(1, "自治体一覧を準備しています")
            municipalities = self._processor().prepare_municipalities(
                code,
                cache_root,
                self.reuse_check.isChecked(),
            )
            self._municipalities_cache = municipalities
            selection_dialog = dialog_module.MunicipalitySelectionDialog(
                municipalities,
                self._selected_muni_codes,
                self,
            )
            if dialog_module._dialog_exec(selection_dialog) == dialog_module._accepted_value():
                self._selected_muni_codes = selection_dialog.selected_codes()
                self.muni_summary.setText(
                    f"{len(self._selected_muni_codes)}自治体を選択"
                )
            self._set_progress(0, "準備完了")
        except Exception as exc:
            self._set_progress(0, "準備完了")
            QMessageBox.critical(self, "自治体一覧の取得に失敗", str(exc))
            self._log(str(exc))

    def _choose_additional_data(self):
        code, _name = self._pref_data()
        cache_root = _standard_cache_location()
        try:
            self._set_progress(1, "e-Stat項目一覧を準備しています")
            headers = self._processor().prepare_headers(
                code,
                cache_root,
                self.reuse_check.isChecked(),
            )
            self._headers_cache = headers
            selection_dialog = dialog_module.AdditionalDataDialog(
                headers,
                self.preset_codes,
                self.additional_codes,
                preset_enabled=self.preset_check.isChecked(),
                parent=self,
            )
            if dialog_module._dialog_exec(selection_dialog) == dialog_module._accepted_value():
                self.additional_codes = selection_dialog.selected_additional_codes()
                self._save_additional_codes()
                self._update_extra_summary()
            self._set_progress(0, "準備完了")
        except Exception as exc:
            self._set_progress(0, "準備完了")
            QMessageBox.critical(self, "項目一覧の取得に失敗", str(exc))
            self._log(str(exc))

    _choose_municipalities._gcham_v113_preflight = True
    _choose_additional_data._gcham_v113_preflight = True
    cls._choose_municipalities = _choose_municipalities
    cls._choose_additional_data = _choose_additional_data


def apply_v113_preflight_ui() -> None:
    global _APPLIED
    if _APPLIED:
        return
    _patch_processor_cache_reuse()
    _patch_selection_actions()
    _APPLIED = True
