from functools import wraps
from flask import request, jsonify
from typing import Tuple, Optional


def validate_coordinates(f):
    """
    Декоратор для проверки координат в запросе.
    Проверяет наличие и корректность параметров lat и lon.
    """

    @wraps(f)
    def wrapper(*args, **kwargs):
        # Получаем параметры из запроса
        lat = request.args.get('lat', type=float)
        lon = request.args.get('lon', type=float)

        # Проверяем наличие параметров
        if lat is None or lon is None:
            return jsonify({"error": "Missing coordinates parameters"}), 400

        # Проверяем диапазон значений
        if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
            return jsonify({
                "error": "Invalid coordinates range",
                "details": {
                    "latitude": "Must be between -90 and 90",
                    "longitude": "Must be between -180 and 180"
                }
            }), 400

        return f(*args, **kwargs)

    return wrapper


def validate_room_temp(f):
    """
    Декоратор для проверки комнатной температуры.
    Проверяет необязательный параметр room_temp.
    """

    @wraps(f)
    def wrapper(*args, **kwargs):
        room_temp = request.args.get('room_temp', default=22.0, type=float)

        if not (10 <= room_temp <= 40):  # Реалистичный диапазон для комнатной температуры
            return jsonify({
                "error": "Invalid room temperature",
                "details": "Must be between 10 and 40°C"
            }), 400

        return f(*args, **kwargs)

    return wrapper


def validate_api_key(f):
    """
    Декоратор для проверки API ключа (если требуется аутентификация)
    """

    @wraps(f)
    def wrapper(*args, **kwargs):
        api_key = request.headers.get('X-API-KEY')

        if not api_key or api_key != current_app.config['API_KEYS'].get(api_key):
            return jsonify({
                "error": "Unauthorized",
                "details": "Invalid or missing API key"
            }), 401

        return f(*args, **kwargs)

    return wrapper


def validate_input_data(schema: dict):
    """
    Универсальный валидатор для входных данных по схеме
    """

    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            data = request.get_json()
            errors = {}

            for field, rules in schema.items():
                value = data.get(field)

                # Проверка обязательных полей
                if rules.get('required') and value is None:
                    errors[field] = "This field is required"
                    continue

                # Проверка типа
                if value is not None and not isinstance(value, rules.get('type')):
                    errors[field] = f"Must be {rules.get('type').__name__}"

                # Дополнительные проверки
                if 'min' in rules and value < rules['min']:
                    errors[field] = f"Must be at least {rules['min']}"

                if 'max' in rules and value > rules['max']:
                    errors[field] = f"Must be at most {rules['max']}"

            if errors:
                return jsonify({
                    "error": "Validation failed",
                    "details": errors
                }), 400

            return f(*args, **kwargs)

        return wrapper

    return decorator
