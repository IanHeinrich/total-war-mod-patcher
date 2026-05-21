from html import escape

from PyQt6.QtWidgets import QTextEdit

from ..state import AppState

_LEVEL_COLORS = {
    "info": "#cccccc",
    "success": "#4ec970",
    "warning": "#e5c07b",
    "error": "#e06c75",
    "progress": "#61afef",
}


class LogViewer(QTextEdit):
    def __init__(self, state: AppState):
        super().__init__()
        self.setReadOnly(True)
        self.setMaximumHeight(150)
        self.setStyleSheet("QTextEdit { background-color: #1e1e1e; }")
        state.log_message.connect(self._append_colored)

    def _append_colored(self, message: str, level: str) -> None:
        color = _LEVEL_COLORS.get(level, _LEVEL_COLORS["info"])
        self.append(f'<span style="color:{color}">{escape(message)}</span>')
