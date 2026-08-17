# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Ryo Horiike / GISPHN

from __future__ import annotations

import json
from pathlib import Path

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qgis.core import QgsSettings

from .constants import PREFECTURES, SETTINGS_PREFIX, STAT_TABLES
from .processor import BuildOptions, DataPackProcessor
from .qgis_io import CancelledError


def _qt_enum_member(nested_name: str, member_name: str):
    """Return a scoped Qt enum member, with a dynamic Qt5 fallback."""
    nested = getattr(Qt, nested_name, None)
    if nested is not None and hasattr(nested, member_name):
        return getattr(nested, member_name)
    return getattr(Qt, member_name)


def _checked():
    return _qt_enum_member("CheckState", "Checked")


def _unchecked():
    return _qt_enum_member("CheckState", "Unchecked")


def _item_user_checkable():
    return _qt_enum_member("ItemFlag", "ItemIsUserCheckable")


def _item_enabled():
    return _qt_enum_member("ItemFlag", "ItemIsEnabled")


def _dialog_exec(dialog):
    method = getattr(dialog, "exec", None)
    if method is None:
        method = getattr(dialog, "exec_")
    return method()


def _accepted_value():
    enum = getattr(QDialog, "DialogCode", None)
    if enum is not None and hasattr(enum, "Accepted"):
        return getattr(enum, "Accepted")
    return getattr(QDialog, "Accepted")


def _button_role(name: str):
    try:
        return getattr(QMessageBox.ButtonRole, name)
    except AttributeError:
        return getattr(QMessageBox, name)


def _user_role():
    enum = getattr(Qt, "ItemDataRole", Qt)
    return getattr(enum, "UserRole")


def _no_selection():
    enum = getattr(QAbstractItemView, "SelectionMode", QAbstractItemView)
    return getattr(enum, "NoSelection")


def _dialog_button(name: str):
    enum = getattr(QDialogButtonBox, "StandardButton", QDialogButtonBox)
    return getattr(enum, name)


def _message_icon(name: str):
    enum = getattr(QMessageBox, "Icon", QMessageBox)
    return getattr(enum, name)


class MunicipalitySelectionDialog(QDialog):
    def __init__(self, municipalities, selected_codes=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("自治体を選択")
        self.resize(520, 650)
        self.municipalities = sorted(municipalities, key=lambda m: m.code)
        selected_codes = set(selected_codes or [])

        layout = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setPlaceholderText("自治体名または行政区域コードで検索")
        layout.addWidget(self.search)

        controls = QHBoxLayout()
        for text, handler in (
            ("すべて選択", self.select_all_visible),
            ("すべて解除", self.clear_all),
            ("選択を反転", self.invert_visible),
        ):
            b = QPushButton(text)
            b.clicked.connect(handler)
            controls.addWidget(b)
        controls.addStretch(1)
        layout.addLayout(controls)

        self.list = QListWidget()
        self.list.setSelectionMode(_no_selection())
        for muni in self.municipalities:
            item = QListWidgetItem(f"{muni.code}  {muni.name}")
            item.setData(_user_role(), muni.code)
            item.setFlags(item.flags() | _item_user_checkable())
            item.setCheckState(_checked() if muni.code in selected_codes else _unchecked())
            self.list.addItem(item)
        layout.addWidget(self.list)

        buttons = QDialogButtonBox(
            _dialog_button("Ok") | _dialog_button("Cancel")
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.search.textChanged.connect(self.filter_items)

    def filter_items(self, text):
        needle = text.strip().lower()
        for i in range(self.list.count()):
            item = self.list.item(i)
            item.setHidden(bool(needle) and needle not in item.text().lower())

    def select_all_visible(self):
        for i in range(self.list.count()):
            item = self.list.item(i)
            if not item.isHidden():
                item.setCheckState(_checked())

    def clear_all(self):
        for i in range(self.list.count()):
            self.list.item(i).setCheckState(_unchecked())

    def invert_visible(self):
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item.isHidden():
                continue
            item.setCheckState(_unchecked() if item.checkState() == _checked() else _checked())

    def selected_codes(self):
        result = set()
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item.checkState() == _checked():
                result.add(str(item.data(_user_role())))
        return result


class AdditionalDataDialog(QDialog):
    def __init__(self, headers, preset_codes, selected_codes, preset_enabled=True, parent=None):
        super().__init__(parent)
        self.setWindowTitle("追加データを選択")
        self.resize(850, 720)
        self.preset_codes = set(preset_codes)
        self.selected_codes_initial = set(selected_codes)
        self.preset_enabled = preset_enabled

        layout = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setPlaceholderText("日本語項目名または項目コードで検索")
        layout.addWidget(self.search)

        controls = QHBoxLayout()
        b_all = QPushButton("表示項目をすべて選択")
        b_clear = QPushButton("追加選択をすべて解除")
        b_all.clicked.connect(self.select_all_visible)
        b_clear.clicked.connect(self.clear_additional)
        controls.addWidget(b_all)
        controls.addWidget(b_clear)
        controls.addStretch(1)
        layout.addLayout(controls)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["項目名", "項目コード", "状態"])
        self.tree.setColumnWidth(0, 500)
        self.tree.setColumnWidth(1, 130)
        layout.addWidget(self.tree)

        table_names = dict(STAT_TABLES)
        for stats_id, _table_name in STAT_TABLES:
            root = QTreeWidgetItem([table_names[stats_id], stats_id, ""])
            self.tree.addTopLevelItem(root)
            header = headers[stats_id]
            for col in header.columns():
                preset = col.code in self.preset_codes
                status = "G-CHAM既定" if preset else "追加可能"
                item = QTreeWidgetItem([col.label, col.code, status])
                item.setData(0, _user_role(), col.code)
                item.setFlags(item.flags() | _item_user_checkable())
                if preset and preset_enabled:
                    item.setCheckState(0, _checked())
                    item.setFlags(item.flags() & ~_item_enabled())
                else:
                    item.setCheckState(
                        0, _checked() if col.code in self.selected_codes_initial else _unchecked()
                    )
                root.addChild(item)
            root.setExpanded(False)

        buttons = QDialogButtonBox(
            _dialog_button("Ok") | _dialog_button("Cancel")
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.search.textChanged.connect(self.filter_items)

    def _iter_children(self):
        for i in range(self.tree.topLevelItemCount()):
            root = self.tree.topLevelItem(i)
            for j in range(root.childCount()):
                yield root, root.child(j)

    def filter_items(self, text):
        needle = text.strip().lower()
        for i in range(self.tree.topLevelItemCount()):
            root = self.tree.topLevelItem(i)
            any_visible = False
            for j in range(root.childCount()):
                item = root.child(j)
                match = not needle or needle in (item.text(0) + " " + item.text(1)).lower()
                item.setHidden(not match)
                any_visible = any_visible or match
            root.setHidden(not any_visible)
            if needle and any_visible:
                root.setExpanded(True)

    def select_all_visible(self):
        for _root, item in self._iter_children():
            if item.isHidden() or not (item.flags() & _item_enabled()):
                continue
            item.setCheckState(0, _checked())

    def clear_additional(self):
        for _root, item in self._iter_children():
            code = str(item.data(0, _user_role()))
            if self.preset_enabled and code in self.preset_codes:
                continue
            item.setCheckState(0, _unchecked())

    def selected_additional_codes(self):
        result = set()
        for _root, item in self._iter_children():
            code = str(item.data(0, _user_role()))
            if self.preset_enabled and code in self.preset_codes:
                continue
            if item.checkState(0) == _checked():
                result.add(code)
        return result


class GCHAMDataPackDialog(QDialog):
    def __init__(self, iface, plugin_dir: Path, parent=None):
        super().__init__(parent or iface.mainWindow())
        self.iface = iface
        self.plugin_dir = Path(plugin_dir)
        self.settings = QgsSettings()
        self._cancelled = False
        self._running = False
        self._selected_muni_codes: set[str] = set()
        self._municipalities_cache = None
        self._headers_cache = None
        self.additional_codes = self._load_additional_codes()
        self.preset_codes = {
            item["code"] for item in DataPackProcessor(self.plugin_dir).preset["fields"]
        }

        self.setWindowTitle("G-CHAM Data Pack Builder")
        self.resize(760, 720)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        form_group = QGroupBox("対象")
        form = QFormLayout(form_group)
        self.pref_combo = QComboBox()
        for code, name in PREFECTURES:
            self.pref_combo.addItem(f"{code}  {name}", (code, name))
        form.addRow("都道府県", self.pref_combo)

        muni_widget = QWidget()
        muni_layout = QVBoxLayout(muni_widget)
        muni_layout.setContentsMargins(0, 0, 0, 0)
        self.radio_all = QRadioButton("都道府県内のすべての自治体")
        self.radio_selected = QRadioButton("選択した自治体のみ")
        self.radio_all.setChecked(True)
        self.muni_button = QPushButton("自治体を選択...")
        self.muni_button.setEnabled(False)
        self.muni_summary = QLabel("すべての自治体")
        muni_layout.addWidget(self.radio_all)
        row = QHBoxLayout()
        row.addWidget(self.radio_selected)
        row.addWidget(self.muni_button)
        row.addWidget(self.muni_summary, 1)
        muni_layout.addLayout(row)
        form.addRow("自治体", muni_widget)
        layout.addWidget(form_group)

        data_group = QGroupBox("人口データ")
        data_layout = QVBoxLayout(data_group)
        self.preset_check = QCheckBox("G-CHAMデータパック用データ")
        self.preset_check.setChecked(True)
        data_layout.addWidget(self.preset_check)
        extra_row = QHBoxLayout()
        self.extra_button = QPushButton("追加データを選択...")
        self.extra_summary = QLabel()
        self.reset_extra_button = QPushButton("初期設定に戻す")
        extra_row.addWidget(self.extra_button)
        extra_row.addWidget(self.extra_summary, 1)
        extra_row.addWidget(self.reset_extra_button)
        data_layout.addLayout(extra_row)
        self._update_extra_summary()
        layout.addWidget(data_group)

        supplemental_group = QGroupBox("追加レイヤ")
        supplemental_layout = QVBoxLayout(supplemental_group)

        top_row = QHBoxLayout()
        self.facilities_check = QCheckBox("施設")
        self.transport_check = QCheckBox("交通")
        self.disaster_check = QCheckBox("災害")
        self.background_check = QCheckBox("背景地図")
        for checkbox in (self.facilities_check, self.transport_check, self.disaster_check, self.background_check):
            checkbox.setChecked(True)
            top_row.addWidget(checkbox)
        top_row.addStretch(1)
        supplemental_layout.addLayout(top_row)

        road_row = QHBoxLayout()
        road_row.addSpacing(24)
        self.roads_check = QCheckBox("道路（交通とは別選択・容量大）")
        self.roads_check.setChecked(False)
        self.roads_check.setToolTip("道路データは容量が大きいため、交通とは別に選択できます。初期状態ではオフです。")
        road_row.addWidget(self.roads_check)
        road_row.addStretch(1)
        supplemental_layout.addLayout(road_row)

        note = QLabel("※ 道路データは容量が大きいため、交通グループとは別に選択してください。初期状態ではオフです。")
        note.setWordWrap(True)
        supplemental_layout.addWidget(note)
        layout.addWidget(supplemental_group)

        output_group = QGroupBox("出力")
        output_form = QFormLayout(output_group)
        output_row = QHBoxLayout()
        self.output_edit = QLineEdit()
        self.output_button = QPushButton("参照...")
        output_row.addWidget(self.output_edit, 1)
        output_row.addWidget(self.output_button)
        output_form.addRow("出力フォルダ", output_row)
        self.reuse_check = QCheckBox("ダウンロード済みデータを再利用する")
        self.reuse_check.setChecked(True)
        output_form.addRow("", self.reuse_check)
        layout.addWidget(output_group)

        self.progress_label = QLabel("準備完了")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumBlockCount(1000)
        layout.addWidget(self.progress_label)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.log_box, 1)

        buttons = QHBoxLayout()
        self.create_button = QPushButton("データパックを作成")
        self.cancel_run_button = QPushButton("処理をキャンセル")
        self.cancel_run_button.setVisible(False)
        self.close_button = QPushButton("閉じる")
        buttons.addStretch(1)
        buttons.addWidget(self.create_button)
        buttons.addWidget(self.cancel_run_button)
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)

        self.radio_selected.toggled.connect(self._municipality_mode_changed)
        self.pref_combo.currentIndexChanged.connect(self._pref_changed)
        self.muni_button.clicked.connect(self._choose_municipalities)
        self.extra_button.clicked.connect(self._choose_additional_data)
        self.reset_extra_button.clicked.connect(self._reset_additional)
        self.output_button.clicked.connect(self._browse_output)
        self.create_button.clicked.connect(self._run_build)
        self.cancel_run_button.clicked.connect(self._request_cancel)
        self.close_button.clicked.connect(self.reject)

    def _settings_key(self, suffix):
        return f"{SETTINGS_PREFIX}/{suffix}"

    def _load_additional_codes(self):
        raw = self.settings.value(self._settings_key("additional_codes"), "[]")
        try:
            return set(json.loads(str(raw)))
        except Exception:
            return set()

    def _save_additional_codes(self):
        self.settings.setValue(
            self._settings_key("additional_codes"),
            json.dumps(sorted(self.additional_codes), ensure_ascii=False),
        )

    def _pref_data(self):
        return self.pref_combo.currentData()

    def _pref_changed(self):
        self._selected_muni_codes.clear()
        self._municipalities_cache = None
        self._headers_cache = None
        self.muni_summary.setText("未選択" if self.radio_selected.isChecked() else "すべての自治体")

    def _municipality_mode_changed(self, selected):
        self.muni_button.setEnabled(selected and not self._running)
        self.muni_summary.setText(
            f"{len(self._selected_muni_codes)}自治体を選択"
            if selected and self._selected_muni_codes
            else "未選択" if selected else "すべての自治体"
        )

    def _browse_output(self):
        path = QFileDialog.getExistingDirectory(self, "出力フォルダを選択", self.output_edit.text())
        if path:
            self.output_edit.setText(path)

    def _ensure_output_dir(self):
        text = self.output_edit.text().strip()
        if not text:
            self._browse_output()
            text = self.output_edit.text().strip()
        if not text:
            return None
        path = Path(text)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _processor(self):
        return DataPackProcessor(
            self.plugin_dir,
            log=self._log,
            progress=self._set_progress,
            is_cancelled=lambda: self._cancelled,
        )

    def _choose_municipalities(self):
        output = self._ensure_output_dir()
        if output is None:
            return
        code, _name = self._pref_data()
        try:
            self._set_progress(1, "自治体一覧を準備しています")
            municipalities = self._processor().prepare_municipalities(
                code, output, self.reuse_check.isChecked()
            )
            self._municipalities_cache = municipalities
            dialog = MunicipalitySelectionDialog(
                municipalities, self._selected_muni_codes, self
            )
            if _dialog_exec(dialog) == _accepted_value():
                self._selected_muni_codes = dialog.selected_codes()
                self.muni_summary.setText(f"{len(self._selected_muni_codes)}自治体を選択")
            self._set_progress(0, "準備完了")
        except Exception as exc:
            QMessageBox.critical(self, "自治体一覧の取得に失敗", str(exc))
            self._log(str(exc))

    def _choose_additional_data(self):
        output = self._ensure_output_dir()
        if output is None:
            return
        code, _name = self._pref_data()
        try:
            self._set_progress(1, "e-Stat項目一覧を準備しています")
            headers = self._processor().prepare_headers(code, output, self.reuse_check.isChecked())
            self._headers_cache = headers
            dialog = AdditionalDataDialog(
                headers,
                self.preset_codes,
                self.additional_codes,
                preset_enabled=self.preset_check.isChecked(),
                parent=self,
            )
            if _dialog_exec(dialog) == _accepted_value():
                self.additional_codes = dialog.selected_additional_codes()
                self._save_additional_codes()
                self._update_extra_summary()
            self._set_progress(0, "準備完了")
        except Exception as exc:
            QMessageBox.critical(self, "項目一覧の取得に失敗", str(exc))
            self._log(str(exc))

    def _reset_additional(self):
        self.additional_codes.clear()
        self._save_additional_codes()
        self._update_extra_summary()

    def _update_extra_summary(self):
        self.extra_summary.setText(f"追加選択: {len(self.additional_codes)}項目")

    def _log(self, message):
        self.log_box.appendPlainText(str(message))

    def _set_progress(self, pct, message):
        self.progress_bar.setValue(int(pct))
        self.progress_label.setText(str(message))

    def _request_cancel(self):
        self._cancelled = True
        self.progress_label.setText("キャンセル要求を受け付けました...")

    def _set_running(self, running):
        self._running = running
        for w in (
            self.pref_combo, self.radio_all, self.radio_selected, self.preset_check,
            self.extra_button, self.reset_extra_button, self.output_edit, self.output_button,
            self.reuse_check, self.facilities_check, self.transport_check,
            self.disaster_check, self.background_check, self.create_button, self.close_button,
        ):
            w.setEnabled(not running)
        self.muni_button.setEnabled(not running and self.radio_selected.isChecked())
        self.cancel_run_button.setVisible(running)

    def _confirm_existing(self, paths):
        msg = QMessageBox(self)
        msg.setWindowTitle("既存FGBファイル")
        msg.setIcon(_message_icon("Warning"))
        msg.setText(f"{len(paths)}個のFGBファイルが既に存在します。")
        msg.setInformativeText("既存ファイルの処理方法を選択してください。")
        overwrite = msg.addButton("すべて上書き", _button_role("AcceptRole"))
        skip = msg.addButton("既存ファイルをスキップ", _button_role("DestructiveRole"))
        msg.addButton("キャンセル", _button_role("RejectRole"))
        _dialog_exec(msg)
        clicked = msg.clickedButton()
        if clicked == overwrite:
            return "overwrite"
        if clicked == skip:
            return "skip"
        return "cancel"

    def _run_build(self):
        output = self._ensure_output_dir()
        if output is None:
            return
        if self.radio_selected.isChecked() and not self._selected_muni_codes:
            self._choose_municipalities()
            if not self._selected_muni_codes:
                return

        code, name = self._pref_data()
        options = BuildOptions(
            pref_code=code,
            pref_name=name,
            output_dir=output,
            all_municipalities=self.radio_all.isChecked(),
            selected_municipality_codes=set(self._selected_muni_codes),
            use_preset=self.preset_check.isChecked(),
            additional_codes=set(self.additional_codes),
            reuse_downloads=self.reuse_check.isChecked(),
            include_facilities=self.facilities_check.isChecked(),
            include_transport=self.transport_check.isChecked(),
            include_roads=self.roads_check.isChecked(),
            include_disaster=self.disaster_check.isChecked(),
            include_background=self.background_check.isChecked(),
        )
        self._cancelled = False
        self.log_box.clear()
        self._set_running(True)
        try:
            result = self._processor().build(options, self._confirm_existing)
            QMessageBox.information(
                self,
                "完了",
                f"G-CHAMデータパックを作成しました。\n\n出力先: {output}\n"
                f"自治体数: {len(result['municipalities'])}",
            )
        except CancelledError as exc:
            self._log(str(exc))
            self._set_progress(self.progress_bar.value(), "処理を中止しました")
        except Exception as exc:
            self._log(f"ERROR: {exc}")
            QMessageBox.critical(self, "G-CHAM Data Pack Builder", str(exc))
            self._set_progress(self.progress_bar.value(), "エラーで停止しました")
        finally:
            self._set_running(False)
