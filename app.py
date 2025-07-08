import numpy as np
import sys

from PyQt5.QtWidgets import (
    QApplication, QWidget, QPushButton, QVBoxLayout,
    QFileDialog, QLabel, QCheckBox, QSpinBox, QHBoxLayout
)
from PyQt5.QtCore import Qt, QRect, pyqtSignal, QTimer, QThread
from PyQt5.QtGui import QPainter, QPen, QColor, QPixmap, QGuiApplication, QImage

from pynput import keyboard

from skribbl_helper import find_canvas, downscale_and_quantise, qimage_to_np_array, create_brush_strokes
from drawing import StrokeDrawing


class SnipOverlay(QWidget):

    region_selected = pyqtSignal(tuple)    # NEW: x, y, x, y
    def __init__(self):
        super().__init__()

        # Capture the screen and store it
        self.screen_pixmap = QGuiApplication.primaryScreen().grabWindow(0)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setWindowState(Qt.WindowFullScreen)

        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.CrossCursor)

        self.start = None
        self.end = None

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.start = event.pos()
            self.end = self.start
            self.update()

    def mouseMoveEvent(self, event):
        if self.start:
            self.end = event.pos()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.start and self.end:
            # Only accept region if it's sufficiently large (to avoid accidental clicks)
            if (self.start - self.end).manhattanLength() > 10:
                x1 = min(self.start.x(), self.end.x())
                y1 = min(self.start.y(), self.end.y())
                x2 = max(self.start.x(), self.end.x())
                y2 = max(self.start.y(), self.end.y())
                self.region_selected.emit(find_canvas(self.snip_overlay(x1, x2, y1, y2), x1, y1))  # <--- EMIT COORDINATES
            else:
                print("Selection too small — ignored.")
            self.close()

    def paintEvent(self, event):
        painter = QPainter(self)

        # Show the screenshot as the background
        painter.drawPixmap(0, 0, self.screen_pixmap)

        # Dim the entire screen
        painter.fillRect(self.rect(), QColor(0, 0, 0, 100))

        # Draw the selection rectangle if dragging
        if self.start and self.end:
            rect = QRect(self.start, self.end)
            painter.setPen(QPen(QColor(0, 255, 0), 2))
            painter.setBrush(QColor(0, 255, 0, 40))
            painter.drawRect(rect)

    def snip_overlay(self, x1, x2, y1, y2) -> np.ndarray:
        """ Snip screenshot and convert to numpy arry. """
        image = self.screen_pixmap.toImage().convertToFormat(QImage.Format_ARGB32)
        x, y, w, h = x1, y1, x2 - x1, y2 - y1
        # Crop using QRect, then convert to numpy
        cropped_img = image.copy(x, y, w, h)
        ptr = cropped_img.bits()
        ptr.setsize(cropped_img.byteCount())
        arr = np.array(ptr).reshape(h, w, 4)  # ARGB

        return arr[:, :, [2, 1, 0]]
    

class SimpleApp(QWidget):

    set_drawing_strokes = pyqtSignal(list)
    set_drawing_canvas = pyqtSignal(tuple)
    set_drawing_colours = pyqtSignal(list)
    reset_drawing = pyqtSignal()
    draw = pyqtSignal(int)
    stop_drawing = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Skribble drawer.")
        self.setWindowFlags(Qt.Window | Qt.CustomizeWindowHint | Qt.WindowTitleHint | Qt.WindowStaysOnTopHint | Qt.WindowCloseButtonHint)
        # --- UI Elements ---
        self.select_region_btn = QPushButton("Select Region")
        self.select_region_btn.clicked.connect(self.launch_snipper)

        self.random_checkbox = QCheckBox("Random")

        self.reset_button = QPushButton("Reset")
        self.reset_button.clicked.connect(self.reset)

        self.image_label = QLabel("No image loaded")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setFixedHeight(150)
        self.image_label.setStyleSheet("border: 1px solid gray;")

        self.paste_image_button = QPushButton("Paste Image")
        self.paste_image_button.clicked.connect(self.paste_image)

        self.brush_size_input = QSpinBox()
        self.brush_size_input.setRange(1, 100)
        self.brush_size_input.setValue(10)

        brush_layout = QHBoxLayout()
        brush_layout.addWidget(QLabel("Brush Size:"))
        brush_layout.addWidget(self.brush_size_input)

        self.draw_delay_input = QSpinBox()
        self.draw_delay_input.setRange(0, 5000)
        self.draw_delay_input.setSingleStep(100)
        self.draw_delay_input.setValue(100)

        delay_layout = QHBoxLayout()
        delay_layout.addWidget(QLabel("Draw Delay (ms):"))
        delay_layout.addWidget(self.draw_delay_input)
        
        self.progress_label = QLabel("'Drawing: 0/0")

        # --- Layout ---
        layout = QVBoxLayout()
        layout.addWidget(self.select_region_btn)
        layout.addWidget(self.random_checkbox)
        layout.addLayout(brush_layout)
        layout.addLayout(delay_layout)
        layout.addWidget(self.progress_label)
        layout.addWidget(self.reset_button)
        layout.addWidget(self.image_label)
        layout.addWidget(self.paste_image_button)

        self.setLayout(layout)

        self._data = None
        self._image = None
        self._thread = QThread()
        self._drawing = StrokeDrawing()
        self._drawing.moveToThread(self._thread)
        self._started = False
        # Connect signals.
        self._drawing.progress_signal.connect(self.update_progress)
        self._drawing.request_next_stroke.connect(self.request_draw)
        
        self.set_drawing_canvas.connect(self._drawing.set_canvas)
        self.set_drawing_colours.connect(self._drawing.set_colours)
        self.set_drawing_strokes.connect(self._drawing.set_strokes)
        self.reset_drawing.connect(self._drawing.reset)
        self.draw.connect(self._drawing.draw)
        self.stop_drawing.connect(self._drawing.stop)

        self.listener = keyboard.Listener(on_press=self.on_key_press, on_release=self.on_key_release)
        self.listener.start()
        self._thread.start()

    def launch_snipper(self):
        self.overlay = SnipOverlay()
        self.overlay.region_selected.connect(self.on_canvas_found)
        self.overlay.showFullScreen()
        self.overlay.activateWindow()
    
    def request_draw(self, drawing: bool):
        if self._started and drawing:
            self.draw.emit(self.draw_delay_input.value())
        elif not drawing:
            self._started = False

    def on_key_press(self, key):
        try:
            if key.char == '-' and not self._started:
                print('start!')
                self._started = True
                self.request_draw(True)
        except:
            pass

    def on_key_release(self, key):
        try:
            if key.char == '-':
                print('KEY RELEASED STOPPING!')
                self.stop_drawing.emit()
                self._started = False
        except:
            pass

    def on_canvas_found(self, data: tuple):
        self._set_content(data=data)

    def reset(self):
        self.reset_drawing.emit()

    def paste_image(self):
        clipboard = QApplication.clipboard()
        image = clipboard.image()
        if not image.isNull():
            pixmap = QPixmap.fromImage(image)
            self.image_label.setPixmap(pixmap.scaled(
                self.image_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
            ))
            self._set_content(image=qimage_to_np_array(image))       
            print("Image pasted from clipboard.")
        else:
            self._image = None
            self.image_label.setText("No image in clipboard")
            print("Clipboard does not contain an image.")

    def update_progress(self, progress: str):
        self.progress_label.setText(progress)

    def _set_content(self, image: np.ndarray = None, data: tuple = None):
        if data is not None:
            self._data = data
            self.set_drawing_canvas.emit(data[0])
            self.set_drawing_colours.emit(data[1])
        if image is not None:
            self._image = image
        if self._data is not None and self._image is not None:
            canvas, colours = self._data
            self.set_drawing_strokes.emit(
                create_brush_strokes(
                    self._image,
                    [colour[0] for colour in colours],
                    width=canvas[2] - canvas[0],
                    height=canvas[3] - canvas[1] - 50
            )[:40])

    def closeEvent(self, event):
        # Optional: Stop thread cleanly on window close
        if self._thread.isRunning():
            print("Stopping thread...")
            self._drawing.stop()
            self._thread.quit()
            self._thread.wait()  # Wait for thread to finish

        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = SimpleApp()
    window.show()
    sys.exit(app.exec_())