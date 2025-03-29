import json
from datetime import datetime, timedelta
from pathlib import Path

class WeatherCache:
    def __init__(self, cache_dir, ttl_hours, max_size):
        self.cache_dir = cache_dir
        self.ttl = timedelta(hours=ttl_hours)
        self.max_size = max_size