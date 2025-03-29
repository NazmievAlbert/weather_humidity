from flask import Blueprint, jsonify, request
from app.utils.validation import validate_coordinates
from app.services.weather_api import get_weather_data

humidity_bp = Blueprint('humidity', __name__)

@humidity_bp.route('/get_humidity_info', methods=['GET'])
@validate_coordinates
def get_humidity():
    # Логика обработки запроса
    pass
