# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Ryo Horiike / GISPHN

from __future__ import annotations

from . import v113_layer_selection
from . import v113_municipality_scope

_APPLIED = False


def _patch_internal_result_guard() -> None:
    original = v113_municipality_scope._rename_result_for_municipality
    if getattr(original, "_gcham_v113_internal_guard", False):
        return

    def _rename_result_for_municipality(result, pref_code, municipality):
        if result.group == v113_layer_selection._INTERNAL_GROUP:
            return result
        return original(result, pref_code, municipality)

    _rename_result_for_municipality._gcham_v113_internal_guard = True
    v113_municipality_scope._rename_result_for_municipality = (
        _rename_result_for_municipality
    )


def apply_v113_safety() -> None:
    global _APPLIED
    if _APPLIED:
        return
    _patch_internal_result_guard()
    _APPLIED = True
