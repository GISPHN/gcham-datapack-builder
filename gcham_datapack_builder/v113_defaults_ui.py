# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Ryo Horiike / GISPHN

from __future__ import annotations

import json

from qgis.PyQt.QtWidgets import QHBoxLayout, QPushButton

from . import dialog as dialog_module
from . import v113_layer_selection
from .constants import SETTINGS_PREFIX

_APPLIED = False
_DEFAULTS = set(v113_layer_selection.ALL_LAYER_KEYS) - {"road_n13"}
_MIGRATION_KEY = f"{SETTINGS_PREFIX}/supplemental_defaults_v113_test3"
_SELECTION_KEY = f"{SETTINGS_PREFIX}/supplemental_layers"


def _load_layer_selection(dialog) -> set[str]:
    """Load saved selection, migrating test2's all-off default once to the new default."""
    migrated = bool(dialog.settings.value(_MIGRATION_KEY, False, type=bool))
    if not migrated:
        values = sorted(_DEFAULTS)
        dialog.settings.setValue(
            _SELECTION_KEY,
            json.dumps(values, ensure_ascii=False),
        )
        dialog.settings.setValue(_MIGRATION_KEY, True)
        return set(_DEFAULTS)

    raw = dialog.settings.value(_SELECTION_KEY, "")
    if raw in (None, ""):
        return set(_DEFAULTS)
    try:
        values = set(json.loads(str(raw)))
    except (TypeError, ValueError, json.JSONDecodeError):
        return set(_DEFAULTS)
    return values.intersection(v113_layer_selection.ALL_LAYER_KEYS)


def _clear_all(dialog) -> None:
    v113_layer_selection._set_tree_selection(dialog, set())
    v113_layer_selection._save_layer_selection(dialog)


def _patch_defaults() -> None:
    v113_layer_selection.DEFAULT_LAYER_KEYS = set(_DEFAULTS)
    v113_layer_selection._load_layer_selection = _load_layer_selection


def _patch_clear_button() -> None:
    cls = dialog_module.GCHAMDataPackDialog
    original_build_ui = cls._build_ui
    if getattr(original_build_ui, "_gcham_v113_defaults_ui", False):
        return

    def _build_ui(self):
        original_build_ui(self)
        if not hasattr(self, "supplemental_tree"):
            return

        self.clear_layers_button = QPushButton("すべてのチェックを外す")
        self.clear_layers_button.setToolTip(
            "追加レイヤのチェックをすべて解除します。特定レイヤだけ追加したい場合に使用します。"
        )
        self.clear_layers_button.clicked.connect(lambda: _clear_all(self))

        group_widget = self.supplemental_tree.parentWidget()
        group_layout = group_widget.layout() if group_widget is not None else None
        inserted = False
        if group_layout is not None:
            for i in range(group_layout.count()):
                item = group_layout.itemAt(i)
                row = item.layout() if item is not None else None
                if row is None:
                    continue
                if hasattr(self, "reset_layers_button"):
                    for j in range(row.count()):
                        child = row.itemAt(j)
                        if child is not None and child.widget() is self.reset_layers_button:
                            row.insertWidget(j, self.clear_layers_button)
                            inserted = True
                            break
                if inserted:
                    break
        if not inserted and group_layout is not None:
            row = QHBoxLayout()
            row.addStretch(1)
            row.addWidget(self.clear_layers_button)
            group_layout.addLayout(row)

    _build_ui._gcham_v113_defaults_ui = True
    cls._build_ui = _build_ui

    original_set_running = cls._set_running

    def _set_running(self, running):
        original_set_running(self, running)
        if hasattr(self, "clear_layers_button"):
            self.clear_layers_button.setEnabled(not running)

    cls._set_running = _set_running


def apply_v113_defaults_ui() -> None:
    global _APPLIED
    if _APPLIED:
        return
    _patch_defaults()
    _patch_clear_button()
    _APPLIED = True
