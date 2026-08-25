# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Ryo Horiike / GISPHN

from __future__ import annotations

from pathlib import Path

from qgis.core import QgsProject

from . import v113_layer_selection

_APPLIED = False
_POP_GROUP = "250mメッシュ人口"


def _is_population_layer(layer) -> bool:
    """Identify population layers created by the established population workflow."""
    if layer is None:
        return False
    name = str(layer.name())
    if "_250mメッシュ人口_2020国調" in name:
        return True
    try:
        source = str(layer.source()).split("|", 1)[0]
        filename = Path(source).name.lower()
    except Exception:
        return False
    return (
        filename.startswith("census2020_")
        and filename.endswith("_pop250m.fgb")
    )


def _population_layers_from_project():
    """Return existing project-owned population map layers in stable project order."""
    project = QgsProject.instance()
    result = []
    seen = set()

    # First keep the order already present in the population tree group.
    root = project.layerTreeRoot()
    group = root.findGroup(_POP_GROUP)
    if group is not None:
        for node in group.findLayers():
            layer = node.layer()
            if layer is None or layer.id() in seen:
                continue
            if _is_population_layer(layer):
                result.append((layer, node.itemVisibilityChecked()))
                seen.add(layer.id())

    # Self-repair: if the tree group was emptied by an earlier ordering bug,
    # recover the still project-owned census2020 population layers.
    for layer in project.mapLayers().values():
        if layer.id() in seen or not _is_population_layer(layer):
            continue
        result.append((layer, True))
        seen.add(layer.id())

    # Prefecture population first, municipality population(s) after it. The
    # established layer names/path generation are unchanged; this is tree-only.
    def sort_key(item):
        layer = item[0]
        source = str(layer.source()).split("|", 1)[0]
        filename = Path(source).name.lower()
        stem = filename.removeprefix("census2020_").removesuffix("_pop250m.fgb")
        code = stem.split("_", 1)[0]
        return (0 if len(code) == 2 else 1, code, layer.name())

    result.sort(key=sort_key)
    return result


def _target_index(root) -> int | None:
    """Return the requested population-group index without moving any map layer."""
    disaster = root.findGroup("災害")
    if disaster is not None and disaster.parent() is root:
        return root.children().index(disaster) + 1

    background = root.findGroup("背景地図")
    if background is not None and background.parent() is root:
        return root.children().index(background)

    return None


def _restore_population_group_position() -> None:
    """Recreate only layer-tree nodes, preserving project-owned population layers."""
    project = QgsProject.instance()
    root = project.layerTreeRoot()
    population_layers = _population_layers_from_project()
    if not population_layers:
        return

    old_group = root.findGroup(_POP_GROUP)
    old_checked = True
    old_expanded = True
    if old_group is not None:
        old_checked = old_group.itemVisibilityChecked()
        old_expanded = old_group.isExpanded()

    target_index = _target_index(root)
    if target_index is None:
        # No disaster/background anchor exists. Keep the established population
        # group in place, repairing missing layer nodes only when necessary.
        if old_group is None:
            old_group = root.addGroup(_POP_GROUP)
        existing_ids = {
            node.layerId()
            for node in old_group.findLayers()
            if node.layer() is not None
        }
        for layer, visible in population_layers:
            if layer.id() in existing_ids:
                continue
            node = old_group.addLayer(layer)
            node.setItemVisibilityChecked(visible)
        return

    # If already correctly positioned and complete, leave the original tree
    # untouched. This is the normal no-op path.
    if old_group is not None and old_group.parent() is root:
        children = root.children()
        current_index = children.index(old_group)
        existing_ids = {
            node.layerId()
            for node in old_group.findLayers()
            if node.layer() is not None
        }
        expected_ids = {layer.id() for layer, _visible in population_layers}
        if current_index == target_index and expected_ids.issubset(existing_ids):
            return

    # QgsMapLayer objects are owned by QgsProject independently of layer-tree
    # nodes. Delete/recreate only the tree group, then add references to the
    # same map layers. Population download, FGB creation and layer construction
    # are deliberately not reimplemented here.
    if old_group is not None and old_group.parent() is root:
        old_index = root.children().index(old_group)
        root.removeChildNode(old_group)
        if old_index < target_index:
            target_index -= 1

    target_index = max(0, min(target_index, len(root.children())))
    group = root.insertGroup(target_index, _POP_GROUP)
    group.setItemVisibilityChecked(old_checked)
    group.setExpanded(old_expanded)
    for layer, visible in population_layers:
        node = group.addLayer(layer)
        node.setItemVisibilityChecked(visible)


def _patch_incremental_group_position() -> None:
    original = v113_layer_selection._build_supplemental_only
    if getattr(original, "_gcham_v114_population_position", False):
        return

    def _build_supplemental_only(*args, **kwargs):
        results = original(*args, **kwargs)
        _restore_population_group_position()
        return results

    _build_supplemental_only._gcham_v114_population_position = True
    v113_layer_selection._build_supplemental_only = _build_supplemental_only


def apply_v114_population_group_position() -> None:
    global _APPLIED
    if _APPLIED:
        return
    _patch_incremental_group_position()
    _APPLIED = True
