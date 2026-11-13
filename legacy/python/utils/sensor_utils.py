"""Sensor utilities - accelerometer data processing."""


def accel_to_orientation(accel):
    """Convert accelerometer data to orientation (landscape/portrait)."""
    if type(accel) is dict:
        x, y, z = accel['ax'], accel['ay'], accel['az']
    else:
        x, y, z = accel
    
    if abs(x) > abs(y):
        return 'landscape'
    return 'portrait'


def accel_to_rotation(accel):
    """Convert accelerometer data to rotation angle (0, 90, 180, 270)."""
    if type(accel) is dict:
        x, y, z = accel['ax'], accel['ay'], accel['az']
    else:
        x, y, z = accel
    
    # Invert the sign of x to match the orientation of the sensor
    x = x * -1

    if x > 0.8:
        return 0
    elif x < -0.8:
        return 180
    elif y > 0.8:
        return 90
    elif y < -0.8:
        return 270
    else:
        return 0
