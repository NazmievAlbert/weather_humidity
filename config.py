import os
from pathlib import Path

OWM_API_KEY = os.getenv('OWM_API_KEY')
CACHE_TTL_HOURS = int(os.getenv('CACHE_TTL_HOURS', 1))
CACHE_DIR = Path(os.getenv('CACHE_DIR', 'cache'))
MAX_CACHE_SIZE = int(os.getenv('MAX_CACHE_SIZE', 100))
LOG_DIR = os.getenv('LOG_DIR', 'logs')