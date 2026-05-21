import sys

from PyQt6.QtWidgets import QApplication

from .main_window import MainWindow


def launch_ui() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("TW Mod Patcher")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
