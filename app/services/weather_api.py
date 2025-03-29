import requests
import logging
from typing import Optional, Dict
from datetime import datetime, timedelta
from flask import current_app
from pathlib import Path
import json


class WeatherAPI:
    """Класс для работы с OpenWeatherMap API"""

    def __init__(self):
        self.base_url = "https://api.openweathermap.org/data/2.5/weather"
        self.timeout = 5  # секунд
        self.cache_dir = Path(current_app.config['CACHE_DIR'])
        self.cache_ttl = timedelta(hours=current_app.config['CACHE_TTL_HOURS'])

    def _get_cache_key(self, lat: float, lon: float) -> str:
        """Генерация ключа для кэша"""
        return f"weather_{round(lat, 2)}_{round(lon, 2)}.json"

    def _read_from_cache(self, lat: float, lon: float) -> Optional[Dict]:
        """Чтение данных из кэша"""
        cache_file = self.cache_dir / self._get_cache_key(lat, lon)

        try:
            if not cache_file.exists():
                return None

            mtime = datetime.fromtimestamp(cache_file.stat().st_mtime)
            if datetime.now() - mtime > self.cache_ttl:
                return None

            with open(cache_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            logging.warning(f"Cache read failed: {str(e)}")
            return None

    def _save_to_cache(self, lat: float, lon: float, data: Dict):
        """Сохранение данных в кэш"""
        try:
            self.cache_dir.mkdir(exist_ok=True)
            cache_file = self.cache_dir / self._get_cache_key(lat, lon)

            with open(cache_file, 'w') as f:
                json.dump(data, f)
        except Exception as e:
            logging.error(f"Cache write failed: {str(e)}")

    def get_weather_data(self, lat: float, lon: float) -> Dict:
        """
        Получение данных о погоде по координатам

        Args:
            lat: Широта
            lon: Долгота

        Returns:
            Словарь с данными о погоде

        Raises:
            requests.exceptions.RequestException: При ошибках запроса
        """
        # Пробуем получить данные из кэша
        cached_data = self._read_from_cache(lat, lon)
        if cached_data:
            logging.info(f"Using cached data for {lat},{lon}")
            cached_data['from_cache'] = True
            return cached_data

        # Параметры запроса
        params = {
            'lat': lat,
            'lon': lon,
            'appid': current_app.config['OWM_API_KEY'],
            'units': 'metric',
            'lang': 'ru'
        }

        try:
            # Выполнение запроса к API
            response = requests.get(
                self.base_url,
                params=params,
                timeout=self.timeout
            )
            response.raise_for_status()

            data = response.json()
            data['from_cache'] = False

            # Сохраняем в кэш
            self._save_to_cache(lat, lon, data)

            return data

        except requests.exceptions.Timeout:
            logging.error("OpenWeatherMap API timeout")
            raise
        except requests.exceptions.RequestException as e:
            logging.error(f"OpenWeatherMap API error: {str(e)}")
            raise

    def extract_weather_info(self, weather_data: Dict) -> Dict:
        """
        Извлечение и форматирование основных данных о погоде

        Args:
            weather_data: Сырые данные от API

        Returns:
            Форматированные данные для ответа
        """
        if not weather_data:
            return {}

        main = weather_data.get('main', {})
        weather = weather_data.get('weather', [{}])[0]

        return {
            'location': weather_data.get('name', 'Unknown'),
            'temperature': main.get('temp'),
            'humidity': main.get('humidity'),
            'pressure': main.get('pressure'),
            'description': weather.get('description', ''),
            'icon': weather.get('icon'),
            'wind_speed': weather_data.get('wind', {}).get('speed'),
            'clouds': weather_data.get('clouds', {}).get('all'),
            'timestamp': weather_data.get('dt')
        }