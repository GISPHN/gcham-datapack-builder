# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Ryo Horiike / GISPHN

def classFactory(iface):
    from .plugin import GCHAMDataPackBuilderPlugin
    return GCHAMDataPackBuilderPlugin(iface)
