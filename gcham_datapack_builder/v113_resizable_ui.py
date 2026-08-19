# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Ryo Horiike / GISPHN

from __future__ import annotations

from qgis.PyQt.QtWidgets import QSizePolicy

from . import dialog as dialog_module

_APPLIED = False


def _policy(name: str):
    scope = getattr(QSizePolicy, "Policy", QSizePolicy)
    return getattr(scope, name)


def _patch_resizable_dialog() -> None:
    cls = dialog_module.GCHAMDataPackDialog
    original_build_ui = cls._build_ui
    if getattr(original_build_ui, "_gcham_v113_resizable", False):
        return

    def _build_ui(self):
        original_build_ui(self)

        # Keep the action buttons visible on ordinary laptop displays.  Earlier
        # test builds assigned large minimum heights to both the supplemental
        # tree and the log pane, which effectively made the dialog taller than
        # the available screen and prevented useful vertical resizing.
        self.setSizeGripEnabled(True)
        self.setMinimumSize(760, 620)
        self.resize(940, 800)

        if hasattr(self, "supplemental_tree"):
            self.supplemental_tree.setMinimumHeight(100)
            self.supplemental_tree.setMaximumHeight(180)
            self.supplemental_tree.setSizePolicy(
                _policy("Expanding"), _policy("Preferred")
            )

        self.log_box.setMinimumHeight(80)
        self.log_box.setMaximumHeight(16777215)
        self.log_box.setSizePolicy(_policy("Expanding"), _policy("Expanding"))

        layout = self.layout()
        if layout is not None and hasattr(layout, "setStretchFactor"):
            layout.setStretchFactor(self.log_box, 1)

    _build_ui._gcham_v113_resizable = True
    cls._build_ui = _build_ui


def apply_v113_resizable_ui() -> None:
    global _APPLIED
    if _APPLIED:
        return
    _patch_resizable_dialog()
    _APPLIED = True
