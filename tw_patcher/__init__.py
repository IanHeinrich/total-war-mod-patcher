from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _dist_version

try:
    __version__ = _dist_version("tw-mod-patcher")
except PackageNotFoundError:  # running from a source tree that was never installed
    __version__ = "0.0.0+unknown"

from .clients.rpfm import RPFMClient, RPFMConnection
from .config import Settings, settings
from .services.extraction import ExtractionService
from .services.repacking import RepackingService
from .services.system import SystemService

__all__ = [
    "Settings",
    "settings",
    "RPFMClient",
    "RPFMConnection",
    "ExtractionService",
    "RepackingService",
    "SystemService",
]
