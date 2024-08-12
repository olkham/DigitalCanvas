import os
from PIL import Image
import requests
from io import BytesIO
import subprocess
import platform
import hashlib
import base64
import re
import uuid
import os
import ctypes


def check_and_create(dirpath):
    if not os.path.exists(dirpath):
            os.makedirs(dirpath)

def create_thumbnail(image_path, thumbnail_path, size=(200, 200)):
    with Image.open(image_path) as img:
        img.thumbnail(size, Image.LANCZOS)
        img.save(thumbnail_path)

def replace_webp_extension(filename):
    # Use regex to find the original extension before .webp
    match = re.search(r'\.(jpg|jpeg|png|bmp)\.webp$', filename)
    if match:
        original_extension = match.group(1)
        filename = filename.replace(f'.{original_extension}.webp', f'.{original_extension}')
    else :
        # If the filename does not have the .webp extension, replace the .webp extension with .jpg
        if filename.endswith('.webp'):
            filename = filename.replace('.webp', '.jpg')
    return filename

def save_remote_image(image_url, upload_folder, size=None):
    try:
        response = requests.get(image_url)
        response.raise_for_status()
        image = Image.open(BytesIO(response.content))        
        filename = os.path.basename(image_url)
        file_path = os.path.join(upload_folder, filename)
        file_path = replace_webp_extension(file_path)
        image.save(file_path)
        return filename
    except Exception as e:
        print(f"Failed to fetch image: {e}")
        return None
    
def create_thumbnails_for_existing_images(images, thumbs):
    for filename in os.listdir(images):
        file_path = os.path.join(images, filename)
        thumbnail_path = os.path.join(thumbs, filename)
        if not os.path.exists(thumbnail_path):
            create_thumbnail(file_path, thumbnail_path)

def is_raspberry_pi():
    try:
        with open('/proc/device-tree/model') as model_file:
            model = model_file.read().lower()
            return 'raspberry pi' in model
    except FileNotFoundError:
        return False
            
def get_system_uuid():
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

def get_short_system_uuid():
    try:
        uuid = get_system_uuid()  # Assuming get_system_uuid() is defined elsewhere and returns the system's UUID as a string
        if uuid:
            # Hash the UUID
            hash_obj = hashlib.sha256(uuid.encode())
            # Convert to base64 for a shorter representation
            b64_encoded = base64.urlsafe_b64encode(hash_obj.digest())
            # Truncate to desired length, e.g., the first 16 characters
            short_uuid = b64_encoded[:16].decode()
            return short_uuid
        else:
            return None
    except Exception as e:
        print(f"Error creating short UUID: {e}")
        return None

def is_portrait(image_path):
    with Image.open(image_path) as img:
        return img.height > img.width

def is_landscape(image_path):
    with Image.open(image_path) as img:
        return img.width > img.height
    

#if the screen is landscape and the self.orientation is landscape, resize the image to fill the screen keeping the aspect ratio
#if the screen is portrait and the self.orientation is portrait, resize the image to fill the screen keeping the aspect ratio
#if the screen is landscape and the self.orientation is portrait, resize the image to fill the screen keeping the aspect ratio
#if the screen is portrait and the self.orientation is landscape, resize the image to fill the screen keeping the aspect ratio
#if the screen is landscape and the self.orientation is both, resize the landscape image to fill the screen keeping the aspect ratio, but if the image is portrait, resize the image to fit the height of the screen
#if the screen is portrait and the self.orientation is both, resize the portrait image to fill the screen keeping the aspect ratio, but if the image is landscape, resize the image to fit the width of the screen
def resize_image(image, screen_width, screen_height, orientation, rotation):
    image_width, image_height = image.size

    screen_orientation = 'landscape' if screen_width > screen_height else 'portrait'
    image_orientation = 'landscape' if image_width > image_height else 'portrait'

    if rotation == 90 or rotation == 270:
        screen_orientation = 'portrait' if screen_orientation == 'landscape' else 'landscape'

    if screen_orientation == 'landscape' and orientation == 'landscape':
        new_width, new_height = resize_to_fill(image_width, image_height, screen_width, screen_height)
    elif screen_orientation == 'portrait' and orientation == 'portrait':
        new_width, new_height = resize_to_fill(image_width, image_height, screen_width, screen_height)
    elif screen_orientation == 'landscape' and orientation == 'portrait':
        new_width, new_height = resize_to_fill(image_width, image_height, screen_width, screen_height)
    elif screen_orientation == 'portrait' and orientation == 'landscape':
        new_width, new_height = resize_to_fill(image_width, image_height, screen_width, screen_height)
    elif screen_orientation == 'landscape' and orientation == 'both':
        if image_orientation == 'landscape':
            new_width, new_height = resize_to_fill(image_width, image_height, screen_width, screen_height)
        else:
            new_width, new_height = resize_to_fit_height(image_width, image_height, screen_height)
    elif screen_orientation == 'portrait' and orientation == 'both':
        if image_orientation == 'portrait':
            new_width, new_height = resize_to_fill(image_width, image_height, screen_width, screen_height)
        else:
            new_width, new_height = resize_to_fit_width(image_width, image_height, screen_width)

    resized_image = image.resize((new_width, new_height), Image.LANCZOS)
    return resized_image

def resize_to_fill(image_width, image_height, screen_width, screen_height):
    aspect_ratio = min(screen_width / image_width, screen_height / image_height)
    return int(image_width * aspect_ratio), int(image_height * aspect_ratio)

def resize_to_fit_height(image_width, image_height, screen_height):
    aspect_ratio = screen_height / image_height
    return int(image_width * aspect_ratio), screen_height

def resize_to_fit_width(image_width, image_height, screen_width):
    aspect_ratio = screen_width / image_width
    return screen_width, int(image_height * aspect_ratio)

def crop_center(image, size):
    '''
    Crop the image to the specified size by taking a center crop.
    '''
    width, height = image.size
    new_width, new_height = size
    left = (width - new_width) // 2
    top = (height - new_height) // 2
    right = (width + new_width) // 2
    bottom = (height + new_height) // 2
    return image.crop((left, top, right, bottom))

#function to resize the image to resize to a target size using two options: fill or fit
#fill: resize the image to fill the target size and crop the excess
#fit: resize the image to fit the target size and keep the aspect ratio
def resize_to_target(src_image, target_image, resize_option):
    
    image_width, image_height = src_image.size
    target_width, target_height = target_image.size
    
    image_aspect = image_width / image_height
    target_aspect = target_width / target_height

    if resize_option == 'fill':
        if image_aspect > target_aspect:
            new_height = target_height
            new_width = int(new_height * image_aspect)
        else:
            new_width = target_width
            new_height = int(new_width / image_aspect)
    elif resize_option == 'fit':
        if image_aspect > target_aspect:
            new_width = target_width
            new_height = int(new_width / image_aspect)
        else:
            new_height = target_height
            new_width = int(new_height * image_aspect)

    resized_image = src_image.resize((new_width, new_height), Image.LANCZOS)

    if resize_option == 'fill':
        left = (new_width - target_width) / 2
        top = (new_height - target_height) / 2
        right = left + target_width
        bottom = top + target_height
        return resized_image.crop((left, top, right, bottom))
    else:
        return resized_image
    
#read an image as PIL Image from a URL
def read_image_from_url(image_url):
    response = requests.get(image_url)
    image = Image.open(BytesIO(response.content))
    return image

def get_thumbnail(json_data):
    metadata = json_data.get('Metadata', {})
    library_section_type = metadata.get('librarySectionType')
    
    if library_section_type == 'movie':
        thumb_url = metadata.get('thumb')
    elif library_section_type == 'show':
        thumb_url = metadata.get('grandparentThumb')
    else:
        thumb_url = metadata.get('parentThumb')
        
    return None if thumb_url == 'null' else thumb_url

def strtobool (val):
    """Convert a string representation of truth to true (1) or false (0).
    True values are 'y', 'yes', 't', 'true', 'on', and '1'; false values
    are 'n', 'no', 'f', 'false', 'off', and '0'.  Raises ValueError if
    'val' is anything else.
    """
    if val is None:
        return None
    
    if not isinstance(val, str):
        raise ValueError("not a string: %r" % (val,))
    
    val = val.lower()
    if val in ('y', 'yes', 't', 'true', 'on', '1'):
        return 1
    elif val in ('n', 'no', 'f', 'false', 'off', '0'):
        return 0
    else:
        raise ValueError("invalid truth value %r" % (val,))
    
def accel_to_orientation(accel):
    # x, y, z = accel
    # print(f'x: {x}, y: {y}, z: {z}')
    if abs(accel['ax']) > abs(accel['ay']):
        return 'landscape'
    return 'portrait'

def clamp(value, min_value, max_value):
    return max(min(value, max_value), min_value)

def rescale_brightness(brightness, min_value=0, max_value=100):
    return int((brightness / 100) * (max_value - min_value) + min_value)

def rescale_luminance(luminance, min_value=300, max_value=2000):
    return int((luminance / 100) * (max_value - min_value) + min_value)

def luminance_to_brightness(luminance, min_value=300, max_value=2000):
    brightness = (rescale_luminance(luminance, min_value, max_value) / max_value) * 100
    brightness = clamp(brightness, 0, 100)
    return int(brightness)

def check_os():
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
    if os.name == 'nt':
        # Windows
        try:
            return ctypes.windll.shell32.IsUserAnAdmin()==1
        except:
            return False
    elif os.name == 'posix':
        # Linux and Mac
        return os.getuid() == 0
    else:
        return False

