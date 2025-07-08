from PyQt5.QtCore import QThread, pyqtSignal, QTimer, QObject, pyqtSlot
from PyQt5.QtWidgets import QApplication
from threading import Event
import random


class MouseControl:

    def click(self):
        pass

    def move(self, x, y, duration):
        pass

    def press(self, x, y):
        pass

    def release(self, x, y):
        pass


class RootMouse(MouseControl):

    def __init__(self):
        super().__init__()
        import mouse
        self._m = mouse
    
    def click(self):
        self._m.click()

    def move(self, x, y, duration: int = None):
        self._m.move(x, y, True, 0 if duration is None else duration / 1000)
    
    def press(self):
        self._m.press()

    def release(self):
        self._m.release()


class PyAutoMouse(MouseControl):

    def __init__(self):
        super().__init__()
        import pyautogui
        self._m = pyautogui

    def click(self):
        self._m.click('left')

    def move(self, x, y, duration: int = None):
        self._m.moveTo(x + 2560, y, (0 if duration is None else duration / 1000))
    
    def press(self):
        self._m.press('left')

    def release(self):
        self._m.mouseUp('left')


class StrokeDrawing(QObject):

    finished = pyqtSignal()

    request_next_stroke = pyqtSignal(bool)
    progress_signal = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._canvas = (0, 0, 0, 0)
        self._colours = {}

        self._strokes = []
        self._index = 0
        self._stroke_index = 0
        self._active_colour = None
        self._is_drawing = False
        self._reset_flag = False

        self._mouse_press = False
        self._velocity = 100
        self._distance = 100

        self.mouse = RootMouse()

        self.update_progress()

    def update_progress(self):
        self.progress_signal.emit(f'Drawing {self._index}/{len(self._strokes)}')
    
    def _reset(self):
        self._index = 0
        self._stroke_index = 0
        self._active_colour = None
        self._reset_flag = False

    @pyqtSlot()
    def reset(self):
        if self._is_drawing:
            self._reset_flag = True
            self._is_drawing = False
        else:
            self._reset()

    @pyqtSlot(list)
    def set_strokes(self, strokes: list):
        if self._is_drawing:
            return
        self._strokes = []
        for stroke in strokes:
            self._strokes.extend([
                (stroke[0], polygon) for polygon in stroke[1]
            ])

    @pyqtSlot(tuple)
    def set_canvas(self, canvas_coords: tuple):
        if self._is_drawing:
            return
        self._canvas = canvas_coords

    @pyqtSlot(list)
    def set_colours(self, colours: list):
        if self._is_drawing:
            return
        self._colours.clear()
        for colour in colours:
            self._colours[tuple(colour[0])] = colour[1]

    @pyqtSlot(int)
    def draw(self, velocity: int):
        """ Draw the stroke. """
        self._is_drawing = True
        self._velocity = velocity
        self.update_progress()
        # Drawing loop.
        if self._index >= len(self._strokes):
            self._is_drawing = False
            self.release_mouse()
            self.request_next_stroke.emit(False)
            return

        colour, strokes = self._strokes[self._index]
        if self._active_colour is None or tuple(colour) != self._active_colour:
            self.select_colour(colour)

        is_final_stroke = self._stroke_index + 1 >= len(strokes)
        start = strokes[self._stroke_index]
        end = strokes[0] if is_final_stroke else strokes[self._stroke_index + 1]

        self.move_mouse(start, relative=True)

        if not self._mouse_press:
            self.press_mouse()

        distance = (((end[0] - start[0]) ** 2) + ((end[1] - start[1]) ** 2)) ** .5
        time = (distance / self._distance) * self._velocity

        self.move_mouse(end, relative=True, duration=time)

        self.update_progress()

        if is_final_stroke:
            self._stroke_index = 0
            self._index += 1
            self.release_mouse()
        else:
            self._stroke_index += 1

        if self._is_drawing:
            self.request_next_stroke.emit(True)
        else:
            self.release_mouse()
            self.request_next_stroke.emit(False)

    @pyqtSlot()
    def stop(self):
        self.release_mouse()
        self._is_drawing = False
        
        
    def select_colour(self, colour):
        colour = tuple(colour)
        if colour not in self._colours:
            raise IndexError(f'Colour not found {colour} in {self._colours}')
        elif colour == self._active_colour:
            return
        click_area = self._colours[colour]
        print('selecting new colour!')

        self.mouse_click(
            click_area[0] + ((click_area[2] - click_area[0]) // 2),
            click_area[1] + ((click_area[3] - click_area[1]) // 2),
            relative=False
        )

        self._active_colour = colour
        
    def mouse_click(self, x: int, y: int, relative: bool):
        self.mouse.move(
            self._canvas[0] + x if relative else x,
            self._canvas[1] + y if relative else y
        )
        self.mouse.click()

    def press_mouse(self):
        self._mouse_press = True
        self.mouse.press()

    def move_mouse(self, pos: tuple, duration = None, relative: bool = False):
        self.mouse.move(
            self._canvas[0] + pos[0] if relative else pos[0],
            self._canvas[1] + pos[1] if relative else pos[1],
            0 if duration is None else duration / 1000
        )

    def release_mouse(self):
        self.mouse.release()
        self._mouse_press = False