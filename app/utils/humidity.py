import math
from typing import Optional


def calculate_absolute_humidity(temp_c: float, relative_humidity: float) -> Optional[float]:
    """
    Calculate absolute humidity in g/m³ based on temperature and relative humidity.

    Args:
        temp_c: Temperature in Celsius
        relative_humidity: Relative humidity percentage (0-100)

    Returns:
        Absolute humidity in g/m³ rounded to 2 decimal places or None if calculation fails
    """
    if temp_c is None or relative_humidity is None:
        return None

    try:
        # Constants
        R = 8.314462618  # Universal gas constant (J/(mol·K))
        mw = 18.01528  # Molecular weight of water (g/mol)

        # Calculate saturation vapor pressure (hPa)
        es = 6.112 * math.exp((17.67 * temp_c) / (temp_c + 243.5))

        # Calculate actual vapor pressure (hPa)
        e = es * (relative_humidity / 100.0)

        # Convert temperature to Kelvin
        temp_k = temp_c + 273.15

        # Calculate absolute humidity (g/m³)
        absolute_humidity = (e * mw) / (R * temp_k) * 100

        return round(absolute_humidity, 2)
    except (ValueError, ZeroDivisionError, OverflowError):
        return None


def calculate_relative_humidity_for_room(
        absolute_humidity: float,
        room_temp_c: float
) -> Optional[float]:
    """
    Calculate relative humidity for room temperature based on absolute humidity.

    Args:
        absolute_humidity: Absolute humidity in g/m³
        room_temp_c: Room temperature in Celsius

    Returns:
        Relative humidity percentage (0-100) rounded to 1 decimal place or None if calculation fails
    """
    if absolute_humidity is None or room_temp_c is None:
        return None

    try:
        # Constants
        R = 8.314462618  # Universal gas constant (J/(mol·K))
        mw = 18.01528  # Molecular weight of water (g/mol)

        # Calculate saturation vapor pressure at room temperature (hPa)
        es_room = 6.112 * math.exp((17.67 * room_temp_c) / (room_temp_c + 243.5))

        # Convert temperature to Kelvin
        temp_k = room_temp_c + 273.15

        # Calculate actual vapor pressure (hPa)
        e_room = (absolute_humidity * R * temp_k) / (mw * 100)

        # Calculate relative humidity percentage
        relative_humidity_room = (e_room / es_room) * 100

        return round(relative_humidity_room, 1)
    except (ValueError, ZeroDivisionError, OverflowError):
        return None