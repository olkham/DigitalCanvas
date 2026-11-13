"""System utilities - OS detection, UUID, admin privileges."""

import os
import platform
import subprocess
import hashlib
import base64
import uuid
import ctypes
from functools import lru_cache


@lru_cache(maxsize=1)
def is_raspberry_pi():
    """Check if running on Raspberry Pi."""
    try:
        with open('/proc/device-tree/model') as model_file:
            model = model_file.read().lower()
            return 'raspberry pi' in model
    except FileNotFoundError:
        return False


@lru_cache(maxsize=1)
def get_system_uuid():
    """Get system UUID (cached)."""
    try:
        if platform.system() == "Windows":
            cmd = 'wmic csproduct get uuid'
            _uuid = subprocess.check_output(cmd).decode().split('\n')[1].strip()
        elif platform.system() == "Linux":
            if is_raspberry_pi():
                cmd = 'cat /proc/cpuinfo | grep Serial | cut -d " " -f 2'
                _uuid = subprocess.check_output(cmd, shell=True).decode().strip()
            else:
                cmd = 'cat /sys/class/dmi/id/product_uuid'
                _uuid = subprocess.check_output(cmd, shell=True).decode().strip()
        else:
            print("Unsupported OS")
            _uuid = uuid.uuid4()
    except Exception as e:
        print(f"Error getting system UUID: {e}")
        _uuid = uuid.uuid4()
    return _uuid


@lru_cache(maxsize=1)
def get_short_system_uuid():
    """Get shortened system UUID (cached)."""
    try:
        system_uuid = get_system_uuid()
        if system_uuid:
            hash_obj = hashlib.sha256(system_uuid.encode())
            b64_encoded = base64.urlsafe_b64encode(hash_obj.digest())
            short_uuid = b64_encoded[:16].decode()
            return short_uuid
        else:
            return None
    except Exception as e:
        print(f"Error creating short UUID: {e}")
        return None


@lru_cache(maxsize=1)
def check_os():
    """Check and return the operating system type (cached)."""
    if platform.system() == "Windows":
        return "Windows"
    elif platform.system() == "Linux":
        if is_raspberry_pi():
            return "Raspberry Pi"
        else:
            return "Linux"
    elif platform.system() == "Darwin":
        return "Mac"
    else:
        return "Unsupported OS"


def check_admin_privileges():
    """Check if running with admin/root privileges."""
    if os.name == 'nt':
        try:
            return ctypes.windll.shell32.IsUserAnAdmin() == 1
        except:
            return False
    elif os.name == 'posix':
        return os.getuid() == 0
    else:
        return False
