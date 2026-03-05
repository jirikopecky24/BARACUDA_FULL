from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QPainterPath, QPainterPathStroker
import pyqtgraph as pg
import sys
import numpy as np

class OutlineROI(pg.ROI):
    def shape(self):
        p = QPainterPath()
        p.addRect(self.boundingRect())
        stroker = QPainterPathStroker()
        stroker.setWidth(8)  # clickable border width
        return stroker.createStroke(p)

app = QApplication(sys.argv)
win = pg.GraphicsLayoutWidget()
v = win.addViewBox()
v.setAspectLocked()

img = pg.ImageItem()
img.setImage(np.random.normal(size=(100, 100)))
v.addItem(img)

roi = OutlineROI([20, 20], [40, 40], movable=True)
roi.addScaleHandle([1, 1], [0, 0])
roi.addScaleHandle([0, 0], [1, 1])
roi.addScaleHandle([1, 0], [0, 1])
roi.addScaleHandle([0, 1], [1, 0])
v.addItem(roi)

win.show()
QTimer.singleShot(5000, app.quit) # Show for 5 seconds to test
app.exec()
