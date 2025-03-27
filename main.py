import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime, timedelta
import time
from flask import Flask, request, jsonify
import requests
import math
import os
from dotenv import load_dotenv
import json
from pathlib import Path
import hashlib
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from functools import wraps
from apscheduler.schedulers.background import BackgroundScheduler
import atexit
import signal
from prometheus_flask_exporter import PrometheusMetrics

# Load environment variables
load_dotenv()

# Initialize Flask app
app = Flask(__name__)
metrics = PrometheusMetrics(app)
metrics.info('app_info', 'Weather Service Info', version='1.0.0')


# Configuration
class Config:
    OWM_API_KEY = os.getenv('OWM_API_KEY')
    LOG_DIR = os.getenv('LOG_DIR', 'logs')
    CACHE_TTL = timedelta(hours=int(os.getenv('CACHE_TTL_HOURS', 1)))
    CACHE_DIR = Path(os.getenv('CACHE_DIR', 'weather_cache'))
    MAX_CACHE_SIZE = int(os.getenv('MAX_CACHE_SIZE', 1000))


app.config.from_object(Config)


# Initialize cache
def init_cache():
    """Initialize cache directory"""
    app.config.CACHE_DIR.mkdir(exist_ok=True)
    app.logger.info(f"Cache directory initialized at {app.config.CACHE_DIR.absolute()}")


# Cache utilities
def get_cache_key(lat: float, lon: float) -> str:
    """Generate cache key based on coordinates"""
    key = f"{round(lat, 4)}_{round(lon, 4)}"
    return hashlib.md5(key.encode()).hexdigest()


def get_cached_weather(lat: float, lon: float) -> dict:
    """Get weather data from cache"""
    cache_file = app.config.CACHE_DIR / f"{get_cache_key(lat, lon)}.json"

    if not cache_file.exists():
        return None

    try:
        with open(cache_file, 'r') as f:
            data = json.load(f)

        cache_time = datetime.fromisoformat(data['timestamp'])
        if datetime.now() - cache_time < app.config.CACHE_TTL:
            app.logger.debug(f"Cache hit for {cache_file.name}")
            return data['weather_data']

        app.logger.debug(f"Cache expired for {cache_file.name}")
    except Exception as e:
        app.logger.error(f"Error reading cache file {cache_file}: {e}")

    return None


def set_cached_weather(lat: float, lon: float, weather_data: dict):
    """Save weather data to cache"""
    cache_file = app.config.CACHE_DIR / f"{get_cache_key(lat, lon)}.json"

    data = {
        'timestamp': datetime.now().isoformat(),
        'coordinates': {'lat': lat, 'lon': lon},
        'weather_data': weather_data
    }

    try:
        with open(cache_file, 'w') as f:
            json.dump(data, f, indent=2)
        app.logger.debug(f"Weather data cached to {cache_file.name}")
    except Exception as e:
        app.logger.error(f"Error writing cache file {cache_file}: {e}")


def clean_expired_cache():
    """Clean expired cache entries"""
    now = datetime.now()
    deleted = 0

    for cache_file in app.config.CACHE_DIR.glob('*.json'):
        try:
            with open(cache_file, 'r') as f:
                data = json.load(f)

            cache_time = datetime.fromisoformat(data['timestamp'])
            if now - cache_time >= app.config.CACHE_TTL:
                cache_file.unlink()
                deleted += 1
        except Exception as e:
            app.logger.error(f"Error cleaning cache file {cache_file}: {e}")
            continue

    if deleted:
        app.logger.info(f"Cleaned {deleted} expired cache files")


def clean_cache():
    """Clean cache based on both TTL and size"""
    clean_expired_cache()

    # Remove oldest files if cache is too big
    files = sorted(app.config.CACHE_DIR.glob('*.json'), key=os.path.getmtime)
    while len(files) > app.config.MAX_CACHE_SIZE:
        try:
            files[0].unlink()
            files = files[1:]
            app.logger.info(f"Removed oldest cache file to maintain size limit")
        except Exception as e:
            app.logger.error(f"Error removing cache file: {e}")
            break


# Setup logging
def setup_logging():
    """Configure logging system"""
    if not os.path.exists(app.config.LOG_DIR):
        os.makedirs(app.config.LOG_DIR)

    log_file = os.path.join(app.config.LOG_DIR, 'weather_service.log')

    handler = RotatingFileHandler(
        log_file, maxBytes=1000000, backupCount=5
    )
    handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
    ))

    app.logger.addHandler(handler)
    app.logger.setLevel(logging.INFO)


# Rate limiting
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["2000 per day", "100 per hour"]
)


# Error handlers
@app.errorhandler(429)
def ratelimit_handler(e):
    return jsonify({
        "error": "Rate limit exceeded",
        "message": str(e.description)
    }), 429


# Request validation decorator
def validate_coordinates(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        lat = request.args.get('lat', type=float)
        lon = request.args.get('lon', type=float)

        if lat is None or lon is None:
            return jsonify({"error": "Missing coordinates"}), 400
        if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
            return jsonify({"error": "Invalid coordinates"}), 400

        return f(*args, **kwargs)

    return decorated_function


# API interaction logging
def log_owm_interaction(url, params, response, duration):
    """Log OpenWeatherMap API interactions"""
    log_data = {
        'timestamp': datetime.utcnow().isoformat(),
        'api_endpoint': url,
        'request_params': {**params, 'appid': 'REDACTED'},  # Hide API key
        'response_status': response.status_code,
        'response_data': response.json() if response.status_code == 200 else None,
        'processing_time_sec': duration
    }

    app.logger.info("OpenWeatherMap API Interaction", extra={'data': log_data})


# Humidity calculations
def calculate_absolute_humidity(temp_c, relative_humidity):
    """Calculate absolute humidity (g/m³)"""
    try:
        if temp_c is None or relative_humidity is None:
            app.logger.warning("Invalid input for humidity calculation")
            return None

        R = 8.314462618
        mw = 18.01528

        es = 6.112 * math.exp((17.67 * temp_c) / (temp_c + 243.5))
        e = es * (relative_humidity / 100.0)
        temp_k = temp_c + 273.15
        absolute_humidity = (e * mw) / (R * temp_k) * 100

        app.logger.debug(
            f"Calculated absolute humidity: {absolute_humidity:.2f} g/m³ from "
            f"temp: {temp_c}°C, RH: {relative_humidity}%"
        )

        return round(absolute_humidity, 2)
    except Exception as e:
        app.logger.error(f"Error in humidity calculation: {str(e)}")
        return None


def calculate_relative_humidity_for_room(absolute_humidity, room_temp_c):
    """Calculate relative humidity for room temperature"""
    try:
        if absolute_humidity is None or room_temp_c is None:
            app.logger.warning("Invalid input for room humidity calculation")
            return None

        R = 8.314462618
        mw = 18.01528

        es_room = 6.112 * math.exp((17.67 * room_temp_c) / (room_temp_c + 243.5))
        temp_k = room_temp_c + 273.15
        e_room = (absolute_humidity * R * temp_k) / (mw * 100)
        relative_humidity_room = (e_room / es_room) * 100

        app.logger.debug(
            f"Calculated room RH: {relative_humidity_room:.1f}% at {room_temp_c}°C "
            f"from AH: {absolute_humidity}g/m³"
        )

        return round(relative_humidity_room, 1)
    except Exception as e:
        app.logger.error(f"Error in room humidity calculation: {str(e)}")
        return None


# API Endpoints
@app.route('/get_humidity_info', methods=['GET'])
@validate_coordinates
@limiter.limit("10 per minute")
def get_humidity_info():
    start_time = time.time()
    request_id = f"req-{datetime.utcnow().strftime('%Y%m%d-%H%M%S-%f')}"

    app.logger.info(
        f"Incoming request {request_id} from {request.remote_addr}",
        extra={'request_args': dict(request.args)}
    )

    lat = request.args.get('lat', type=float)
    lon = request.args.get('lon', type=float)
    room_temp = request.args.get('room_temp', default=22.0, type=float)

    try:
        cached_data = get_cached_weather(lat, lon)

        if cached_data:
            data = cached_data
            from_cache = True
        else:
            params = {
                'lat': lat,
                'lon': lon,
                'appid': app.config.OWM_API_KEY,
                'units': 'metric'
            }

            app.logger.debug(
                f"Preparing OWM API request {request_id}",
                extra={'api_params': {**params, 'appid': 'REDACTED'}}
            )

            api_start = time.time()
            response = requests.get("https://api.openweathermap.org/data/2.5/weather",
                                    params=params, timeout=10)
            api_duration = time.time() - api_start

            log_owm_interaction("https://api.openweathermap.org/data/2.5/weather",
                                params, response, api_duration)

            if response.status_code != 200:
                app.logger.error(
                    f"OWM API error in request {request_id}",
                    extra={
                        'status_code': response.status_code,
                        'response': response.text
                    }
                )
                return jsonify({
                    'error': 'Ошибка при получении данных о погоде',
                    'api_error': response.json().get('message', 'Unknown error'),
                    'request_id': request_id
                }), 502

            data = response.json()
            set_cached_weather(lat, lon, data)
            from_cache = False

        temp_c = data['main']['temp']
        relative_humidity = data['main']['humidity']
        location = data.get('name', 'Unknown location')
        abs_humidity = calculate_absolute_humidity(temp_c, relative_humidity)

        if abs_humidity is None:
            app.logger.error(f"Calculation failed for request {request_id}")
            return jsonify({
                'error': 'Не удалось рассчитать абсолютную влажность',
                'request_id': request_id
            }), 500

        room_rh = calculate_relative_humidity_for_room(abs_humidity, room_temp)
        total_duration = time.time() - start_time

        result = {
            'request_id': request_id,
            'location': location,
            'coordinates': {'lat': lat, 'lon': lon},
            'outdoor_weather': {
                'temperature_c': temp_c,
                'relative_humidity': relative_humidity,
                'absolute_humidity_g_m3': abs_humidity
            },
            'indoor_estimation': {
                'room_temperature_c': room_temp,
                'estimated_relative_humidity': room_rh,
                'absolute_humidity_g_m3': abs_humidity
            },
            'processing_time_sec': total_duration,
            'data_source': 'OpenWeatherMap',
            'cache_info': {
                'used_cache': from_cache,
                'cache_expires': (datetime.now() + app.config.CACHE_TTL).isoformat()
                if not from_cache else None,
                'cache_ttl_hours': app.config.CACHE_TTL.total_seconds() / 3600
            }
        }

        app.logger.info(f"Successful response for request {request_id}")
        return jsonify(result)

    except Exception as e:
        app.logger.error(f"Unexpected error in request {request_id}", exc_info=True)
        return jsonify({
            'error': 'Внутренняя ошибка сервера',
            'request_id': request_id,
            'details': str(e)
        }), 500


@app.route('/health')
def health_check():
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "cache_size": len(list(app.config.CACHE_DIR.glob('*.json')))
    })


@app.route('/docs')
def api_docs():
    return jsonify({
        "endpoints": {
            "/get_humidity_info": {
                "description": "Get humidity information",
                "parameters": {
                    "lat": "Latitude (required)",
                    "lon": "Longitude (required)",
                    "room_temp": "Room temperature in Celsius (default: 22.0)"
                },
                "rate_limit": "10 requests per minute"
            },
            "/health": {
                "description": "Service health check"
            },
            "/docs": {
                "description": "API documentation"
            }
        }
    })


# Background tasks and shutdown handling
scheduler = BackgroundScheduler()
scheduler.add_job(clean_cache, 'interval', hours=1)
scheduler.start()


def handle_shutdown(signum, frame):
    """Handle graceful shutdown"""
    app.logger.info("Shutting down...")
    clean_cache()
    scheduler.shutdown()
    exit(0)


signal.signal(signal.SIGTERM, handle_shutdown)
signal.signal(signal.SIGINT, handle_shutdown)
atexit.register(lambda: scheduler.shutdown())

# Initialize application
if __name__ == '__main__':
    setup_logging()
    init_cache()
    clean_cache()

    app.run(host='0.0.0.0', port=5000, debug=True)