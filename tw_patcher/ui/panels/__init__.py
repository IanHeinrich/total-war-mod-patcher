from PyQt6.QtWidgets import QGroupBox

from ..state import AppState


class BasePanel(QGroupBox):
    def __init__(self, title: str, state: AppState):
        super().__init__(title)
        self._state = state
        state.busy_changed.connect(self.set_busy)

    def set_busy(self, busy: bool) -> None:
        pass
