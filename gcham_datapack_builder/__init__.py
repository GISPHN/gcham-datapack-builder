# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Ryo Horiike / GISPHN


def classFactory(iface):
    from .v112_patches import apply_patches
    from .v112_followup import apply_followup_patches

    apply_patches()
    apply_followup_patches()
    from .plugin import GCHAMDataPackBuilderPlugin

    return GCHAMDataPackBuilderPlugin(iface)
