from PyQt6.QtCore import QObject, pyqtSignal


class AppState(QObject):
    log_message = pyqtSignal(str, str)  # (message, level)
    busy_changed = pyqtSignal(bool)
    patch_mods_changed = pyqtSignal()
    modding_root_changed = pyqtSignal()
    game_changed = pyqtSignal(str)  # game_key

    def __init__(self):
        super().__init__()
        self._busy = False

    @property
    def is_busy(self) -> bool:
        return self._busy

    def set_busy(self, busy: bool) -> None:
        if self._busy != busy:
            self._busy = busy
            self.busy_changed.emit(busy)

    def log(self, message: str, level: str = "info") -> None:
        self.log_message.emit(message, level)
