# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Ryo Horiike / GISPHN

from __future__ import annotations

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTreeWidgetItem,
)

from . import dialog as dialog_module
from . import qgis_io
from . import v113_defaults_ui
from . import v113_layer_selection
from . import v113_municipality_scope
from .constants import SETTINGS_PREFIX
from .processor import BuildOptions

_APPLIED = False
POPULATION_KEY = "population_census"
WORKFLOW_MIGRATION_KEY = f"{SETTINGS_PREFIX}/unified_workflow_v113_test7"


def _truthy(value) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _patch_selection_constants() -> None:
    all_keys = set(v113_layer_selection.ALL_LAYER_KEYS)
    all_keys.add(POPULATION_KEY)
    defaults = all_keys - {"road_n13"}
    v113_layer_selection.ALL_LAYER_KEYS = all_keys
    v113_layer_selection.DEFAULT_LAYER_KEYS = set(defaults)
    v113_defaults_ui._DEFAULTS = set(defaults)


def _selected(dialog) -> set[str]:
    return v113_layer_selection._selected_layer_keys(dialog)


def _supplemental_selected(selection: set[str]) -> set[str]:
    return set(selection) - {POPULATION_KEY}


def _set_population_internal(dialog, enabled: bool) -> None:
    dialog.preset_check.setChecked(bool(enabled))
    available = not dialog._running and bool(enabled)
    dialog.extra_button.setEnabled(available)
    dialog.reset_extra_button.setEnabled(available)
    dialog.extra_summary.setEnabled(available)


def _update_data_summary(dialog) -> None:
    if not hasattr(dialog, "data_selection_summary"):
        return
    selection = _selected(dialog)
    total = len(v113_layer_selection.ALL_LAYER_KEYS)
    dialog.data_selection_summary.setText(
        f"選択: {len(selection)}/{total}データ"
    )
    _set_population_internal(dialog, POPULATION_KEY in selection)


def _reset_population_columns(dialog) -> None:
    dialog.additional_codes.clear()
    dialog._save_additional_codes()
    dialog._update_extra_summary()


def _select_datapack(dialog) -> None:
    selection = set(v113_layer_selection.ALL_LAYER_KEYS) - {"road_n13"}
    v113_layer_selection._set_tree_selection(dialog, selection)
    v113_layer_selection._save_layer_selection(dialog)
    _reset_population_columns(dialog)
    _update_data_summary(dialog)


def _select_specific(dialog) -> None:
    v113_layer_selection._set_tree_selection(dialog, set())
    v113_layer_selection._save_layer_selection(dialog)
    _reset_population_columns(dialog)
    _update_data_summary(dialog)


def _ancestor_group(widget):
    current = widget.parentWidget() if widget is not None else None
    while current is not None:
        if isinstance(current, QGroupBox):
            return current
        current = current.parentWidget()
    return None


def _update_data_enabled(dialog) -> None:
    if not hasattr(dialog, "supplemental_tree"):
        return
    selected_mode_ready = (
        not dialog.radio_selected.isChecked()
        or bool(dialog._selected_muni_codes)
    )
    enabled = not dialog._running and selected_mode_ready
    dialog.supplemental_tree.setEnabled(enabled)
    if hasattr(dialog, "datapack_button"):
        dialog.datapack_button.setEnabled(enabled)
    if hasattr(dialog, "specific_button"):
        dialog.specific_button.setEnabled(enabled)
    if hasattr(dialog, "data_selection_summary"):
        dialog.data_selection_summary.setEnabled(enabled)
    population_enabled = POPULATION_KEY in _selected(dialog)
    dialog.extra_button.setEnabled(enabled and population_enabled)
    dialog.reset_extra_button.setEnabled(enabled and population_enabled)
    dialog.extra_summary.setEnabled(enabled and population_enabled)


def _patch_dialog_ui() -> None:
    cls = dialog_module.GCHAMDataPackDialog
    original_build = cls._build_ui
    if getattr(original_build, "_gcham_v113_unified", False):
        return

    def _build_ui(self):
        original_build(self)

        target_group = _ancestor_group(self.pref_combo)
        if target_group is not None:
            target_group.setTitle("① 対象自治体を選択")

        # The former population-only block is replaced by a single unified
        # creation-data tree. Keep the widgets alive for the established
        # BuildOptions pathway, but move the population-column controls into
        # the unified panel.
        old_population_group = _ancestor_group(self.preset_check)
        if old_population_group is not None:
            old_population_group.setVisible(False)
        self.preset_check.setVisible(False)

        data_group = _ancestor_group(self.supplemental_tree)
        if data_group is not None:
            data_group.setTitle("② 作成データを選択")
        data_layout = data_group.layout() if data_group is not None else None
        if data_layout is None:
            return

        if hasattr(self, "layer_only_check"):
            self.layer_only_check.setVisible(False)

        # Population is a peer of facility/transport/disaster data, not a
        # separate workflow.
        population_root = QTreeWidgetItem(["人口データ"])
        population_root.setFlags(
            population_root.flags()
            | v113_layer_selection._qt_item_flag("ItemIsUserCheckable")
            | v113_layer_selection._qt_item_flag("ItemIsEnabled")
        )
        population_child = QTreeWidgetItem(["250mメッシュ人口（2020年国勢調査）"])
        population_child.setData(0, dialog_module._user_role(), POPULATION_KEY)
        population_child.setFlags(
            population_child.flags()
            | v113_layer_selection._qt_item_flag("ItemIsUserCheckable")
            | v113_layer_selection._qt_item_flag("ItemIsEnabled")
        )
        population_child.setCheckState(0, v113_layer_selection._unchecked())
        population_root.addChild(population_child)
        population_root.setExpanded(True)
        self.supplemental_tree.insertTopLevelItem(0, population_root)

        # Re-apply saved selection after the population item exists.
        saved = v113_layer_selection._load_layer_selection(self)
        v113_layer_selection._set_tree_selection(self, saved)

        action_row = QHBoxLayout()
        self.datapack_button = QPushButton("G-CHAMデータパックのデータ")
        self.datapack_button.setToolTip(
            "人口・施設・交通・災害・背景地図を選択します。容量の大きい道路は選択しません。"
        )
        self.specific_button = QPushButton("特定のデータを追加")
        self.specific_button.setToolTip(
            "すべてのチェックを外し、必要なデータだけを選択できる状態にします。"
        )
        self.data_selection_summary = QLabel()
        action_row.addWidget(self.datapack_button)
        action_row.addWidget(self.specific_button)
        action_row.addStretch(1)
        action_row.addWidget(self.data_selection_summary)
        data_layout.insertLayout(0, action_row)

        # Keep the detailed Census-column selector available, but inside the
        # population entry of the unified workflow.
        self.extra_button.setText("人口項目を選択...")
        self.reset_extra_button.setText("人口項目を初期設定に戻す")
        population_row = QHBoxLayout()
        population_row.addSpacing(28)
        population_row.addWidget(self.extra_button)
        population_row.addWidget(self.extra_summary, 1)
        population_row.addWidget(self.reset_extra_button)
        data_layout.insertLayout(2, population_row)

        # The older test-build controls are superseded by the two explicit
        # workflow buttons above.
        if hasattr(self, "clear_layers_button"):
            self.clear_layers_button.setVisible(False)
        if hasattr(self, "reset_layers_button"):
            self.reset_layers_button.setVisible(False)

        output_group = _ancestor_group(self.output_edit)
        if output_group is not None:
            output_group.setTitle("③ 出力")
        self.create_button.setText("選択したデータを作成")

        self.datapack_button.clicked.connect(lambda: _select_datapack(self))
        self.specific_button.clicked.connect(lambda: _select_specific(self))
        self.supplemental_tree.itemChanged.connect(
            lambda _item, _column: _update_data_summary(self)
        )
        self.radio_selected.toggled.connect(lambda _value: _update_data_enabled(self))
        self.pref_combo.currentIndexChanged.connect(
            lambda _index: _update_data_enabled(self)
        )

        # Migrate the preceding test-build selection once. New users see the
        # complete G-CHAM pack selection immediately; later dialog openings
        # preserve their last explicit selection.
        migrated = _truthy(self.settings.value(WORKFLOW_MIGRATION_KEY, False))
        if not migrated:
            _select_datapack(self)
            self.settings.setValue(WORKFLOW_MIGRATION_KEY, True)
        else:
            _update_data_summary(self)
        _update_data_enabled(self)

    _build_ui._gcham_v113_unified = True
    cls._build_ui = _build_ui

    original_choose_muni = cls._choose_municipalities

    def _choose_municipalities(self):
        result = original_choose_muni(self)
        _update_data_enabled(self)
        return result

    cls._choose_municipalities = _choose_municipalities

    original_set_running = cls._set_running

    def _set_running(self, running):
        original_set_running(self, running)
        if hasattr(self, "datapack_button"):
            _update_data_enabled(self)
        if not running:
            _update_data_summary(self)

    cls._set_running = _set_running


def _run_population_and_scoped_supplementals(self, selection: set[str]):
    """Build population/core once, then selected supplemental data per municipality."""
    output = self._ensure_output_dir()
    if output is None:
        return None
    if self.radio_selected.isChecked() and not self._selected_muni_codes:
        self._choose_municipalities()
        if not self._selected_muni_codes:
            return None

    code, name = self._pref_data()
    self._cancelled = False
    self.log_box.clear()
    self._set_running(True)

    previous_selection = v113_layer_selection._CURRENT_SELECTION
    previous_all = v113_municipality_scope._ACTIVE_ALL_MUNICIPALITIES
    previous_codes = set(v113_municipality_scope._ACTIVE_MUNICIPALITY_CODES)
    try:
        processor = self._processor()
        core_options = BuildOptions(
            pref_code=code,
            pref_name=name,
            output_dir=output,
            all_municipalities=False,
            selected_municipality_codes=set(self._selected_muni_codes),
            use_preset=True,
            additional_codes=set(self.additional_codes),
            reuse_downloads=self.reuse_check.isChecked(),
            include_facilities=False,
            include_transport=False,
            include_roads=False,
            include_disaster=False,
            include_background=False,
        )
        core_result = processor.build(core_options, self._confirm_existing)

        v113_layer_selection._CURRENT_SELECTION = set(selection)
        v113_municipality_scope._ACTIVE_ALL_MUNICIPALITIES = False
        v113_municipality_scope._ACTIVE_MUNICIPALITY_CODES = set(
            self._selected_muni_codes
        )
        supplemental_results = v113_layer_selection._build_supplemental_only(
            processor,
            output,
            code,
            name,
            self.reuse_check.isChecked(),
        )
        QMessageBox.information(
            self,
            "完了",
            "選択したG-CHAMデータを作成しました。\n\n"
            f"出力先: {output}\n"
            f"自治体数: {len(core_result['municipalities'])}\n"
            f"追加データ: {len(supplemental_results)}レイヤ",
        )
    except qgis_io.CancelledError as exc:
        self._log(str(exc))
        self._set_progress(self.progress_bar.value(), "処理を中止しました")
    except Exception as exc:
        self._log(f"ERROR: {exc}")
        QMessageBox.critical(self, "G-CHAM Data Pack Builder", str(exc))
        self._set_progress(self.progress_bar.value(), "エラーで停止しました")
    finally:
        v113_layer_selection._CURRENT_SELECTION = previous_selection
        v113_municipality_scope._ACTIVE_ALL_MUNICIPALITIES = previous_all
        v113_municipality_scope._ACTIVE_MUNICIPALITY_CODES = previous_codes
        self._set_running(False)
    return None


def _patch_run_logic() -> None:
    cls = dialog_module.GCHAMDataPackDialog
    original_run = cls._run_build
    if getattr(original_run, "_gcham_v113_unified", False):
        return

    def _run_build(self):
        selection = _selected(self)
        if not selection:
            QMessageBox.warning(
                self,
                "作成データが未選択です",
                "作成するデータを1つ以上選択してください。",
            )
            return None

        population_selected = POPULATION_KEY in selection
        supplemental_selection = _supplemental_selected(selection)
        _set_population_internal(self, population_selected)

        # The legacy layer-only switch remains as an internal implementation
        # detail. Users no longer need to understand or operate it.
        if hasattr(self, "layer_only_check"):
            self.layer_only_check.setChecked(not population_selected)

        # A selected-municipality full pack needs two stages so the supplemental
        # outputs are actually scoped and named per municipality rather than
        # being silently generated for the whole prefecture.
        if (
            population_selected
            and supplemental_selection
            and self.radio_selected.isChecked()
        ):
            return _run_population_and_scoped_supplementals(self, selection)

        return original_run(self)

    _run_build._gcham_v113_unified = True
    cls._run_build = _run_build


def apply_v113_unified_workflow() -> None:
    global _APPLIED
    if _APPLIED:
        return
    _patch_selection_constants()
    _patch_dialog_ui()
    _patch_run_logic()
    _APPLIED = True
