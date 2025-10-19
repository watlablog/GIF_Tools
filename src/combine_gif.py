import os
from typing import List, Optional

from PIL import Image, ImageSequence, UnidentifiedImageError
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QMovie, QPixmap, QImage
from PyQt5.QtWidgets import (
    QApplication,
    QFileDialog,
    QLabel,
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
    QHBoxLayout,
    QSizePolicy,
)


def pil_to_qpixmap(image: Image.Image) -> QPixmap:
    """Pillow画像をQPixmapへ変換する関数。"""
    if image.mode != "RGBA":
        image = image.convert("RGBA")
    width, height = image.size
    data = image.tobytes("raw", "RGBA")
    qimage = QImage(data, width, height, QImage.Format_RGBA8888).copy()
    return QPixmap.fromImage(qimage)


class GifDropLabel(QLabel):
    """GIFファイルのドロップを受け付けるラベル。"""

    def __init__(self, prompt: str, callback):
        """表示文言とドロップ時コールバックを設定する。"""
        super().__init__(prompt)
        self.setObjectName("DropLabel")
        self.setAlignment(Qt.AlignCenter)
        self.setAcceptDrops(True)
        self.callback = callback

    def dragEnterEvent(self, event):
        """URLを含むドラッグを受理する。"""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        """GIFがドロップされたらパスをコールバックへ渡す。"""
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


class GifPreviewLabel(QLabel):
    """静止画プレビューを表示するラベル。"""

    def __init__(self, placeholder: str):
        """プレースホルダーを設定して初期化する。"""
        super().__init__(placeholder)
        self.setObjectName("PreviewLabel")
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(200, 200)
        self._pixmap: Optional[QPixmap] = None

    def set_image(self, image: Optional[Image.Image]):
        """Pillow画像を受け取りラベルに表示する。"""
        if image is None:
            self._pixmap = None
            self.setPixmap(QPixmap())
            self.setText("No preview")
            return
        pixmap = pil_to_qpixmap(image)
        self._pixmap = pixmap
        self._apply_scaled_pixmap()

    def clear_preview(self, message: str = "No preview"):
        """プレビューを消してメッセージを表示する。"""
        self._pixmap = None
        self.setPixmap(QPixmap())
        self.setText(message)

    def resizeEvent(self, event):
        """リサイズに合わせて画像の縮尺を再調整する。"""
        super().resizeEvent(event)
        if self._pixmap:
            self._apply_scaled_pixmap()

    def _apply_scaled_pixmap(self):
        """保持中の画像をラベルサイズに合わせて拡縮する。"""
        if not self._pixmap:
            return
        target = self._pixmap.scaled(
            self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        self.setPixmap(target)
        self.setText("")


class GifCombineWindow(QMainWindow):
    """GIF結合機能を提供するメインウィンドウ。"""

    def __init__(self):
        """画面レイアウトと内部状態を初期化する。"""
        super().__init__()
        self.setWindowTitle("Combine GIF Tool")
        self.resize(900, 640)

        # GIFごとの読み込み結果を格納
        self.gif_paths: List[Optional[str]] = [None, None]
        self.frames: List[List[Image.Image]] = [[], []]
        self.durations: List[List[int]] = [[], []]
        self.loop_counts: List[int] = [0, 0]

        # ドロップ領域と個別プレビュー
        self.drop_left = GifDropLabel(
            "Drop left GIF here", lambda path: self.load_gif(0, path)
        )
        self.drop_right = GifDropLabel(
            "Drop right GIF here", lambda path: self.load_gif(1, path)
        )

        self.left_preview = GifPreviewLabel("Left GIF preview")
        self.right_preview = GifPreviewLabel("Right GIF preview")

        # 入力UI群の配置
        drop_layout = QHBoxLayout()
        drop_layout.addWidget(self.drop_left, 1)
        drop_layout.addWidget(self.drop_right, 1)

        preview_layout = QHBoxLayout()
        preview_layout.addWidget(self.left_preview, 1)
        preview_layout.addWidget(self.right_preview, 1)

        # フレーム確認用スライダー
        self.frame_slider = QSlider(Qt.Horizontal)
        self.frame_slider.setEnabled(False)
        self.frame_slider.valueChanged.connect(self.on_frame_changed)

        self.frame_label = QLabel("Frame: - / -")

        slider_layout = QHBoxLayout()
        slider_layout.addWidget(self.frame_label)
        slider_layout.addWidget(self.frame_slider, 1)

        # FPS設定
        self.fps_spin = QSpinBox()
        self.fps_spin.setRange(1, 120)
        self.fps_spin.setValue(10)
        self.fps_spin.valueChanged.connect(self.on_fps_changed)

        fps_layout = QHBoxLayout()
        fps_layout.addWidget(QLabel("Frame Rate (fps)"))
        fps_layout.addWidget(self.fps_spin)
        fps_layout.addStretch()

        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText(
            "Output GIF path (e.g. /path/to/combined.gif)"
        )

        browse_button = QPushButton("Browse...")
        browse_button.clicked.connect(self.select_output_path)

        output_layout = QHBoxLayout()
        output_layout.addWidget(self.output_edit, 1)
        output_layout.addWidget(browse_button)

        create_button = QPushButton("Create GIF")
        create_button.clicked.connect(self.create_combined_gif)
        self.create_button = create_button
        self.create_button.setEnabled(False)

        # 設定タブの組み立て
        settings_layout = QVBoxLayout()
        settings_layout.addLayout(drop_layout)
        settings_layout.addSpacing(8)
        settings_layout.addLayout(preview_layout)
        settings_layout.addSpacing(8)
        settings_layout.addLayout(slider_layout)
        settings_layout.addLayout(fps_layout)
        settings_layout.addSpacing(8)
        settings_layout.addLayout(output_layout)
        settings_layout.addWidget(create_button, alignment=Qt.AlignRight)

        settings_tab = QWidget()
        settings_tab.setLayout(settings_layout)

        self.preview_movie_label = QLabel("Combined GIF preview will appear here")
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

        status_bar = QStatusBar()
        self.setStatusBar(status_bar)

        self.apply_dark_theme()

    def apply_dark_theme(self):
        """ウィンドウ全体にダークテーマのスタイルを適用する。"""
        palette = """
        QWidget {
            background-color: #1E1E1E;
            color: #E0E0E0;
            font-family: 'Helvetica Neue', Arial, sans-serif;
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
        QLineEdit, QSlider, QSpinBox {
            background-color: #252526;
            border: 1px solid #3C3C3C;
            border-radius: 4px;
            padding: 4px;
        }
        QLabel#DropLabel {
            border: 2px dashed #3C3C3C;
            border-radius: 8px;
            background-color: #252526;
            min-height: 120px;
        }
        QLabel#PreviewLabel {
            border: 1px solid #3C3C3C;
            border-radius: 8px;
            background-color: #252526;
            padding: 12px;
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

    def load_gif(self, index: int, path: str):
        """指定したGIFを読み込みプレビューと内部状態を更新する。"""
        try:
            with Image.open(path) as img:
                frames = []
                durations = []
                for frame in ImageSequence.Iterator(img):
                    copy = frame.convert("RGBA")
                    frames.append(copy)
                    durations.append(
                        frame.info.get("duration", img.info.get("duration", 100))
                    )
                loop = img.info.get("loop", 0)
        except (FileNotFoundError, UnidentifiedImageError, OSError) as exc:
            QMessageBox.critical(self, "GIF Load Error", f"Failed to load GIF.\n{exc}")
            return

        if not frames:
            QMessageBox.warning(self, "GIF Load", "No frames were found in the GIF.")
            return

        self.gif_paths[index] = path
        self.frames[index] = frames
        self.durations[index] = durations
        self.loop_counts[index] = loop

        if index == 0:
            self.left_preview.set_image(frames[0])
        else:
            self.right_preview.set_image(frames[0])

        self.statusBar().showMessage(f"Loaded GIF {index + 1}: {path}", 5000)

        if self.preview_movie:
            self.preview_movie.stop()
            self.preview_movie.deleteLater()
            self.preview_movie = None
            self.preview_movie_label.clear()
        # 生成済みプレビューを初期状態に戻す
        self.preview_movie_label.setText("Combined GIF preview will appear here")
        self.tabs.setCurrentIndex(0)

        self.update_controls_after_load()

    def update_controls_after_load(self):
        """入力が揃った際にスライダーやFPS設定を整える。"""
        ready = all(path is not None for path in self.gif_paths)
        self.create_button.setEnabled(ready)

        if ready:
            total_frames = max(len(self.frames[0]), len(self.frames[1]))
            self.frame_slider.blockSignals(True)
            self.frame_slider.setRange(0, total_frames - 1)
            self.frame_slider.setValue(0)
            self.frame_slider.setEnabled(total_frames > 1)
            self.frame_slider.blockSignals(False)
            self.update_frame_label(0)

            fps_left = self._compute_fps(self.durations[0])
            fps_right = self._compute_fps(self.durations[1])
            max_fps = max(fps_left, fps_right)
            self.fps_spin.blockSignals(True)
            self.fps_spin.setValue(max(1, int(round(max_fps))))
            self.fps_spin.blockSignals(False)
            self.on_frame_changed(0)

            if not self.output_edit.text():
                directories = [os.path.dirname(path) for path in self.gif_paths if path]
                default_dir = directories[0] if directories else "."
                default_path = os.path.join(default_dir or ".", "combined.gif")
                self.output_edit.setText(default_path)
        else:
            self.frame_slider.setEnabled(False)
            self.frame_label.setText("Frame: - / -")

    def _compute_fps(self, durations: List[int]) -> float:
        """フレーム持続時間から平均FPSを算出する。"""
        if not durations:
            return 10.0
        avg_duration = sum(durations) / len(durations)
        if avg_duration <= 0:
            return 10.0
        return 1000.0 / avg_duration

    def update_frame_label(self, index: int):
        """フレームスライダーの現在位置をラベル表示に反映する。"""
        total_frames = max(len(self.frames[0]), len(self.frames[1]))
        self.frame_label.setText(f"Frame: {index + 1} / {total_frames}")

    def on_frame_changed(self, value: int):
        """スライダー移動時に各プレビューを更新する。"""
        total_frames = max(len(self.frames[0]), len(self.frames[1]))
        if total_frames == 0:
            return
        value = max(0, min(value, total_frames - 1))
        self.update_frame_label(value)

        for i, preview in enumerate((self.left_preview, self.right_preview)):
            frames = self.frames[i]
            if frames:
                frame_index = min(value, len(frames) - 1)
                preview.set_image(frames[frame_index])
            else:
                preview.clear_preview()

    def on_fps_changed(self, value: int):
        """FPS入力が変化した際にステータスを通知する。"""
        self.statusBar().showMessage(f"FPS set to {value}", 3000)

    def select_output_path(self):
        """結合結果の保存先をダイアログで選択する。"""
        initial = self.output_edit.text() or "combined.gif"
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Select output GIF file",
            initial,
            "GIF Files (*.gif)",
        )
        if filename:
            if not filename.lower().endswith(".gif"):
                filename += ".gif"
            self.output_edit.setText(filename)

    def create_combined_gif(self):
        """2つのGIFを横方向に結合した新しいGIFを生成する。"""
        if not all(path is not None for path in self.gif_paths):
            QMessageBox.warning(self, "Combine GIF", "Please drop two GIF files first.")
            return

        output_path = self.output_edit.text().strip()
        if not output_path:
            QMessageBox.warning(self, "Combine GIF", "Please specify an output path.")
            return

        frames_a = self.frames[0]
        frames_b = self.frames[1]

        total_frames = max(len(frames_a), len(frames_b))
        if total_frames == 0:
            QMessageBox.warning(
                self, "Combine GIF", "No frames available for combination."
            )
            return

        fps = self.fps_spin.value()
        duration_ms = max(1, int(round(1000.0 / fps)))

        width_a, height_a = frames_a[0].size
        width_b, height_b = frames_b[0].size
        combined_height = max(height_a, height_b)
        combined_width = width_a + width_b

        frames_out: List[Image.Image] = []

        for index in range(total_frames):
            frame_a = frames_a[min(index, len(frames_a) - 1)]
            frame_b = frames_b[min(index, len(frames_b) - 1)]

            # 背景を白で生成し上下中央揃えで貼り付ける
            canvas = Image.new(
                "RGBA", (combined_width, combined_height), (255, 255, 255, 255)
            )

            offset_a = (0, (combined_height - frame_a.height) // 2)
            offset_b = (width_a, (combined_height - frame_b.height) // 2)

            canvas.paste(frame_a, offset_a, mask=frame_a)
            canvas.paste(frame_b, offset_b, mask=frame_b)
            frames_out.append(canvas)

        # 指定FPSに合わせた一定のフレーム持続時間を適用
        durations_out = [duration_ms] * total_frames

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        try:
            frames_out[0].save(
                output_path,
                save_all=True,
                append_images=frames_out[1:],
                duration=durations_out,
                loop=max(self.loop_counts),
                disposal=2,
            )
        except OSError as exc:
            QMessageBox.critical(
                self, "Combine GIF", f"Failed to save combined GIF.\n{exc}"
            )
            return

        self.statusBar().showMessage(f"Combined GIF saved to: {output_path}", 5000)
        self.load_preview_movie(output_path)
        self.tabs.setCurrentIndex(1)
        QMessageBox.information(
            self, "Combine GIF", "Combined GIF has been created successfully."
        )

    def load_preview_movie(self, gif_path: str):
        """生成したGIFをプレビューダブで再生する。"""
        if self.preview_movie:
            self.preview_movie.stop()
            self.preview_movie.deleteLater()
            self.preview_movie = None

        if not os.path.exists(gif_path):
            self.preview_movie_label.setText("Combined GIF preview will appear here")
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
            self.preview_movie_label.setText("Unable to load combined GIF preview.")
            self.preview_movie_label.adjustSize()


def main():
    """アプリケーションを起動するエントリーポイント。"""
    app = QApplication([])
    window = GifCombineWindow()
    window.show()
    app.exec_()


if __name__ == "__main__":
    main()
