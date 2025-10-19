import os
from typing import List, Optional

from PIL import Image, ImageSequence, UnidentifiedImageError
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QMovie, QPixmap, QImage
from PyQt5.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
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
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QGroupBox,
    QCheckBox,
    QSizePolicy,
)


def _resample_filter():
    """Pillowのリサンプリングフィルタをバージョン差なく取得する。"""

    return Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS


def pil_to_qpixmap(image: Image.Image) -> QPixmap:
    """Pillow画像をQPixmapへ変換する。"""

    if image.mode != "RGBA":
        image = image.convert("RGBA")
    width, height = image.size
    data = image.tobytes("raw", "RGBA")
    qimage = QImage(data, width, height, QImage.Format_RGBA8888).copy()
    return QPixmap.fromImage(qimage)


class GifDropLabel(QLabel):
    """GIFファイルをドラッグ＆ドロップで受け付けるラベル。"""

    def __init__(self, callback):
        """ドロップ時に呼び出すコールバックを登録する。"""

        super().__init__("Drop GIF file here")
        self.setObjectName("DropLabel")
        self.setAlignment(Qt.AlignCenter)
        self.setAcceptDrops(True)
        self.callback = callback

    def dragEnterEvent(self, event):
        """URLを含むドラッグを許可する。"""

        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        """GIFがドロップされたらパスをコールバックに渡す。"""

        if not event.mimeData().hasUrls():
            event.ignore()
            return

        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path and path.lower().endswith(".gif"):
                self.callback(path)
                event.acceptProposedAction()
                return

        QMessageBox.information(self, "Info", "Please drop a .gif file.")
        event.ignore()


class FramePreviewLabel(QLabel):
    """分解したフレームをプレビュー表示するラベル。"""

    def __init__(self):
        """プレビュー用の表示設定を行う。"""

        super().__init__("Frame preview will appear here")
        self.setObjectName("FramePreviewLabel")
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(240, 240)
        self._pixmap: Optional[QPixmap] = None

    def set_image(self, image: Optional[Image.Image]):
        """Pillow画像を受け取って表示する。"""

        if image is None:
            self.clear_preview()
            return
        self._pixmap = pil_to_qpixmap(image)
        self._apply_scaled_pixmap()

    def clear_preview(self, message: str = "Frame preview will appear here"):
        """プレビューを空にしてメッセージを表示する。"""

        self._pixmap = None
        self.setPixmap(QPixmap())
        self.setText(message)

    def resizeEvent(self, event):
        """リサイズ時にピクスマップを再調整する。"""

        super().resizeEvent(event)
        if self._pixmap:
            self._apply_scaled_pixmap()

    def _apply_scaled_pixmap(self):
        """保持中のピクスマップをビューサイズに合わせる。"""

        if not self._pixmap:
            return
        scaled = self._pixmap.scaled(
            self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        self.setPixmap(scaled)
        self.setText("")


class GifDecompositionWindow(QMainWindow):
    """GIFを分解して静止画として保存するウィンドウ。"""

    def __init__(self):
        """ウィジェット構築と初期状態の設定を行う。"""

        super().__init__()
        self.setWindowTitle("GIF Decomposition Tool")
        self.resize(900, 640)

        # GIF読み込み結果を管理する属性
        self.frames: List[Image.Image] = []
        self.gif_path: Optional[str] = None

        # ドロップ領域とプレビュー関連の構築
        self.drop_label = GifDropLabel(self.load_gif)
        self.frame_preview = FramePreviewLabel()
        self.frame_list = QListWidget()
        self.frame_list.setSelectionMode(QListWidget.SingleSelection)
        self.frame_list.itemSelectionChanged.connect(self.on_frame_selection_changed)

        # フレーム移動用スライダー
        self.frame_slider = QSlider(Qt.Horizontal)
        self.frame_slider.setMinimum(0)
        self.frame_slider.setMaximum(0)
        self.frame_slider.setEnabled(False)
        self.frame_slider.valueChanged.connect(self.on_slider_changed)
        self._syncing_slider = False

        self.frame_label = QLabel("Frame: - / -")

        # リサイズ設定
        self.resize_checkbox = QCheckBox("Resize output")
        self.resize_checkbox.stateChanged.connect(self.toggle_resize_inputs)
        self.aspect_ratio_checkbox = QCheckBox("Keep aspect ratio")
        self.aspect_ratio_checkbox.setEnabled(False)
        self.aspect_ratio_checkbox.stateChanged.connect(self.on_aspect_ratio_changed)

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

        # 保存先設定
        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("Output directory (e.g. /path/to/frames)")
        browse_button = QPushButton("Browse...")
        browse_button.clicked.connect(self.select_output_directory)

        # 分解実行ボタン
        decompose_button = QPushButton("Decomposition")
        decompose_button.clicked.connect(self.decompose_gif)
        decompose_button.setEnabled(False)
        self.decompose_button = decompose_button

        # 設定タブのレイアウト構築
        list_layout = QVBoxLayout()
        list_layout.addWidget(QLabel("Frames"))
        list_layout.addWidget(self.frame_list)

        preview_layout = QVBoxLayout()
        preview_layout.addWidget(self.frame_preview, 1)
        preview_layout.addWidget(self.frame_slider)
        preview_layout.addWidget(self.frame_label)

        viewer_layout = QHBoxLayout()
        viewer_layout.addLayout(preview_layout, 1)
        viewer_layout.addLayout(list_layout, 0)

        resize_toggle_layout = QHBoxLayout()
        resize_toggle_layout.addWidget(self.resize_checkbox)
        resize_toggle_layout.addStretch()

        resize_fields_layout = QHBoxLayout()
        resize_fields_layout.addWidget(QLabel("Width"))
        resize_fields_layout.addWidget(self.width_spin)
        resize_fields_layout.addSpacing(12)
        resize_fields_layout.addWidget(QLabel("Height"))
        resize_fields_layout.addWidget(self.height_spin)
        resize_fields_layout.addStretch()

        ratio_layout = QHBoxLayout()
        ratio_layout.addWidget(self.aspect_ratio_checkbox)
        ratio_layout.addStretch()

        resize_group_layout = QVBoxLayout()
        resize_group_layout.addLayout(resize_toggle_layout)
        resize_group_layout.addLayout(resize_fields_layout)
        resize_group_layout.addLayout(ratio_layout)

        resize_group = QGroupBox("Resize")
        resize_group.setLayout(resize_group_layout)

        output_layout = QHBoxLayout()
        output_layout.addWidget(self.output_edit, 1)
        output_layout.addWidget(browse_button)

        settings_inner_layout = QVBoxLayout()
        settings_inner_layout.addWidget(self.drop_label)
        settings_inner_layout.addLayout(viewer_layout, 1)
        settings_inner_layout.addWidget(resize_group)
        settings_inner_layout.addLayout(output_layout)
        settings_inner_layout.addWidget(decompose_button, alignment=Qt.AlignRight)

        settings_container = QWidget()
        settings_container.setLayout(settings_inner_layout)

        settings_scroll = QScrollArea()
        settings_scroll.setWidgetResizable(True)
        settings_scroll.setWidget(settings_container)
        settings_scroll.setFrameShape(QScrollArea.NoFrame)

        settings_tab_layout = QVBoxLayout()
        settings_tab_layout.addWidget(settings_scroll)
        settings_tab_layout.setContentsMargins(0, 0, 0, 0)

        settings_tab = QWidget()
        settings_tab.setLayout(settings_tab_layout)

        # プレビューダブの準備（タブは設定に留める）
        self.preview_movie_label = QLabel("GIF preview will appear here")
        self.preview_movie_label.setObjectName("PreviewLabel")
        self.preview_movie_label.setAlignment(Qt.AlignCenter)
        self.preview_movie_label.setMinimumSize(320, 240)
        self.preview_movie_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.preview_scroll = QScrollArea()
        self.preview_scroll.setWidgetResizable(False)
        self.preview_scroll.setAlignment(Qt.AlignCenter)
        self.preview_scroll.setWidget(self.preview_movie_label)
        self.preview_movie: Optional[QMovie] = None

        preview_tab_layout = QVBoxLayout()
        preview_tab_layout.addWidget(self.preview_scroll, 1)

        preview_tab = QWidget()
        preview_tab.setLayout(preview_tab_layout)

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
        """ウィンドウ全体へダークテーマを適用する。"""

        palette = """
        QWidget {
            background-color: #1E1E1E;
            color: #E0E0E0;
            font-family: 'Helvetica Neue', Arial, sans-serif;
        }
        QLabel#DropLabel {
            border: 2px dashed #3C3C3C;
            border-radius: 8px;
            background-color: #252526;
            min-height: 120px;
        }
        QLabel#FramePreviewLabel, QLabel#PreviewLabel {
            border: 1px solid #3C3C3C;
            border-radius: 8px;
            background-color: #252526;
            padding: 12px;
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
        QLineEdit, QSpinBox, QSlider {
            background-color: #252526;
            border: 1px solid #3C3C3C;
            border-radius: 4px;
            padding: 4px;
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
        QStatusBar {
            background-color: #1E1E1E;
        }
        """
        self.setStyleSheet(palette)

    def load_gif(self, path: str):
        """ドロップされたGIFを読み込みフレーム情報を設定する。"""

        try:
            with Image.open(path) as img:
                frames = [
                    frame.convert("RGBA") for frame in ImageSequence.Iterator(img)
                ]
        except (FileNotFoundError, UnidentifiedImageError, OSError) as exc:
            QMessageBox.critical(self, "GIF Load Error", f"Failed to load GIF.\n{exc}")
            return

        if not frames:
            QMessageBox.warning(self, "GIF Load", "No frames were found in the GIF.")
            return

        self.frames = frames
        self.gif_path = path
        self.populate_frame_list()
        self.update_preview_controls()
        self.load_preview_movie(path)
        self.decompose_button.setEnabled(True)

        # リサイズデフォルトを元のサイズに合わせる
        width, height = frames[0].size
        self.width_spin.setValue(width)
        self.height_spin.setValue(height)

        if not self.output_edit.text():
            default_dir = os.path.dirname(path)
            self.output_edit.setText(default_dir)

        self.status_bar.showMessage(f"Loaded GIF: {path}", 5000)
        self.tabs.setCurrentIndex(0)

    def populate_frame_list(self):
        """フレームリストを現在のフレームで再構築する。"""

        self.frame_list.clear()
        total = len(self.frames)
        digit = self._calc_padding(total)
        for idx in range(total):
            label = f"Frame {idx + 1:0{digit}d}"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, idx)
            self.frame_list.addItem(item)

    def update_preview_controls(self):
        """スライダーとプレビューを初期化する。"""

        if not self.frames:
            self.frame_preview.clear_preview()
            self.frame_slider.setEnabled(False)
            self.frame_slider.setRange(0, 0)
            self.frame_label.setText("Frame: - / -")
            return

        count = len(self.frames)
        self.frame_slider.blockSignals(True)
        self.frame_slider.setRange(0, count - 1)
        self.frame_slider.setValue(0)
        self.frame_slider.setEnabled(count > 1)
        self.frame_slider.blockSignals(False)
        self.frame_label.setText(f"Frame: 1 / {count}")

        self.frame_list.blockSignals(True)
        self.frame_list.setCurrentRow(0)
        self.frame_list.blockSignals(False)

        self.frame_preview.set_image(self.frames[0])

    def toggle_resize_inputs(self, state: int):
        """リサイズ入力欄とアスペクト比チェックの有効状態を更新する。"""

        enabled = state == Qt.Checked
        self.width_spin.setEnabled(enabled)
        self.height_spin.setEnabled(enabled)
        self.aspect_ratio_checkbox.setEnabled(enabled)
        if not enabled:
            self.aspect_ratio_checkbox.setChecked(False)

    def on_frame_selection_changed(self):
        """リスト選択の変更に合わせてプレビューを更新する。"""

        selected = self.frame_list.selectedItems()
        if not selected:
            return
        index = selected[0].data(Qt.UserRole)
        if index is None:
            return
        self.frame_preview.set_image(self.frames[index])
        self.frame_label.setText(f"Frame: {index + 1} / {len(self.frames)}")
        self._set_slider_value(index)

    def on_slider_changed(self, value: int):
        """スライダー移動時にリスト選択とプレビューを同期する。"""

        if self._syncing_slider or not self.frames:
            return
        value = max(0, min(value, len(self.frames) - 1))
        self._syncing_slider = True
        try:
            self.frame_list.blockSignals(True)
            self.frame_list.setCurrentRow(value)
        finally:
            self.frame_list.blockSignals(False)
            self._syncing_slider = False
        self.frame_preview.set_image(self.frames[value])
        self.frame_label.setText(f"Frame: {value + 1} / {len(self.frames)}")

    def on_width_changed(self, value: int):
        """幅が変更された際に高さを比率維持で計算する。"""

        if not (
            self.resize_checkbox.isChecked() and self.aspect_ratio_checkbox.isChecked()
        ):
            return
        reference = self._get_reference_size()
        if not reference or reference[0] == 0:
            return
        new_height = int(round(value * reference[1] / reference[0]))
        new_height = max(
            self.height_spin.minimum(), min(self.height_spin.maximum(), new_height)
        )
        self.height_spin.blockSignals(True)
        self.height_spin.setValue(new_height)
        self.height_spin.blockSignals(False)

    def on_height_changed(self, value: int):
        """高さが変更された際に幅を比率維持で計算する。"""

        if not (
            self.resize_checkbox.isChecked() and self.aspect_ratio_checkbox.isChecked()
        ):
            return
        reference = self._get_reference_size()
        if not reference or reference[1] == 0:
            return
        new_width = int(round(value * reference[0] / reference[1]))
        new_width = max(
            self.width_spin.minimum(), min(self.width_spin.maximum(), new_width)
        )
        self.width_spin.blockSignals(True)
        self.width_spin.setValue(new_width)
        self.width_spin.blockSignals(False)

    def on_aspect_ratio_changed(self, state: int):
        """アスペクト比維持オン時に現在の幅から高さを再計算する。"""

        if state == Qt.Checked and self.resize_checkbox.isChecked():
            self.on_width_changed(self.width_spin.value())

    def select_output_directory(self):
        """保存先ディレクトリをファイルダイアログで選択する。"""

        directory = QFileDialog.getExistingDirectory(
            self, "Select output directory", self.output_edit.text()
        )
        if directory:
            self.output_edit.setText(directory)

    def decompose_gif(self):
        """読み込んだGIFを静止画へ分解して保存する。"""

        if not self.frames or not self.gif_path:
            QMessageBox.warning(self, "Decomposition", "Please drop a GIF file first.")
            return

        output_dir = self.output_edit.text().strip()
        if not output_dir:
            QMessageBox.warning(
                self, "Decomposition", "Please specify an output directory."
            )
            return

        os.makedirs(output_dir, exist_ok=True)

        total = len(self.frames)
        padding = self._calc_padding(total)
        base_name = os.path.splitext(os.path.basename(self.gif_path))[0]

        resize_enabled = self.resize_checkbox.isChecked()
        target_size = None
        if resize_enabled:
            target_size = (self.width_spin.value(), self.height_spin.value())

        for index, frame in enumerate(self.frames, start=1):
            output_image = frame
            if resize_enabled and target_size:
                output_image = frame.resize(target_size, _resample_filter())

            filename = f"{base_name}_{index:0{padding}d}.png"
            output_path = os.path.join(output_dir, filename)
            output_image.save(output_path)

        self.status_bar.showMessage(f"Saved {total} frames to: {output_dir}", 5000)
        QMessageBox.information(
            self, "Decomposition", "Frames have been exported successfully."
        )

    def load_preview_movie(self, gif_path: str):
        """読み込んだGIFをプレビューダブへ設定する。"""

        if self.preview_movie:
            self.preview_movie.stop()
            self.preview_movie.deleteLater()
            self.preview_movie = None

        if not os.path.exists(gif_path):
            self.preview_movie_label.setText("GIF preview will appear here")
            self.preview_movie_label.adjustSize()
            return

        movie = QMovie(gif_path)
        if movie.isValid():
            self.preview_movie = movie
            self.preview_movie_label.setMovie(movie)
            movie.jumpToFrame(0)
            self.preview_movie_label.adjustSize()
            movie.start()
        else:
            self.preview_movie_label.setText("Unable to load GIF preview.")
            self.preview_movie_label.adjustSize()

    def _set_slider_value(self, index: int):
        """スライダーの値を同期済み状態で更新する。"""

        if not (0 <= index < len(self.frames)):
            return
        self._syncing_slider = True
        try:
            self.frame_slider.blockSignals(True)
            self.frame_slider.setValue(index)
        finally:
            self.frame_slider.blockSignals(False)
            self._syncing_slider = False

    def _get_reference_size(self) -> Optional[tuple[int, int]]:
        """比率維持計算に使う参照サイズを取得する。"""

        selected = self.frame_list.selectedItems()
        if selected:
            index = selected[0].data(Qt.UserRole)
            if index is not None:
                return self.frames[index].size
        if self.frames:
            return self.frames[0].size
        return None

    @staticmethod
    def _calc_padding(count: int) -> int:
        """フレーム数に応じたゼロパディング桁数を計算する。"""

        if count <= 0:
            return 3
        digits = len(str(count))
        if str(count).startswith("1") and set(str(count)[1:]) == {"0"}:
            digits += 1
        return max(3, digits)


def main():
    """アプリケーションを起動するエントリーポイント。"""

    app = QApplication([])
    window = GifDecompositionWindow()
    window.show()
    app.exec_()


if __name__ == "__main__":
    main()
