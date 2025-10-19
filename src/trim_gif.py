import os
from typing import Callable, List, Optional

from PIL import Image, ImageSequence, UnidentifiedImageError
from PyQt5.QtCore import Qt, QRectF, QPointF
from PyQt5.QtGui import QColor, QPainter, QPen, QPixmap, QImage, QMovie
from PyQt5.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QSizePolicy,
)


def pil_to_pixmap(image: Image.Image) -> QPixmap:
    """Pillow画像をQtで扱えるQPixmapへ変換する関数。"""
    if image.mode != "RGBA":
        image = image.convert("RGBA")
    width, height = image.size
    data = image.tobytes("raw", "RGBA")
    qimage = QImage(data, width, height, QImage.Format_RGBA8888).copy()
    return QPixmap.fromImage(qimage)


class GifDropWidget(QLabel):
    """GIFファイルのドロップ入力を受け付けるラベル。"""

    def __init__(self, callback: Callable[[str], None]):
        """コールバックを保持してドロップ領域を初期化する。"""
        super().__init__("Drop a GIF file here")
        self.setObjectName("DropLabel")
        self.setAlignment(Qt.AlignCenter)
        self.setAcceptDrops(True)
        self.callback = callback

    def dragEnterEvent(self, event):
        """URLを含むドラッグであれば受け入れる。"""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        """GIFファイルがドロップされたらコールバックへ通知する。"""
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


class CropRectItem(QGraphicsRectItem):
    """画像内で移動・リサイズ可能なトリミング矩形。"""

    HANDLE_MARGIN = 12
    MIN_SIZE = 16

    def __init__(self, bounds: QRectF):
        """矩形の境界を設定しペンなどの初期化を行う。"""
        super().__init__(bounds)
        self._bounds = QRectF(bounds)
        self._mode = None
        self._press_pos = QPointF()
        self._press_rect = QRectF()
        self.setPen(QPen(QColor("#3cb371"), 2))
        self.setBrush(Qt.transparent)
        self.setZValue(10)
        self.setAcceptHoverEvents(True)

    def set_bounds(self, bounds: QRectF):
        """矩形が画像範囲から外れないよう境界を更新する。"""
        self._bounds = QRectF(bounds)
        rect = self.rect().intersected(self._bounds)
        if rect.width() < self.MIN_SIZE or rect.height() < self.MIN_SIZE:
            rect = self._bounds
        self.setRect(rect)

    def mousePressEvent(self, event):
        """クリック位置からリサイズ/移動モードを決定する。"""
        self._mode = self._detect_mode(event.pos())
        self._press_pos = event.pos()
        self._press_rect = QRectF(self.rect())
        event.accept()

    def mouseMoveEvent(self, event):
        """ドラッグ操作で矩形の移動やサイズ変更を行う。"""
        if self._mode is None:
            event.ignore()
            return

        pos = event.pos()
        delta = pos - self._press_pos
        rect = QRectF(self._press_rect)

        if self._mode == "move":
            rect.translate(delta)
            rect = self._constrain_move(rect)
        else:
            rect = self._resize_rect(rect, delta)

        rect = rect.intersected(self._bounds)
        if rect.width() < self.MIN_SIZE or rect.height() < self.MIN_SIZE:
            event.accept()
            return

        self.setRect(rect)
        event.accept()

    def mouseReleaseEvent(self, event):
        """ドラッグ終了時に状態をリセットする。"""
        self._mode = None
        event.accept()

    def hoverMoveEvent(self, event):
        """カーソル位置に応じたリサイズカーソルを表示する。"""
        mode = self._detect_mode(event.pos())
        cursor = Qt.ArrowCursor
        if mode in ("tl", "br"):
            cursor = Qt.SizeFDiagCursor
        elif mode in ("tr", "bl"):
            cursor = Qt.SizeBDiagCursor
        elif mode == "move":
            cursor = Qt.SizeAllCursor
        self.setCursor(cursor)
        event.accept()

    def _detect_mode(self, pos: QPointF) -> Optional[str]:
        """ドラッグ操作の対象となる辺/角/移動を判定する。"""
        rect = self.rect()
        margin = self.HANDLE_MARGIN
        within = rect.contains(pos)
        near_left = abs(pos.x() - rect.left()) <= margin
        near_right = abs(pos.x() - rect.right()) <= margin
        near_top = abs(pos.y() - rect.top()) <= margin
        near_bottom = abs(pos.y() - rect.bottom()) <= margin

        if near_left and near_top:
            return "tl"
        if near_right and near_top:
            return "tr"
        if near_left and near_bottom:
            return "bl"
        if near_right and near_bottom:
            return "br"
        if within:
            return "move"
        return None

    def _resize_rect(self, rect: QRectF, delta: QPointF) -> QRectF:
        """選択されたハンドルに基づき矩形サイズを調整する。"""
        new_rect = QRectF(rect)
        min_size = self.MIN_SIZE

        if self._mode == "tl":
            new_left = max(self._bounds.left(), rect.left() + delta.x())
            new_top = max(self._bounds.top(), rect.top() + delta.y())
            if rect.right() - new_left >= min_size:
                new_rect.setLeft(new_left)
            if rect.bottom() - new_top >= min_size:
                new_rect.setTop(new_top)
        elif self._mode == "tr":
            new_right = min(self._bounds.right(), rect.right() + delta.x())
            new_top = max(self._bounds.top(), rect.top() + delta.y())
            if new_right - rect.left() >= min_size:
                new_rect.setRight(new_right)
            if rect.bottom() - new_top >= min_size:
                new_rect.setTop(new_top)
        elif self._mode == "bl":
            new_left = max(self._bounds.left(), rect.left() + delta.x())
            new_bottom = min(self._bounds.bottom(), rect.bottom() + delta.y())
            if rect.right() - new_left >= min_size:
                new_rect.setLeft(new_left)
            if new_bottom - rect.top() >= min_size:
                new_rect.setBottom(new_bottom)
        elif self._mode == "br":
            new_right = min(self._bounds.right(), rect.right() + delta.x())
            new_bottom = min(self._bounds.bottom(), rect.bottom() + delta.y())
            if new_right - rect.left() >= min_size:
                new_rect.setRight(new_right)
            if new_bottom - rect.top() >= min_size:
                new_rect.setBottom(new_bottom)

        return new_rect

    def _constrain_move(self, rect: QRectF) -> QRectF:
        """矩形が境界の外へ出ないよう移動量を補正する。"""
        bounds = self._bounds
        dx = dy = 0.0
        if rect.left() < bounds.left():
            dx = bounds.left() - rect.left()
        elif rect.right() > bounds.right():
            dx = bounds.right() - rect.right()

        if rect.top() < bounds.top():
            dy = bounds.top() - rect.top()
        elif rect.bottom() > bounds.bottom():
            dy = bounds.bottom() - rect.bottom()

        rect.translate(dx, dy)
        return rect


class GifPreviewView(QGraphicsView):
    """トリミング用オーバーレイ付きのGIFプレビュー表示。"""

    def __init__(self):
        """シーンと表示設定を初期化する。"""
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.NoFrame)
        self.setBackgroundBrush(QColor("#101010"))
        self._pixmap_item = None
        self.crop_item: Optional[CropRectItem] = None

    def set_pixmap(self, pixmap: QPixmap):
        """新しいピクセル画像をシーンに反映する。"""
        scene = self.scene()

        if self._pixmap_item is None:
            self._pixmap_item = scene.addPixmap(pixmap)
        else:
            self._pixmap_item.setPixmap(pixmap)

        bounds = QRectF(pixmap.rect())
        scene.setSceneRect(bounds)

        if self.crop_item is None:
            self.crop_item = CropRectItem(bounds)
            scene.addItem(self.crop_item)
        else:
            self.crop_item.set_bounds(bounds)

        self._fit_view()

    def reset_crop(self):
        """矩形を画像全体にリセットする。"""
        if self.crop_item and self._pixmap_item:
            self.crop_item.setRect(QRectF(self._pixmap_item.pixmap().rect()))

    def current_crop_rect(self) -> Optional[QRectF]:
        """現在のトリミング矩形を返す。"""
        if self.crop_item:
            return QRectF(self.crop_item.rect())
        return None

    def resizeEvent(self, event):
        """ビューのリサイズに合わせて表示を調整する。"""
        super().resizeEvent(event)
        self._fit_view()

    def _fit_view(self):
        """画像全体が収まるようビューをフィットさせる。"""
        if self._pixmap_item:
            self.fitInView(self.sceneRect(), Qt.KeepAspectRatio)


class GifTrimWindow(QMainWindow):
    """GIFトリミングアプリのメインウィンドウ。"""

    def __init__(self):
        """ウィジェット構築と初期状態の設定を行う。"""
        super().__init__()
        self.setWindowTitle("GIF Trim Tool")
        self.resize(900, 640)

        # GIF読み込み状態を保持する変数郡
        self.frames: List[Image.Image] = []
        self.frame_durations: List[int] = []
        self.gif_loop = 0
        self.gif_path: Optional[str] = None

        # 入力ドロップエリアとプレビュー
        self.drop_widget = GifDropWidget(self.load_gif_from_path)
        self.preview_view = GifPreviewView()

        # フレーム切り替え用スライダー
        self.frame_slider = QSlider(Qt.Horizontal)
        self.frame_slider.setEnabled(False)
        self.frame_slider.valueChanged.connect(self.on_frame_slider_changed)

        self.frame_label = QLabel("Frame: - / -")

        # 出力ファイル設定
        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText(
            "Output GIF path (e.g. /path/to/output_trimmed.gif)"
        )
        browse_button = QPushButton("Browse...")
        browse_button.clicked.connect(self.select_output_path)

        # トリミング実行ボタン
        trim_button = QPushButton("Trim GIF")
        trim_button.clicked.connect(self.trim_gif)
        trim_button.setEnabled(False)
        self.trim_button = trim_button

        # 入力UIの配置
        output_layout = QHBoxLayout()
        output_layout.addWidget(self.output_edit, 1)
        output_layout.addWidget(browse_button)

        slider_layout = QHBoxLayout()
        slider_layout.addWidget(self.frame_label)
        slider_layout.addWidget(self.frame_slider, 1)

        # 設定タブの構築
        settings_layout = QVBoxLayout()
        settings_layout.addWidget(self.drop_widget)
        settings_layout.addSpacing(8)
        settings_layout.addWidget(self.preview_view, 1)
        settings_layout.addLayout(slider_layout)
        settings_layout.addSpacing(12)
        settings_layout.addLayout(output_layout)
        settings_layout.addWidget(trim_button, alignment=Qt.AlignRight)

        settings_tab = QWidget()
        settings_tab.setLayout(settings_layout)

        # プレビューダブの構築
        self.preview_movie_label = QLabel("Trimmed GIF preview will appear here")
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
        """ダークテーマのスタイルシートを適用する。"""
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
        QLineEdit, QSlider {
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

    def load_gif_from_path(self, path: str):
        """指定パスのGIFを読み込みフレーム情報を保持する。"""
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

        self.frames = frames
        self.frame_durations = durations
        self.gif_loop = loop
        self.gif_path = path

        self.trim_button.setEnabled(True)
        self.frame_slider.setEnabled(len(frames) > 1)
        self.frame_slider.setRange(0, len(frames) - 1)
        self.frame_slider.setValue(0)
        self.update_frame_label(0)

        pixmap = pil_to_pixmap(self.frames[0])
        self.preview_view.set_pixmap(pixmap)
        self.preview_view.reset_crop()

        if not self.output_edit.text():
            default_name = os.path.splitext(path)[0] + "_trimmed.gif"
            self.output_edit.setText(default_name)

        self.statusBar().showMessage(f"Loaded GIF: {path}", 5000)
        if self.preview_movie:
            self.preview_movie.stop()
            self.preview_movie.deleteLater()
            self.preview_movie = None
            self.preview_movie_label.clear()
        # 以前のプレビュー表示を初期状態へ戻す
        self.preview_movie_label.setText("Trimmed GIF preview will appear here")
        self.tabs.setCurrentIndex(0)

    def update_frame_label(self, index: int):
        """現在フレームのインデックス表示を更新する。"""
        total = len(self.frames)
        self.frame_label.setText(f"Frame: {index + 1} / {total}")

    def on_frame_slider_changed(self, value: int):
        """スライダー操作に合わせてプレビューを切り替える。"""
        if not self.frames:
            return
        value = max(0, min(value, len(self.frames) - 1))
        pixmap = pil_to_pixmap(self.frames[value])
        self.preview_view.set_pixmap(pixmap)
        self.update_frame_label(value)

    def select_output_path(self):
        """保存先のGIFファイルをダイアログで選択する。"""
        initial = self.output_edit.text() or "trimmed.gif"
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

    def trim_gif(self):
        """指定された矩形でGIFをトリミングして保存する。"""
        if not self.frames:
            QMessageBox.warning(self, "Trim GIF", "Please drop a GIF file first.")
            return

        output_path = self.output_edit.text().strip()
        if not output_path:
            QMessageBox.warning(self, "Trim GIF", "Please specify an output path.")
            return

        crop_rect = self.preview_view.current_crop_rect()
        if not crop_rect:
            QMessageBox.warning(self, "Trim GIF", "Crop area is not defined.")
            return

        left = int(crop_rect.left())
        top = int(crop_rect.top())
        right = int(crop_rect.right())
        bottom = int(crop_rect.bottom())

        if right <= left or bottom <= top:
            QMessageBox.warning(self, "Trim GIF", "Invalid crop area.")
            return

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        cropped_frames = []
        # すべてのフレームを矩形で切り抜いて蓄積
        for frame in self.frames:
            cropped_frames.append(frame.crop((left, top, right, bottom)))

        try:
            first = cropped_frames[0]
            # 切り出し結果を元フレーム設定を踏まえて保存
            first.save(
                output_path,
                save_all=True,
                append_images=cropped_frames[1:],
                loop=self.gif_loop,
                duration=self.frame_durations,
                disposal=2,
            )
        except OSError as exc:
            QMessageBox.critical(
                self, "Trim GIF", f"Failed to save trimmed GIF.\n{exc}"
            )
            return

        self.statusBar().showMessage(f"Trimmed GIF saved to: {output_path}", 5000)
        self.load_preview_movie(output_path)
        self.tabs.setCurrentIndex(1)
        QMessageBox.information(
            self, "Trim GIF", "Trimmed GIF has been created successfully."
        )

    def load_preview_movie(self, gif_path: str):
        """トリミング後のGIFをプレビューダブへ読み込む。"""
        if self.preview_movie:
            self.preview_movie.stop()
            self.preview_movie.deleteLater()
            self.preview_movie = None

        if not os.path.exists(gif_path):
            self.preview_movie_label.setText("Trimmed GIF preview will appear here")
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
            self.preview_movie_label.setText("Unable to load trimmed GIF preview.")
            self.preview_movie_label.adjustSize()


def main():
    """トリミングアプリを起動するエントリーポイント。"""
    app = QApplication([])
    window = GifTrimWindow()
    window.show()
    app.exec_()


if __name__ == "__main__":
    main()
