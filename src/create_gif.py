import glob
import os
import shutil
import sys
import tempfile
from typing import List, Optional, Tuple

from PIL import Image, UnidentifiedImageError
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QMovie, QPixmap
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QDoubleSpinBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QFrame,
    QListWidget,
    QListWidgetItem,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QStatusBar,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)


# GUIから反映されるGIF生成パラメータ
GIF_SETTINGS = {
    "duration": 100,
    "size": None,  # (width, height)
}


def _resample_filter():
    """Pillowのバージョン差を吸収して最適なリサンプリングフィルタを返す。"""
    return Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS


def create_gif(in_dir, out_filename):
    """指定フォルダ内の画像を連結してGIFを生成する。"""
    path_list = sorted(glob.glob(os.path.join(*[in_dir, "*"])))
    imgs = []

    for path in path_list:
        if not os.path.isfile(path):
            continue
        try:
            with Image.open(path) as img:
                frame = img.convert("RGBA")
                target_size: Optional[Tuple[int, int]] = GIF_SETTINGS.get("size")
                if target_size:
                    frame = frame.resize(target_size, _resample_filter())
                imgs.append(frame)
        except (UnidentifiedImageError, OSError):
            continue

    if not imgs:
        raise ValueError("No valid image files were found in the source directory.")

    duration = GIF_SETTINGS.get("duration", 100)
    imgs[0].save(
        out_filename,
        save_all=True,
        append_images=imgs[1:],
        optimize=False,
        duration=duration,
        loop=0,
    )


class FileDropWidget(QLabel):
    """ファイルをドラッグ＆ドロップで受け付けるラベルウィジェット。"""

    def __init__(self, callback):
        """ドロップ時に利用するコールバックを登録する。"""
        super().__init__("Drop image files here")
        self.setObjectName("DropLabel")
        self.setAlignment(Qt.AlignCenter)
        self.setAcceptDrops(True)
        self.callback = callback

    def dragEnterEvent(self, event):
        """ドラッグされたデータがURLなら受け入れる。"""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        """ドロップされたファイルパスをコールバックへ渡す。"""
        if not event.mimeData().hasUrls():
            event.ignore()
            return

        paths = [url.toLocalFile() for url in event.mimeData().urls()]
        self.callback(paths)
        event.acceptProposedAction()


class ImagePreviewLabel(QLabel):
    def __init__(self, placeholder: str = "Image preview"):
        """プレビュー表示用ラベルを初期化する。"""
        super().__init__(placeholder)
        self.setObjectName("FilePreviewLabel")
        self.setAlignment(Qt.AlignCenter)
        self._original_pixmap: Optional[QPixmap] = None
        self._image_size: Optional[Tuple[int, int]] = None
        self.setMinimumSize(240, 240)

    def set_image(self, path: Optional[str]):
        """パスで指定された画像を読み込みプレビュー表示する。"""
        if path and os.path.exists(path):
            pixmap = QPixmap(path)
            if pixmap.isNull():
                self.clear_image("Unable to load image.")
                return
            self._original_pixmap = pixmap
            self._image_size = (pixmap.width(), pixmap.height())
            self._apply_scaled_pixmap()
        else:
            self.clear_image("No preview")

    def clear_image(self, message: str = "No preview"):
        """プレビューを初期化してメッセージを表示する。"""
        self._original_pixmap = None
        self._image_size = None
        self.setPixmap(QPixmap())
        self.setText(message)

    def resizeEvent(self, event):
        """リサイズ時に表示中の画像サイズを合わせる。"""
        super().resizeEvent(event)
        if self._original_pixmap:
            self._apply_scaled_pixmap()

    def _apply_scaled_pixmap(self):
        """保持している画像をラベルサイズに収まるよう拡大縮小する。"""
        if not self._original_pixmap:
            return
        target_width = max(1, self.width())
        target_height = max(1, self.height())
        scaled = self._original_pixmap.scaled(
            target_width,
            target_height,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self.setPixmap(scaled)
        self.setText("")

    def original_size(self) -> Optional[Tuple[int, int]]:
        """元画像のピクセルサイズを返す。"""
        return self._image_size


class GifCreatorWindow(QMainWindow):
    """GIF作成UIを提供するメインウィンドウ。"""

    def __init__(self):
        """ウィンドウ全体の初期設定とウィジェット構築を行う。"""
        super().__init__()
        self.setWindowTitle("GIF Creator")
        self.resize(720, 520)

        self.drop_label = FileDropWidget(self.handle_dropped_files)
        self.drop_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.drop_label.setMaximumHeight(160)
        self.file_preview_label = ImagePreviewLabel("Drop files to preview")
        self.file_preview_label.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding
        )
        self.preview_slider = QSlider(Qt.Horizontal)
        self.preview_slider.setMinimum(0)
        self.preview_slider.setMaximum(0)
        self.preview_slider.setEnabled(False)
        self.preview_slider.valueChanged.connect(self.on_preview_slider_changed)
        # 入力ファイルリストの設定
        self.file_list = QListWidget()
        self.file_list.setAlternatingRowColors(False)
        self.file_list.setSelectionMode(QListWidget.ExtendedSelection)
        self.file_list.setMinimumHeight(320)
        self.file_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.file_list.itemSelectionChanged.connect(self.update_file_preview)

        self._updating_size_fields = False
        self._syncing_slider = False

        # リスト操作用ボタン群の生成
        remove_button = QPushButton("Remove Selected")
        remove_button.clicked.connect(self.remove_selected_files)

        move_up_button = QPushButton("Move Up")
        move_up_button.clicked.connect(self.move_selection_up)

        move_down_button = QPushButton("Move Down")
        move_down_button.clicked.connect(self.move_selection_down)

        list_buttons = QVBoxLayout()
        list_buttons.addWidget(remove_button)
        list_buttons.addWidget(move_up_button)
        list_buttons.addWidget(move_down_button)
        clear_button = QPushButton("Clear All")
        clear_button.clicked.connect(self.clear_file_list)
        list_buttons.addWidget(clear_button)
        list_buttons.addStretch()

        # ファイルリストと操作ボタンの配置
        list_layout = QHBoxLayout()
        list_layout.addWidget(self.file_list, 1)
        list_layout.addLayout(list_buttons)
        list_layout.setStretch(0, 1)
        list_layout.setStretch(1, 0)

        list_column_layout = QVBoxLayout()
        list_column_layout.addWidget(QLabel("Selected Files"))
        list_column_layout.addLayout(list_layout)
        list_column_layout.setStretch(0, 0)
        list_column_layout.setStretch(1, 1)

        # プレビューとリストを左右に並べる
        preview_column_layout = QVBoxLayout()
        preview_column_layout.addWidget(self.file_preview_label, 1)
        preview_column_layout.addWidget(self.preview_slider)
        preview_column_layout.setStretch(0, 1)
        preview_column_layout.setStretch(1, 0)

        files_layout = QHBoxLayout()
        files_layout.addLayout(preview_column_layout, 1)
        files_layout.addLayout(list_column_layout, 1)
        files_layout.setStretch(0, 1)
        files_layout.setStretch(1, 1)

        drop_layout = QVBoxLayout()
        drop_layout.addWidget(self.drop_label)
        drop_layout.addLayout(files_layout)
        drop_layout.setStretch(0, 0)
        drop_layout.setStretch(1, 1)
        drop_box = QGroupBox("Input Files")
        drop_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        drop_box.setLayout(drop_layout)

        self.out_file_edit = QLineEdit()
        self.out_file_edit.setPlaceholderText(
            "Output GIF path (e.g. /path/to/output.gif)"
        )
        browse_out_button = QPushButton("Browse...")
        browse_out_button.clicked.connect(self.select_output_file)

        out_layout = QHBoxLayout()
        out_layout.addWidget(self.out_file_edit, 1)
        out_layout.addWidget(browse_out_button)
        out_box = QGroupBox("Output")
        out_box.setLayout(out_layout)

        self.fps_input = QDoubleSpinBox()
        self.fps_input.setDecimals(2)
        self.fps_input.setRange(0.5, 120.0)
        self.fps_input.setSingleStep(0.5)
        self.fps_input.setValue(round(self.ms_to_fps(GIF_SETTINGS["duration"]), 2))

        fps_layout = QHBoxLayout()
        fps_layout.addWidget(QLabel("Frame Rate (fps)"))
        fps_layout.addWidget(self.fps_input)
        fps_box = QGroupBox("Speed")
        fps_box.setLayout(fps_layout)

        self.resize_checkbox = QCheckBox("Resize output")
        self.resize_checkbox.stateChanged.connect(self.toggle_resize_inputs)

        self.width_spin = QSpinBox()
        self.width_spin.setRange(16, 4096)
        self.width_spin.setValue(512)
        self.width_spin.setEnabled(False)
        self.width_spin.valueChanged.connect(self.on_width_changed)

        self.height_spin = QSpinBox()
        self.height_spin.setRange(16, 4096)
        self.height_spin.setValue(512)
        self.height_spin.setEnabled(False)
        self.height_spin.valueChanged.connect(self.on_height_changed)

        self.aspect_ratio_checkbox = QCheckBox("Keep aspect ratio")
        self.aspect_ratio_checkbox.setEnabled(False)
        self.aspect_ratio_checkbox.stateChanged.connect(self.on_aspect_ratio_changed)

        size_toggle_layout = QHBoxLayout()
        size_toggle_layout.addWidget(self.resize_checkbox)
        size_toggle_layout.addStretch()

        size_fields_layout = QHBoxLayout()
        size_fields_layout.addWidget(QLabel("Width"))
        size_fields_layout.addWidget(self.width_spin)
        size_fields_layout.addSpacing(12)
        size_fields_layout.addWidget(QLabel("Height"))
        size_fields_layout.addWidget(self.height_spin)
        size_fields_layout.addStretch()

        ratio_layout = QHBoxLayout()
        ratio_layout.addWidget(self.aspect_ratio_checkbox)
        ratio_layout.addStretch()

        size_container_layout = QVBoxLayout()
        size_container_layout.addLayout(size_toggle_layout)
        size_container_layout.addLayout(size_fields_layout)
        size_container_layout.addLayout(ratio_layout)

        size_box = QGroupBox("Resize")
        size_box.setLayout(size_container_layout)

        self.preview_label = QLabel("GIF preview will appear here")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumSize(320, 240)
        self.preview_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.preview_scroll = QScrollArea()
        self.preview_scroll.setWidgetResizable(False)
        self.preview_scroll.setAlignment(Qt.AlignCenter)
        self.preview_scroll.setWidget(self.preview_label)
        self.preview_movie: Optional[QMovie] = None

        generate_button = QPushButton("Create GIF")
        generate_button.clicked.connect(self.generate_gif)

        # 設定タブ全体のレイアウト
        settings_layout = QVBoxLayout()
        settings_layout.addWidget(drop_box, 2)
        settings_layout.addWidget(out_box)
        settings_layout.addWidget(fps_box)
        settings_layout.addWidget(size_box)
        settings_layout.addWidget(generate_button, alignment=Qt.AlignRight)
        settings_layout.setStretch(0, 1)
        settings_layout.setStretch(1, 0)
        settings_layout.setStretch(2, 0)
        settings_layout.setStretch(3, 0)
        settings_layout.setStretch(4, 0)

        settings_container = QWidget()
        settings_container.setLayout(settings_layout)

        settings_scroll = QScrollArea()
        settings_scroll.setWidgetResizable(True)
        settings_scroll.setWidget(settings_container)
        settings_scroll.setFrameShape(QFrame.NoFrame)

        settings_tab_layout = QVBoxLayout()
        settings_tab_layout.addWidget(settings_scroll)
        settings_tab_layout.setContentsMargins(0, 0, 0, 0)

        settings_tab = QWidget()
        settings_tab.setLayout(settings_tab_layout)

        preview_layout = QVBoxLayout()
        preview_layout.addWidget(self.preview_scroll, 1)
        preview_layout.setStretch(0, 1)
        preview_tab = QWidget()
        preview_tab.setLayout(preview_layout)

        self.tabs = QTabWidget()
        self.tabs.addTab(settings_tab, "Settings")
        self.tabs.addTab(preview_tab, "Preview")

        main_layout = QVBoxLayout()
        main_layout.addWidget(self.tabs)

        central_widget = QWidget()
        central_widget.setLayout(main_layout)
        self.setCentralWidget(central_widget)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        self.apply_dark_theme()

    def apply_dark_theme(self):
        """ウィンドウ全体にダークテーマのスタイルを適用する。"""
        palette = """
        QWidget {
            background-color: #1E1E1E;
            color: #E0E0E0;
            font-family: 'Helvetica Neue', Arial, sans-serif;
        }
        QGroupBox {
            border: 1px solid #3C3C3C;
            border-radius: 6px;
            margin-top: 12px;
            padding: 12px;
            font-weight: bold;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            padding-left: 8px;
        }
        QPushButton {
            background-color: #3A3D41;
            border: 1px solid #3C3C3C;
            border-radius: 4px;
            padding: 6px 12px;
        }
        QPushButton:hover {
            background-color: #4C4F53;
        }
        QPushButton:pressed {
            background-color: #2E3134;
        }
        QLineEdit, QDoubleSpinBox, QSpinBox, QListWidget {
            background-color: #252526;
            border: 1px solid #3C3C3C;
            border-radius: 4px;
            padding: 4px;
            selection-background-color: #094771;
            selection-color: #FFFFFF;
        }
        QLabel#DropLabel {
            border: 2px dashed #3C3C3C;
            border-radius: 8px;
            background-color: #252526;
            min-height: 120px;
        }
        QLabel#FilePreviewLabel {
            border: 1px solid #3C3C3C;
            border-radius: 8px;
            background-color: #252526;
            padding: 8px;
        }
        QTabWidget::pane {
            border: 1px solid #3C3C3C;
            border-radius: 6px;
            padding: 6px;
        }
        QTabBar::tab {
            background-color: #2D2D30;
            border: 1px solid #3C3C3C;
            border-bottom: none;
            padding: 6px 12px;
            min-width: 80px;
        }
        QTabBar::tab:selected {
            background-color: #1E1E1E;
        }
        QTabBar::tab:hover {
            background-color: #3A3D41;
        }
        """
        self.setStyleSheet(palette)

    def select_output_file(self):
        """出力先のGIFファイルをダイアログから選択する。"""
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Select output GIF file",
            self.out_file_edit.text() or "output.gif",
            "GIF Files (*.gif)",
        )
        if filename:
            if not filename.lower().endswith(".gif"):
                filename += ".gif"
            self.out_file_edit.setText(filename)

    def toggle_resize_inputs(self, state: int):
        """リサイズ関連の入力欄とオプションの有効状態を更新する。"""
        enabled = state == Qt.Checked
        self.width_spin.setEnabled(enabled)
        self.height_spin.setEnabled(enabled)
        self.aspect_ratio_checkbox.setEnabled(enabled)
        if not enabled:
            self.aspect_ratio_checkbox.setChecked(False)

    def handle_dropped_files(self, paths: List[str]):
        """ドロップされたファイル群を検査してリストへ登録する。"""
        filtered = []
        existing_counts = {}
        for i in range(self.file_list.count()):
            data = self.file_list.item(i).data(Qt.UserRole)
            if data:
                existing_counts[data] = existing_counts.get(data, 0) + 1

        for path in paths:
            if not os.path.isfile(path):
                continue
            extension = os.path.splitext(path)[1].lower()
            if extension in {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tiff", ".webp"}:
                filtered.append(path)

        if not filtered:
            QMessageBox.information(
                self, "Info", "No supported image files were dropped."
            )
            return

        for path in filtered:
            count = existing_counts.get(path, 0) + 1
            existing_counts[path] = count
            display_name = os.path.basename(path)
            if count > 1:
                display_name = f"{display_name} ({count})"
            item = QListWidgetItem(display_name)
            item.setToolTip(path)
            item.setData(Qt.UserRole, path)
            self.file_list.addItem(item)

        self.refresh_preview_slider()

        if not self.file_list.selectedItems() and self.file_list.count():
            self.file_list.setCurrentRow(0)
        else:
            self.update_file_preview()

        if not self.out_file_edit.text():
            directory = os.path.dirname(filtered[0])
            self.out_file_edit.setText(os.path.join(directory, "output.gif"))

    def clear_file_list(self):
        """リストを空にしてプレビューとスライダーを初期状態に戻す。"""
        self.file_list.clear()
        self.file_preview_label.clear_image("Drop files to preview")
        self.refresh_preview_slider()

    def remove_selected_files(self):
        """選択中の項目を削除し後続のプレビュー更新を行う。"""
        rows = self.get_selected_rows()
        if not rows:
            return
        for row in reversed(rows):
            self.file_list.takeItem(row)
        if self.file_list.count():
            next_row = min(rows[0], self.file_list.count() - 1)
            self.file_list.setCurrentRow(next_row)
        else:
            self.file_preview_label.clear_image("Drop files to preview")
        self.refresh_preview_slider()

    def get_file_paths(self) -> List[str]:
        return [
            self.file_list.item(i).data(Qt.UserRole)
            for i in range(self.file_list.count())
            if self.file_list.item(i).data(Qt.UserRole)
        ]

    def get_selected_rows(self) -> List[int]:
        """選択されている項目のインデックスを昇順で返す。"""
        return sorted(
            {self.file_list.row(item) for item in self.file_list.selectedItems()}
        )

    def move_selection_up(self):
        """選択した連続ブロックをリスト内で一段上へ移動する。"""
        rows = self.get_selected_rows()
        if not rows or rows[0] == 0:
            return

        groups = self._group_rows(rows)
        if groups[0][0] == 0:
            return

        items = self._snapshot_items()

        for start, end in groups:
            above = items[start - 1]
            block = items[start : end + 1]
            items[start - 1 : end + 1] = block + [above]

        self._rebuild_file_list(items)

    def move_selection_down(self):
        """選択した連続ブロックをリスト内で一段下へ移動する。"""
        rows = self.get_selected_rows()
        if not rows:
            return

        last_index = self.file_list.count() - 1
        if last_index < 0 or rows[-1] == last_index:
            return

        groups = self._group_rows(rows)
        if groups[-1][1] == last_index:
            return

        items = self._snapshot_items()

        for start, end in reversed(groups):
            below = items[end + 1]
            block = items[start : end + 1]
            items[start : end + 2] = [below] + block

        self._rebuild_file_list(items)

    def _rebuild_file_list(self, items: List[dict]):
        """与えられた順序でリスト項目を再生成し選択状態も復元する。"""
        self.file_list.clear()
        for entry in items:
            item = QListWidgetItem(entry["text"])
            item.setToolTip(entry["tooltip"])
            item.setData(Qt.UserRole, entry["data"])
            self.file_list.addItem(item)
            if entry["selected"]:
                item.setSelected(True)
        if not self.file_list.selectedItems() and self.file_list.count():
            self.file_list.setCurrentRow(0)
        else:
            self.update_file_preview()
        self.refresh_preview_slider()

    def update_file_preview(self):
        selected = self.file_list.selectedItems()
        if selected:
            path = selected[0].data(Qt.UserRole)
            self.file_preview_label.set_image(path)
            if (
                self.resize_checkbox.isChecked()
                and self.aspect_ratio_checkbox.isChecked()
            ):
                self._apply_aspect_ratio_from_width()
            index = self.file_list.row(selected[0])
            self._set_preview_slider_value(index)
        elif self.file_list.count():
            item = self.file_list.item(0)
            self.file_list.setCurrentItem(item)
            return
        else:
            self.file_preview_label.clear_image("Drop files to preview")
            self.refresh_preview_slider()

    def _snapshot_items(self) -> List[dict]:
        items = []
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            items.append(
                {
                    "text": item.text(),
                    "tooltip": item.toolTip(),
                    "data": item.data(Qt.UserRole),
                    "selected": item.isSelected(),
                }
            )
        return items

    @staticmethod
    def _group_rows(rows: List[int]) -> List[Tuple[int, int]]:
        if not rows:
            return []
        groups: List[Tuple[int, int]] = []
        start = rows[0]
        prev = rows[0]
        for index in rows[1:]:
            if index == prev + 1:
                prev = index
                continue
            groups.append((start, prev))
            start = index
            prev = index
        groups.append((start, prev))
        return groups

    @staticmethod
    def ms_to_fps(value: int) -> float:
        """ミリ秒単位のフレーム時間からFPSを計算する。"""
        return 1000.0 / value if value else 0.0

    def on_width_changed(self, value: int):
        """幅入力変更に合わせて高さを再計算する。"""
        if self._updating_size_fields:
            return
        if not (
            self.resize_checkbox.isChecked() and self.aspect_ratio_checkbox.isChecked()
        ):
            return
        self._apply_aspect_ratio_from_width(value)

    def on_height_changed(self, value: int):
        """高さ入力変更に合わせて幅を再計算する。"""
        if self._updating_size_fields:
            return
        if not (
            self.resize_checkbox.isChecked() and self.aspect_ratio_checkbox.isChecked()
        ):
            return
        self._apply_aspect_ratio_from_height(value)

    def on_aspect_ratio_changed(self, state: int):
        """アスペクト比維持チェック変更時に現在値を更新する。"""
        if state == Qt.Checked and self.resize_checkbox.isChecked():
            self._apply_aspect_ratio_from_width()

    def _apply_aspect_ratio_from_width(self, width: Optional[int] = None):
        """指定された幅に合わせて高さを導出する。"""
        size = self._get_current_image_size()
        if not size or size[0] == 0:
            return
        if width is None:
            width = self.width_spin.value()
        new_height = int(round(width * size[1] / size[0]))
        new_height = max(
            self.height_spin.minimum(), min(self.height_spin.maximum(), new_height)
        )
        self._updating_size_fields = True
        try:
            self.height_spin.setValue(new_height)
        finally:
            self._updating_size_fields = False

    def _apply_aspect_ratio_from_height(self, height: Optional[int] = None):
        """指定された高さに合わせて幅を導出する。"""
        size = self._get_current_image_size()
        if not size or size[1] == 0:
            return
        if height is None:
            height = self.height_spin.value()
        new_width = int(round(height * size[0] / size[1]))
        new_width = max(
            self.width_spin.minimum(), min(self.width_spin.maximum(), new_width)
        )
        self._updating_size_fields = True
        try:
            self.width_spin.setValue(new_width)
        finally:
            self._updating_size_fields = False

    def _get_current_image_size(self) -> Optional[Tuple[int, int]]:
        """現在の選択画像または先頭画像のサイズを取得する。"""
        size = self.file_preview_label.original_size()
        if size and size[0] > 0 and size[1] > 0:
            return size

        selected = self.file_list.selectedItems()
        path = None
        if selected:
            path = selected[0].data(Qt.UserRole)
        elif self.file_list.count():
            path = self.file_list.item(0).data(Qt.UserRole)

        if path and os.path.exists(path):
            try:
                with Image.open(path) as img:
                    return img.size
            except Exception:
                return None
        return None

    def refresh_preview_slider(self):
        """スライダーの範囲と値をリスト内容に合わせて調整する。"""
        count = self.file_list.count()
        self.preview_slider.blockSignals(True)
        try:
            if count <= 0:
                self._syncing_slider = True
                try:
                    self.preview_slider.setRange(0, 0)
                    self.preview_slider.setValue(0)
                finally:
                    self._syncing_slider = False
                self.preview_slider.setEnabled(False)
                return

            current = self.file_list.currentRow()
            if current < 0:
                current = 0
            current = min(current, count - 1)

            self._syncing_slider = True
            try:
                self.preview_slider.setRange(0, count - 1)
                self.preview_slider.setSingleStep(1)
                self.preview_slider.setPageStep(max(1, min(10, count)))
                self.preview_slider.setValue(current)
            finally:
                self._syncing_slider = False

            self.preview_slider.setEnabled(count > 1)
        finally:
            self.preview_slider.blockSignals(False)

    def _set_preview_slider_value(self, index: int):
        """スライダーの値を同期済み状態で更新する。"""
        if index < 0:
            return
        if (
            self.preview_slider.maximum() < index
            or self.preview_slider.minimum() > index
        ):
            self.refresh_preview_slider()
        self._syncing_slider = True
        try:
            self.preview_slider.blockSignals(True)
            self.preview_slider.setValue(index)
        finally:
            self.preview_slider.blockSignals(False)
            self._syncing_slider = False

    def on_preview_slider_changed(self, value: int):
        """スライダー操作で選択中の項目を切り替える。"""
        if self._syncing_slider:
            return
        if not (0 <= value < self.file_list.count()):
            return
        if self.file_list.currentRow() == value:
            return
        self._syncing_slider = True
        try:
            self.file_list.setCurrentRow(value)
        finally:
            self._syncing_slider = False

    def generate_gif(self):
        """画面設定に基づいてGIFを書き出す。"""
        out_file = self.out_file_edit.text().strip()

        paths = self.get_file_paths()
        if not paths:
            QMessageBox.warning(self, "Warning", "Please drop at least one image file.")
            return

        if not out_file:
            directory = os.path.dirname(paths[0]) or os.getcwd()
            out_file = os.path.join(directory, "output.gif")
            self.out_file_edit.setText(out_file)

        target_dir = os.path.dirname(out_file)
        if target_dir:
            os.makedirs(target_dir, exist_ok=True)

        fps = self.fps_input.value()
        if fps <= 0:
            QMessageBox.warning(self, "Warning", "FPS must be greater than 0.")
            return

        GIF_SETTINGS["duration"] = max(1, int(round(1000.0 / fps)))
        if self.resize_checkbox.isChecked():
            GIF_SETTINGS["size"] = (self.width_spin.value(), self.height_spin.value())
        else:
            GIF_SETTINGS["size"] = None

        # 元画像を一時ディレクトリにコピーして指定関数に渡す
        with tempfile.TemporaryDirectory() as temp_dir:
            for index, src in enumerate(paths):
                _, ext = os.path.splitext(src)
                dst = os.path.join(temp_dir, f"{index:04d}{ext}")
                shutil.copy2(src, dst)

            try:
                create_gif(temp_dir, out_file)
            except Exception as exc:
                QMessageBox.critical(self, "Error", str(exc))
                return

        self.status_bar.showMessage(f"GIF created: {out_file}", 5000)
        self.load_preview(out_file)
        self.tabs.setCurrentIndex(1)

    def load_preview(self, gif_path: str):
        """生成したGIFを読み込んでプレビュータブに表示する。"""
        if self.preview_movie:
            self.preview_movie.stop()
            self.preview_movie.deleteLater()
            self.preview_movie = None

        if not os.path.exists(gif_path):
            QMessageBox.warning(self, "Preview", "Generated GIF not found.")
            self.preview_label.setText("GIF preview will appear here")
            self.preview_label.adjustSize()
            self.preview_label.setMovie(None)
            return

        movie = QMovie(gif_path)
        if movie.isValid():
            self.preview_movie = movie
            self.preview_label.setMovie(movie)
            movie.jumpToFrame(0)
            self.preview_label.adjustSize()
            movie.start()
        else:
            self.preview_label.setText("Unable to load GIF.")
            self.preview_label.adjustSize()


def main():
    """アプリケーションを開始するエントリーポイント。"""
    app = QApplication(sys.argv)
    window = GifCreatorWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
