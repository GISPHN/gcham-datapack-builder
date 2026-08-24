# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Ryo Horiike / GISPHN

from __future__ import annotations

from qgis.core import QgsProject

from . import v114_facility_resilience

_APPLIED = False


def _move_existing_population_group() -> None:
    """Move the existing population group without cloning or recreating its layers."""
    root = QgsProject.instance().layerTreeRoot()
    population = root.findGroup("250mメッシュ人口")
    if population is None or population.parent() is not root:
        return

    disaster = root.findGroup("災害")
    background = root.findGroup("背景地図")

    if disaster is not None and disaster.parent() is root:
        children = root.children()
        population_index = children.index(population)
        disaster_index = children.index(disaster)
        if population_index == disaster_index + 1:
            return

        # takeChild() detaches the exact node without deleting it. Reinsert the
        # same group object so its prefecture/municipality population layer nodes
        # remain intact; only the top-level group position changes.
        if not root.takeChild(population):
            return
        disaster_index = root.children().index(disaster)
        root.insertChildNode(disaster_index + 1, population)
        return

    if background is None or background.parent() is not root:
        return

    children = root.children()
    population_index = children.index(population)
    background_index = children.index(background)
    if population_index == background_index - 1:
        return

    if not root.takeChild(population):
        return
    background_index = root.children().index(background)
    root.insertChildNode(background_index, population)


def apply_v114_population_order_fix() -> None:
    global _APPLIED
    if _APPLIED:
        return
    # The v1.1.4 supplemental wrapper calls this function at runtime. Replace
    # only the ordering function; population download/build/add-layer processing
    # remains the established v1.1.3 pathway unchanged.
    v114_facility_resilience._normalize_population_group_order = (
        _move_existing_population_group
    )
    _APPLIED = True
