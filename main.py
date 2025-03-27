import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime
import time
from flask import Flask, request, jsonify
import requests
import math
import os
from dotenv import load_dotenv
import json
import os
from pathlib import Path
from datetime import datetime, timedelta
import hashlib
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address



# Загрузка переменных окружения
load_dotenv()
app = Flask(__name__)
# Конфигурация кэша
CACHE_DIR = Path('weather_cache')
CACHE_TTL = timedelta(hours=1)  # Время жизни кэша


def init_cache():
    """Инициализация кэш-директории"""
    CACHE_DIR.mkdir(exist_ok=True)
    app.logger.info(f"Cache directory initialized at {CACHE_DIR.absolute()}")


def get_cache_key(lat: float, lon: float) -> str:
    """Генерация ключа кэша на основе координат"""
    key = f"{round(lat, 4)}_{round(lon, 4)}"
    return hashlib.md5(key.encode()).hexdigest()


def get_cached_weather(lat: float, lon: float) -> dict:
    """Получить данные из кэша"""
    cache_file = CACHE_DIR / f"{get_cache_key(lat, lon)}.json"

    if not cache_file.exists():
        return None

    try:
        with open(cache_file, 'r') as f:
            data = json.load(f)

        cache_time = datetime.fromisoformat(data['timestamp'])
        if datetime.now() - cache_time < CACHE_TTL:
            app.logger.debug(f"Cache hit for {cache_file.name}")
            return data['weather_data']

        app.logger.debug(f"Cache expired for {cache_file.name}")
    except Exception as e:
        app.logger.error(f"Error reading cache file {cache_file}: {e}")

    return None


def set_cached_weather(lat: float, lon: float, weather_data: dict):
    """Сохранить данные в кэш"""
    cache_file = CACHE_DIR / f"{get_cache_key(lat, lon)}.json"

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
    """Очистка просроченного кэша"""
    now = datetime.now()
    deleted = 0

    for cache_file in CACHE_DIR.glob('*.json'):
        try:
            with open(cache_file, 'r') as f:
                data = json.load(f)

            cache_time = datetime.fromisoformat(data['timestamp'])
            if now - cache_time >= CACHE_TTL:
                cache_file.unlink()
                deleted += 1
        except Exception as e:
            app.logger.error(f"Error cleaning cache file {cache_file}: {e}")
            continue

    if deleted:
        app.logger.info(f"Cleaned {deleted} expired cache files")

# Конфигурация логирования
def setup_logging():
    log_dir = os.getenv('LOG_DIR','logs')
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    log_file = os.path.join(log_dir, 'weather_service.log')

    handler = RotatingFileHandler(
        log_file, maxBytes=1000000, backupCount=5
    )
    handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
    ))

    app.logger.addHandler(handler)
    app.logger.setLevel(logging.INFO)



# Конфигурация API
OWM_API_KEY = os.getenv('OWM_API_KEY')
OWM_API_URL = "https://api.openweathermap.org/data/2.5/weather"

limiter = Limiter(
    app=app,
    key_func=get_remote_address,  # Ограничение по IP
    default_limits=["2000 per day", "100 per hour"]  # Лимиты по умолчанию
)

def log_owm_interaction(url, params, response, duration):
    """Логирование деталей взаимодействия с OpenWeatherMap API"""
    log_data = {
        'timestamp': datetime.utcnow().isoformat(),
        'api_endpoint': url,
        'request_params': params,
        'response_status': response.status_code,
        'response_data': response.json() if response.status_code == 200 else None,
        'processing_time_sec': duration,
        'api_key_used': OWM_API_KEY[:4] + '...' + OWM_API_KEY[-4:] if OWM_API_KEY else None
    }

    app.logger.info("OpenWeatherMap API Interaction", extra={'data': log_data})


def calculate_absolute_humidity(temp_c, relative_humidity):
    """Рассчитывает абсолютную влажность (г/м³)"""
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
    """
    Рассчитывает относительную влажность для комнатной температуры
    на основе абсолютной влажности

    Параметры:
        absolute_humidity - абсолютная влажность в г/м³
        room_temp_c - комнатная температура в °C

    Возвращает:
        relative_humidity - относительная влажность в %
    """
    try:
        if absolute_humidity is None or room_temp_c is None:
            app.logger.warning("Invalid input for room humidity calculation")
            return None

        # Константы для расчета
        R = 8.314462618  # Универсальная газовая постоянная (Дж/(моль·K))
        mw = 18.01528  # Молярная масса воды (г/моль)

        # Расчет давления насыщенного пара для комнатной температуры
        es_room = 6.112 * math.exp((17.67 * room_temp_c) / (room_temp_c + 243.5))  # в гПа

        # Обратное преобразование: из абсолютной влажности в парциальное давление
        temp_k = room_temp_c + 273.15
        e_room = (absolute_humidity * R * temp_k) / (mw * 100)  # *100 для перевода Па в гПа

        # Расчет относительной влажности для комнатной температуры
        relative_humidity_room = (e_room / es_room) * 100

        app.logger.debug(
            f"Calculated room RH: {relative_humidity_room:.1f}% at {room_temp_c}°C "
            f"from AH: {absolute_humidity}g/m³"
        )

        return round(relative_humidity_room, 1)
    except Exception as e:
        app.logger.error(f"Error in room humidity calculation: {str(e)}")
        return None


@app.route('/get_humidity_info', methods=['GET'])
@limiter.limit("10 per minute")  # Специальный лимит для этого эндпоинта
def get_humidity_info():
    start_time = time.time()
    request_id = f"req-{datetime.utcnow().strftime('%Y%m%d-%H%M%S-%f')}"

    app.logger.info(
        f"Incoming request {request_id} from {request.remote_addr}",
        extra={'request_args': dict(request.args)}
    )

    # Получаем параметры запроса
    lat = request.args.get('lat', type=float)
    lon = request.args.get('lon', type=float)


    room_temp = request.args.get('room_temp', default=22.0, type=float)  # Значение по умолчанию 22°C

    if not lat or not lon:
        app.logger.warning(f"Bad request {request_id}: missing coordinates")
        return jsonify({
            'error': 'Необходимо указать координаты lat и lon',
            'request_id': request_id
        }), 400


    try:
        cached_data = get_cached_weather(lat, lon)

        if cached_data:
            data = cached_data
            from_cache = True
        else:
            # Подготовка запроса к OpenWeatherMap
            params = {
                'lat': lat,
                'lon': lon,
                'appid': OWM_API_KEY,
                'units': 'metric'
            }

            app.logger.debug(
                f"Preparing OWM API request {request_id}",
                extra={'api_params': params}
            )

            # Отправка запроса с таймаутом
            api_start = time.time()
            response = requests.get(OWM_API_URL, params=params, timeout=10)
            api_duration = time.time() - api_start

            # Логирование взаимодействия с API
            log_owm_interaction(OWM_API_URL, params, response, api_duration)

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

        # После получения данных о погоде:
        temp_c = data['main']['temp']
        relative_humidity = data['main']['humidity']
        location = data.get('name', 'Unknown location')

        # Расчет абсолютной влажности
        abs_humidity = calculate_absolute_humidity(temp_c, relative_humidity)

        if abs_humidity is None:
            app.logger.error(f"Calculation failed for request {request_id}")
            return jsonify({
                'error': 'Не удалось рассчитать абсолютную влажность',
                'request_id': request_id
            }), 500

        # Расчет относительной влажности для комнатной температуры
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
                'absolute_humidity_g_m3': abs_humidity  # остается неизменной
            },
            'processing_time_sec': total_duration,
            'data_source': 'OpenWeatherMap',
            'cache_info': {
                'used_cache': from_cache,
                'cache_expires': (datetime.now() + CACHE_TTL).isoformat()
                if not from_cache else None,
                'cache_ttl_hours': CACHE_TTL.total_seconds() / 3600
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


if __name__ == '__main__':
    setup_logging()
    init_cache()
    clean_expired_cache()

    app.run(host='0.0.0.0', port=5000, debug=True)