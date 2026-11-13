"""Math utilities - interpolation, clamping, averaging."""


def clamp(value, min_value, max_value):
    """Clamp value between min and max."""
    return max(min(value, max_value), min_value)


def lerp(value, min_val, max_val, new_min, new_max, clamp_output=True):
    """Linear interpolation from one range to another."""
    new_value = (value - min_val) / (max_val - min_val) * (new_max - new_min) + new_min
    if clamp_output:
        new_value = clamp(new_value, new_min, new_max)
    return new_value


def get_mean_value(array):
    """Calculate mean of non-None values in array."""
    values = [value for value in array if value is not None]
    if values:
        return sum(values) / len(values)
    return None


def get_mean_values(array):
    """Calculate mean of accelerometer values (ax, ay, az)."""
    x_values = [item['ax'] for item in array if item is not None and item['ax'] is not None]
    y_values = [item['ay'] for item in array if item is not None and item['ay'] is not None]
    z_values = [item['az'] for item in array if item is not None and item['az'] is not None]
    
    x_mean = sum(x_values) / len(x_values) if x_values else None
    y_mean = sum(y_values) / len(y_values) if y_values else None
    z_mean = sum(z_values) / len(z_values) if z_values else None

    return x_mean, y_mean, z_mean


def rescale_brightness(brightness, min_value=0, max_value=100):
    """Rescale brightness value to new range."""
    return int((brightness / 100) * (max_value - min_value) + min_value)


def rescale_luminance(luminance, min_value=300, max_value=2000):
    """Rescale luminance value to new range."""
    return int((luminance / 100) * (max_value - min_value) + min_value)


def luminance_to_brightness(luminance, min_value=300, max_value=2000):
    """Convert luminance reading to brightness percentage."""
    brightness = (rescale_luminance(luminance, min_value, max_value) / max_value) * 100
    brightness = clamp(brightness, 0, 100)
    return int(brightness)
