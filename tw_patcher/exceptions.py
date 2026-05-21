class TWPatcherError(Exception):
    pass


class RPFMError(TWPatcherError):
    pass


class ExtractionError(TWPatcherError):
    def __init__(self, message: str, failed_tables: list[tuple[str, str]] | None = None):
        super().__init__(message)
        self.failed_tables = failed_tables or []


class RepackError(TWPatcherError):
    def __init__(self, message: str, failed_tables: list[tuple[str, str]] | None = None):
        super().__init__(message)
        self.failed_tables = failed_tables or []


class ConfigurationError(TWPatcherError):
    pass


class NoGameSelectedError(ConfigurationError):
    def __init__(self):
        super().__init__("No game selected. Use --game or select a game in the UI.")
