import sys
from PyQt6.QtWidgets import QApplication
from barakuda.shell.main_window import ShellMainWindow


def run_app(app_mode: str = "full") -> int:
    app = QApplication(sys.argv)
    win = ShellMainWindow(app_mode=app_mode)
    win.show()
    return app.exec()
