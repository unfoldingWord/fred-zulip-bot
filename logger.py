# logger.py
import logging
from logging.handlers import RotatingFileHandler
import os
import sys

# Create logs directory if it doesn't exist
LOG_DIR = "logs"
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

# Path to log file
LOG_FILE = os.path.join(LOG_DIR, "app.log")

# Set up rotating log handler (e.g., 1MB per file, up to 5 backups)
handler = RotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=5)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(name)s - %(message)s')
handler.setFormatter(formatter)

# Create logger instance
logger = logging.getLogger("AppLogger")
logger.setLevel(logging.INFO)
logger.addHandler(handler)

# Add stream handler to print logs to console
stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setFormatter(formatter)
logger.addHandler(stream_handler)

# Avoid duplicate logs if imported multiple times
logger.propagate = False
