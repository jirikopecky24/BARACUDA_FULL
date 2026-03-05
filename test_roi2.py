import pyqtgraph as pg
import inspect

with open('roi_shape_source.txt', 'w') as f:
    f.write(inspect.getsource(pg.ROI.shape))

    f.write("\n\n---\n\n")
    f.write(inspect.getsource(pg.ROI.mouseDragEvent))
