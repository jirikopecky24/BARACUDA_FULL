import sys
from PyQt6.QtWidgets import QApplication
from barakuda.shell.main_window import ShellMainWindow


def main() -> int:
    app = QApplication(sys.argv)
    win = ShellMainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
