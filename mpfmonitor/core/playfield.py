import logging

# For drag and drop vs click separation
import time

# will change these to specific imports once code is more final
from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *

from enum import Enum


class Shape(Enum):
    DEFAULT = 0
    SQUARE = 1
    RECTANGLE = 2
    CIRCLE = 3
    TRIANGLE = 4
    ARROW = 5
    FLIPPER = 6


class PfView(QGraphicsView):

    def __init__(self, parent, mpfmon):
        self.mpfmon = mpfmon
        super().__init__(parent)

        self.setWindowTitle("Playfield")
        self.set_inspector_mode_title(inspect=False)

    def resizeEvent(self, event=None):
        self.fitInView(self.mpfmon.pf, Qt.KeepAspectRatio)

    def set_inspector_mode_title(self, inspect=False):
        if inspect:
            self.setWindowTitle('Inspector Enabled - Playfield')
        else:
            self.setWindowTitle("Playfield")

    def closeEvent(self, event):
        self.mpfmon.write_local_settings()
        event.accept()
        self.mpfmon.check_if_quit()


class PfPixmapItem(QGraphicsPixmapItem):

    def __init__(self, image, mpfmon, parent=None):
        super().__init__(image, parent)

        self.mpfmon = mpfmon
        self.setAcceptDrops(True)


    def create_widget_from_config(self, widget, device_type, device_name):
        try:
            x = self.mpfmon.config[device_type][device_name]['x']
            y = self.mpfmon.config[device_type][device_name]['y']
            default_size = self.mpfmon.pf_device_size
            shape_str = self.mpfmon.config[device_type][device_name].get('shape', 'DEFAULT')
            shape = Shape[str(shape_str).upper()]
            rotation = self.mpfmon.config[device_type][device_name].get('rotation', 0)
            size = self.mpfmon.config[device_type][device_name].get('size', default_size)

        except KeyError:
            return

        x *= self.mpfmon.scene.width()
        y *= self.mpfmon.scene.height()

        self.create_pf_widget(widget, device_type, device_name, x, y,
                              size=size, rotation=rotation, shape=shape, save=False)

    def dragEnterEvent(self, event):
        event.acceptProposedAction()

    dragMoveEvent = dragEnterEvent

    def dropEvent(self, event):
        device = event.source().selectedIndexes()[0]
        device_name = device.data()
        device_type = device.parent().data()

        drop_x = event.scenePos().x()
        drop_y = event.scenePos().y()

        try:
            widget = self.mpfmon.device_window.device_states[device_type][device_name]
            self.create_pf_widget(widget, device_type, device_name, drop_x,
                                  drop_y)
        except KeyError:
            self.mpfmon.log.warn("Invalid device dragged.")



    def create_pf_widget(self, widget, device_type, device_name, drop_x,
                         drop_y, size=None, rotation=0, shape=Shape.DEFAULT, save=True):
        w = PfWidget(self.mpfmon, widget, device_type, device_name, drop_x,
                     drop_y, size=size, rotation=rotation, shape=shape, save=save)

        self.mpfmon.scene.addItem(w)



class PfWidget(QGraphicsItem):

    def __init__(self, mpfmon, widget, device_type, device_name, x, y,
                 size=None, rotation=0, shape=Shape.DEFAULT, save=True):
        super().__init__()

        self.widget = widget
        self.mpfmon = mpfmon
        self.name = device_name
        self.move_in_progress = True
        self.device_type = device_type
        self.set_size(size=size)
        self.shape = shape
        self.angle = rotation

        self.setToolTip('{}: {}'.format(self.device_type, self.name))
        self.setAcceptedMouseButtons(Qt.LeftButton | Qt.RightButton)
        self.setPos(x, y)
        self.update_pos(save)
        self.click_start = 0
        self.release_switch = False

        self.log = logging.getLogger('Core')

        old_widget_exists = widget.set_change_callback(self.notify)

        if old_widget_exists:
            self.log.debug("Previous widget exists.")
            old_widget_exists(destroy=True)


    def boundingRect(self):
        return QRectF(self.device_size / -2, self.device_size / -2,
                      self.device_size, self.device_size)

    def set_shape(self, shape):
        if isinstance(shape, Shape):
            self.shape = shape
        else:
            self.shape = Shape.DEFAULT

    def set_rotation(self, angle=0):
        angle = angle % 360
        self.angle = angle

    def set_size(self, size=None):
        if size is None:
            self.size = self.mpfmon.pf_device_size
            self.device_size = self.mpfmon.scene.width() * \
                               self.mpfmon.pf_device_size
        else:
            self.size = size
            self.device_size = self.mpfmon.scene.width() * size

    def resize_to_default(self, force=False):
        device_config = self.mpfmon.config[self.device_type].get(self.name, None)

        if force:
            device_config.pop('size', None) # Delete saved size info, None is incase key doesn't exist (popped twice)

        device_size = device_config.get('size', None)

        if device_size is not None:
            # Do not change the size if it's already set
            pass
        elif device_config is not None:
            self.set_size()

        self.update_pos(save=False)  # Do not save at this point. Let it be saved elsewhere. This reduces writes.

    def color_gamma(self, color):

        """
        Feel free to fiddle with these constants until it feels right
        With gamma = 0.5 and constant a = 18, the top 54 values are lost,
        but the bottom 25% feels much more normal.
        """

        gamma = 0.5
        a = 18
        corrected = []

        for value in color:
            value = int(pow(value, gamma) * a)
            if value > 255:
                value = 255
            corrected.append(value)

        return corrected

    def set_colored_brush(self, device_type, widget):
        if device_type == 'light':
            color = self.color_gamma(widget.data()['color'])

        elif device_type == 'switch':
            state = widget.data()['state']

            if state:
                color = [0, 255, 0]
            else:
                color = [0, 0, 0]

        return QBrush(QColor(*color), Qt.SolidPattern)

    def paint(self, painter, option, widget=None):

        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(QPen(Qt.white, 3, Qt.SolidLine))
        painter.rotate(self.angle)

        brush = self.set_colored_brush(self.device_type, self.widget)
        painter.setBrush(brush)

        draw_shape = self.shape

        # Preserve legacy and regular use
        if draw_shape == Shape.DEFAULT:
            if self.device_type == 'light':
                draw_shape = Shape.CIRCLE
            elif self.device_type == 'switch':
                draw_shape = Shape.SQUARE

        # Draw based on the shape we want, not device type.
        if draw_shape == Shape.CIRCLE:
            painter.drawEllipse(self.device_size / -2, self.device_size / -2,
                                self.device_size, self.device_size)

        elif draw_shape == Shape.SQUARE:
            aspect_ratio = 1  # Smaller for taller rectangles, larger for wider rectangles
            painter.drawRect((self.device_size * aspect_ratio) / -2, self.device_size / -2,
                             self.device_size * aspect_ratio, self.device_size)

        elif draw_shape == Shape.RECTANGLE:
            aspect_ratio = .4  # Smaller for taller rectangles, larger for wider rectangles
            painter.drawRect((self.device_size * aspect_ratio) / -2, self.device_size / -2,
                             self.device_size * aspect_ratio, self.device_size)

        elif draw_shape == Shape.TRIANGLE:
            aspect_ratio = 1
            scale = .6
            points = QPolygon([
                QPoint(0, self.device_size * scale * -1),
                QPoint(self.device_size * scale * -1, ((self.device_size * scale) / 2) * aspect_ratio),
                QPoint(self.device_size * scale, ((self.device_size * scale) / 2) * aspect_ratio),
            ])
            painter.drawPolygon(points)

        elif draw_shape == Shape.ARROW:
            """
            Vertex  1: x=0   y=-10 
            Vertex  2: x=-5  y=0
            Vertex  3: x=-2  y=0
            Vertex  4: x=-2  y=5
            Vertex  5: x=2   y=5
            Vertex  6: x=2   y=0
            Vertex  7: x=5   y=0
            """

            aspect_ratio = 1
            scale = .8
            points = QPolygon([
                QPoint(0, self.device_size * scale * -1),
                QPoint(self.device_size * scale / -2, 0),
                QPoint(self.device_size * scale / -4, 0),
                QPoint(self.device_size * scale / -4, self.device_size * scale / 2),
                QPoint(self.device_size * scale / 4, self.device_size * scale / 2),
                QPoint(self.device_size * scale / 4, 0),
                QPoint(self.device_size * scale / 2, 0)
            ])
            painter.drawPolygon(points)

        elif draw_shape == Shape.FLIPPER:
            aspect_ratio = 5
            scale = .7
            points = QPolygon([
                QPoint(0, self.device_size * scale * -1),
                QPoint(self.device_size * scale * -1, ((self.device_size * scale) / 2) * aspect_ratio),
                QPoint(self.device_size * scale, ((self.device_size * scale) / 2) * aspect_ratio),
            ])
            painter.drawPolygon(points)

    def notify(self, destroy=False, resize=False):
        self.update()

        if destroy:
            self.destroy()


    def destroy(self):
        self.log.debug("Destroy device: " + self.name)
        self.mpfmon.scene.removeItem(self)
        self.delete_from_config()

    def mouseMoveEvent(self, event):
        if (self.mpfmon.pf.boundingRect().width() > event.scenePos().x() >
                0) and (self.mpfmon.pf.boundingRect().height() >
                event.scenePos().y() > 0):
            # devices off the pf do weird things at the moment

            if time.time() - self.click_start > .3:
                self.setPos(event.scenePos())
                self.move_in_progress = True

    def mousePressEvent(self, event):
        self.click_start = time.time()

        if self.device_type == 'switch':
            if event.buttons() & Qt.RightButton:
                if not self.get_val_inspector_enabled():
                    self.mpfmon.bcp.send('switch', name=self.name, state=-1)
                    self.release_switch = False
                else:
                    self.send_to_inspector_window()
                    self.log.debug('Switch ' + self.name + ' right clicked')
            elif event.buttons() & Qt.LeftButton:
                if not self.get_val_inspector_enabled():
                    self.mpfmon.bcp.send('switch', name=self.name, state=-1)
                    self.release_switch = True
                else:
                    self.send_to_inspector_window()
                    self.log.debug('Switch ' + self.name + ' clicked')

        else:
            if event.buttons() & Qt.RightButton:
                if self.get_val_inspector_enabled():
                    self.send_to_inspector_window()
                    self.log.debug(str(self.device_type) + ' ' + self.name + ' right clicked')
            elif event.buttons() & Qt.LeftButton:
                if self.get_val_inspector_enabled():
                    self.send_to_inspector_window()
                    self.log.debug(str(self.device_type) + ' ' + self.name + ' clicked')


    def mouseReleaseEvent(self, event):
        if self.move_in_progress and time.time() - self.click_start > .5:
            self.move_in_progress = False
            self.update_pos()

        elif self.release_switch:
            self.mpfmon.bcp.send('switch', name=self.name, state=-1)

        self.click_start = 0

    def update_pos(self, save=True):
        x = self.pos().x() / self.mpfmon.scene.width() if self.mpfmon.scene.width() > 0 else self.pos().x()
        y = self.pos().y() / self.mpfmon.scene.height() if self.mpfmon.scene.height() > 0 else self.pos().y()

        if self.device_type not in self.mpfmon.config:
            self.mpfmon.config[self.device_type] = dict()

        if self.name not in self.mpfmon.config[self.device_type]:
            self.mpfmon.config[self.device_type][self.name] = dict()

        self.mpfmon.config[self.device_type][self.name]['x'] = x
        self.mpfmon.config[self.device_type][self.name]['y'] = y

        # Only save the shape if it is different than the  default
        conf_shape_str = self.mpfmon.config[self.device_type][self.name].get('shape', 'DEFAULT')
        conf_shape = Shape[str(conf_shape_str).upper()]

        if self.shape is not conf_shape:
            if self.shape is not Shape.DEFAULT:
                self.mpfmon.config[self.device_type][self.name]['shape'] = self.shape.name
            else:
                try:
                    self.mpfmon.config[self.device_type][self.name].pop('shape')
                except:
                    pass

        # Only save the rotation if it has been changed
        conf_angle = self.mpfmon.config[self.device_type][self.name].get('angle', -1)

        if self.angle is not conf_angle:
            if self.angle != 0:
                self.mpfmon.config[self.device_type][self.name]['rotation'] = self.angle
            else:
                try:
                    self.mpfmon.config[self.device_type][self.name].pop('rotation')
                except:
                    pass

        # Only save the size if it is different than the top level default
        default_size = self.mpfmon.pf_device_size
        conf_size = self.mpfmon.config[self.device_type][self.name].get('size', default_size)

        if self.size is not conf_size \
                and self.size is not self.mpfmon.pf_device_size:
            self.mpfmon.config[self.device_type][self.name]['size'] = self.size

        if save:
            self.mpfmon.save_config()

    def delete_from_config(self):
        self.mpfmon.config[self.device_type].pop(self.name)
        self.mpfmon.save_config()

    def get_val_inspector_enabled(self):
        return self.mpfmon.inspector_enabled

    def send_to_inspector_window(self):
        self.mpfmon.inspector_window_last_selected_cb(pf_widget=self)
