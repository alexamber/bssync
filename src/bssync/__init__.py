"""bssync — two-way sync between local markdown files and a BookStack wiki."""

__version__ = "0.3.0"

from bssync.client import BookStackClient
from bssync.config import load_config

__all__ = ["BookStackClient", "load_config", "__version__"]
