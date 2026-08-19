# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Ryo Horiike / GISPHN


def classFactory(iface):
    from .v112_patches import apply_patches
    from .v112_followup import apply_followup_patches
    from .v112_cityfix import apply_cityfix
    from .v113_layer_selection import apply_v113_layer_selection
    from .v113_roadfix import apply_v113_roadfix
    from .v113_defaults_ui import apply_v113_defaults_ui
    from .v113_resizable_ui import apply_v113_resizable_ui
    from .v113_municipality_scope import apply_v113_municipality_scope
    from .v113_preflight_ui import apply_v113_preflight_ui
    from .v113_safety import apply_v113_safety
    from .v113_unified_workflow import apply_v113_unified_workflow

    apply_patches()
    apply_followup_patches()
    apply_cityfix()
    apply_v113_layer_selection()
    apply_v113_roadfix()
    apply_v113_defaults_ui()
    apply_v113_resizable_ui()
    apply_v113_municipality_scope()
    apply_v113_preflight_ui()
    apply_v113_safety()
    apply_v113_unified_workflow()
    from .plugin import GCHAMDataPackBuilderPlugin

    return GCHAMDataPackBuilderPlugin(iface)
