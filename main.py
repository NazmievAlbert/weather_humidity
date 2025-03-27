import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime, timedelta
import time
from flask import Flask, request, jsonify
import requests
import math
import os
from pathlib import Path
import hashlib
from functools import wraps

# Initialize Flask app with minimal configuration
app = Flask(__name__)
app.config.update({
    'OWM_API_KEY': os.getenv('OWM_API_KEY'),
    'CACHE_TTL_HOURS': int(os.getenv('CACHE_TTL_HOURS', 1)),
    'CACHE_DIR': Path(os.getenv('CACHE_DIR', 'weather_cache')),
    'MAX_CACHE_SIZE': int(os.getenv('MAX_CACHE_SIZE', 100)),
    'LOG_DIR': os.getenv('LOG_DIR', 'logs')
})


# Simplified logging setup
def setup_logging():
    """Configure basic logging"""
    if not os.path.exists(app.config['LOG_DIR']):
        os.makedirs(app.config['LOG_DIR'])

    handler = RotatingFileHandler(
        os.path.join(app.config['LOG_DIR'], 'weather_service.log'),
        maxBytes=500000,  # Reduced from 1MB to 500KB
        backupCount=2  # Reduced from 5 to 2
    )
    handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s: %(message)s'
    ))
    logging.basicConfig(handlers=[handler], level=logging.INFO)


# Cache utilities with reduced complexity
def get_cache_key(lat: float, lon: float) -> str:
    """Simpler cache key generation"""
    return f"{round(lat, 2)}_{round(lon, 2)}"  # Reduced precision


def get_cached_weather(lat: float, lon: float) -> dict:
    """Get weather data from cache with simpler implementation"""
    cache_file = app.config['CACHE_DIR'] / f"{get_cache_key(lat, lon)}.json"

    if not cache_file.exists():
        return None

    try:
        mtime = datetime.fromtimestamp(cache_file.stat().st_mtime)
        if datetime.now() - mtime > timedelta(hours=app.config['CACHE_TTL_HOURS']):
            return None

        with open(cache_file, 'r') as f:
            return json.load(f)
    except Exception:
        return None


def set_cached_weather(lat: float, lon: float, weather_data: dict):
    """Save weather data to cache with basic error handling"""
    try:
        app.config['CACHE_DIR'].mkdir(exist_ok=True)
        cache_file = app.config['CACHE_DIR'] / f"{get_cache_key(lat, lon)}.json"

        with open(cache_file, 'w') as f:
            json.dump(weather_data, f)
    except Exception:
        pass


def clean_cache():
    """Simplified cache cleaning"""
    try:
        files = list(app.config['CACHE_DIR'].glob('*.json'))
        if len(files) > app.config['MAX_CACHE_SIZE']:
            # Remove oldest files first
            files.sort(key=os.path.getmtime)
            for f in files[:len(files) - app.config['MAX_CACHE_SIZE']]:
                try:
                    f.unlink()
                except Exception:
                    continue
    except Exception:
        pass


# Request validation decorator
def validate_coordinates(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            lat = float(request.args.get('lat'))
            lon = float(request.args.get('lon'))
            if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
                return jsonify({"error": "Invalid coordinates"}), 400
            return f(*args, **kwargs)
        except (TypeError, ValueError):
            return jsonify({"error": "Missing or invalid coordinates"}), 400

    return decorated_function


# Humidity calculations (kept as is but with fewer logs)
def calculate_absolute_humidity(temp_c, relative_humidity):
    """Calculate absolute humidity (g/m³) with minimal logging"""
    if temp_c is None or relative_humidity is None:
        return None

    try:
        R = 8.314462618
        mw = 18.01528
        es = 6.112 * math.exp((17.67 * temp_c) / (temp_c + 243.5))
        e = es * (relative_humidity / 100.0)
        temp_k = temp_c + 273.15
        absolute_humidity = (e * mw) / (R * temp_k) * 100
        return round(absolute_humidity, 2)
    except Exception:
        return None


def calculate_relative_humidity_for_room(absolute_humidity, room_temp_c):
    """Calculate relative humidity for room temperature with minimal logging"""
    if absolute_humidity is None or room_temp_c is None:
        return None

    try:
        R = 8.314462618
        mw = 18.01528
        es_room = 6.112 * math.exp((17.67 * room_temp_c) / (room_temp_c + 243.5))
        temp_k = room_temp_c + 273.15
        e_room = (absolute_humidity * R * temp_k) / (mw * 100)
        relative_humidity_room = (e_room / es_room) * 100
        return round(relative_humidity_room, 1)
    except Exception:
        return None


# Main endpoint with reduced logging and simplified logic
@app.route('/get_humidity_info', methods=['GET'])
@validate_coordinates
def get_humidity_info():
    start_time = time.time()
    lat = request.args.get('lat', type=float)
    lon = request.args.get('lon', type=float)
    room_temp = request.args.get('room_temp', default=22.0, type=float)

    try:
        # Try cache first
        cached_data = get_cached_weather(lat, lon)
        if cached_data:
            data = cached_data
            from_cache = True
        else:
            # Fetch from API if not in cache
            params = {
                'lat': lat,
                'lon': lon,
                'appid': app.config['OWM_API_KEY'],
                'units': 'metric'
            }

            response = requests.get(
                "https://api.openweathermap.org/data/2.5/weather",
                params=params,
                timeout=5  # Reduced timeout from 10 to 5 seconds
            )

            if response.status_code != 200:
                return jsonify({
                    'error': 'Weather data unavailable',
                    'details': response.json().get('message', 'Unknown error')
                }), 502

            data = response.json()
            set_cached_weather(lat, lon, data)
            from_cache = False

        # Process data
        temp_c = data['main']['temp']
        relative_humidity = data['main']['humidity']
        abs_humidity = calculate_absolute_humidity(temp_c, relative_humidity)
        room_rh = calculate_relative_humidity_for_room(abs_humidity, room_temp)

        if abs_humidity is None or room_rh is None:
            return jsonify({'error': 'Calculation failed'}), 500

        return jsonify({
            'location': data.get('name', 'Unknown'),
            'outdoor': {
                'temperature': temp_c,
                'humidity': relative_humidity,
                'absolute_humidity': abs_humidity
            },
            'indoor': {
                'temperature': room_temp,
                'estimated_humidity': room_rh
            },
            'cache_used': from_cache
        })

    except requests.exceptions.Timeout:
        return jsonify({'error': 'Weather service timeout'}), 504
    except Exception as e:
        return jsonify({'error': 'Internal server error'}), 500


# Minimal health check
@app.route('/health')
def health_check():
    return jsonify({"status": "ok"})


# Initialize application
if __name__ == '__main__':
    setup_logging()
    app.config['CACHE_DIR'].mkdir(exist_ok=True)
    clean_cache()

    # Run with reduced workers and timeout
    app.run(
        host='0.0.0.0',
        port=5000,
        threaded=True,  # Use threads instead of processes
        debug=False  # Disable debug mode for production
    )