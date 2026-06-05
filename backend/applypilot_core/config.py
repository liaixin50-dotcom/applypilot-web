"""ApplyPilot Core config — paths and defaults for the web backend."""

import os
from pathlib import Path

# All data lives inside the backend directory for demo portability
BACKEND_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BACKEND_DIR / "applypilot.db"
RESUME_PATH = BACKEND_DIR / "resume.txt"

# Default search config (used by mock discover)
DEFAULT_QUERY = os.environ.get("APPLYPILOT_QUERY", "marketing")
DEFAULT_LOCATION = os.environ.get("APPLYPILOT_LOCATION", "Hong Kong")
