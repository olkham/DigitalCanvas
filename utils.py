import os
from PIL import Image
import cv2
import numpy as np
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
        filename = check_for_duplicate_files(upload_folder, filename)
        file_path = os.path.join(upload_folder, filename)
        file_path = replace_webp_extension(file_path)
        image.save(file_path)
        return filename
    except Exception as e:
        print(f"Failed to fetch image: {e}")
        return None
    
def create_thumbnails_for_existing_images(images, thumbs):
    check_and_create(images)
    check_and_create(thumbs)
    
    for filename in os.listdir(images):
        file_path = os.path.join(images, filename)
        thumbnail_path = os.path.join(thumbs, filename)
        if not os.path.exists(thumbnail_path):
            create_thumbnail(file_path, thumbnail_path)

def check_for_duplicate_files(dir, file):
    # Check if the file already exists in the directory
    #if it does exist, add a number to the filename to make it unique
    if os.path.exists(os.path.join(dir, file)):
        base, ext = os.path.splitext(file)
        i = 1
        while os.path.exists(f"{base}_{i}{ext}"):
            i += 1
        file = f"{base}_{i}{ext}"
    return file
    
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
    
def max_usful_size(image_path, max_size):
    #scale the image so that the minimum image dimension is equal to max_size while keeping the aspect ratio
    # as save it,overwriting the original image
    # if the image is already smaller than max_size, return without any action
    with Image.open(image_path) as img:
        
        smallest_dimension = min(img.width, img.height)
        if smallest_dimension <= max_size:
            return
        
        scale_factor = max_size / smallest_dimension
        new_width = int(img.width * scale_factor)
        new_height = int(img.height * scale_factor)
        img = img.resize((new_width, new_height), Image.LANCZOS)
        img.save(image_path, quality=90)


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

def cv2_crop_center(image, size, background=None):
    '''
    Crop the image to the specified size by taking a center crop.
    If the crop size is larger than the original image, expand the image to fill the target size with black pixels.
    '''
    height, width = image.shape[:2]
    new_height, new_width = size[:2]
    
    if new_height > height or new_width > width:
        # Create a new black image with the target size
        if background is not None:
            result = background #cv2.resize(background, (new_width, new_height), interpolation=cv2.INTER_LANCZOS4)
        else:
            result = np.zeros((new_height, new_width, 3), dtype=np.uint8)
        
        # Calculate the coordinates to place the original image in the center
        left = (new_width - width) // 2
        top = (new_height - height) // 2
        right = left + width
        bottom = top + height
        
        # Place the original image in the center of the black image
        result[top:bottom, left:right] = image
        return result
    else:
        # Calculate the coordinates for the center crop
        left = (width - new_width) // 2
        top = (height - new_height) // 2
        right = left + new_width
        bottom = top + new_height
        return image[top:bottom, left:right]

def quick_read_image(image_path):
    return cv2.cvtColor(np.array(Image.open(image_path)), cv2.COLOR_RGB2BGR)

def cv2_to_pil(cv2_img):
    '''Convert OpenCV image (numpy.ndarray) to PIL Image.'''
    return Image.fromarray(cv2.cvtColor(cv2_img, cv2.COLOR_BGR2RGB))

def cv2_rotate_image(image, angle):
    '''
    Rotate the image by the specified angle and adjust the dimensions accordingly.
    '''
    if angle == 0:
        return image
    
    if angle == 90:
        # Rotate 90 degrees: transpose and then flip horizontally
        rotated_image = cv2.transpose(image)
        rotated_image = cv2.flip(rotated_image, 1)
    elif angle == 180:
        # Rotate 180 degrees: flip both horizontally and vertically
        rotated_image = cv2.flip(image, -1)
    elif angle == 270:
        # Rotate 270 degrees: transpose and then flip vertically
        rotated_image = cv2.transpose(image)
        rotated_image = cv2.flip(rotated_image, 0)
    else:
        # For other angles, use the affine transformation
        (h, w) = image.shape[:2]
        center = (w // 2, h // 2)
        
        # Calculate the rotation matrix
        M = cv2.getRotationMatrix2D(center, angle, 1.0)
        
        # Calculate the new bounding dimensions of the image
        cos = np.abs(M[0, 0])
        sin = np.abs(M[0, 1])
        
        new_w = int((h * sin) + (w * cos))
        new_h = int((h * cos) + (w * sin))
        
        # Adjust the rotation matrix to account for the new dimensions
        M[0, 2] += (new_w / 2) - center[0]
        M[1, 2] += (new_h / 2) - center[1]
        
        # Perform the affine transformation
        rotated_image = cv2.warpAffine(image, M, (new_w, new_h))
    
    return rotated_image

def overlay_image(background, overlay, x, y):
    '''
    Overlay the overlay image on top of the background image at the specified position (x, y).
    '''
    background_height, background_width = background.shape[:2]
    overlay_height, overlay_width = overlay.shape[:2]
    
    if x + overlay_width > background_width or y + overlay_height > background_height:
        raise ValueError("Overlay image exceeds the dimensions of the background image.")
    
    # Create a copy of the background image to avoid modifying the original image
    background_copy = background.copy()
    
    # Overlay the image on the background at the specified position
    background_copy[y:y + overlay_height, x:x + overlay_width] = overlay
    
    return background_copy

def overlay_center(background, overlay):
    '''
    Overlay the overlay image on top of the background image at the center.
    '''
    background_height, background_width = background.shape[:2]
    overlay_height, overlay_width = overlay.shape[:2]
    
    x = (background_width - overlay_width) // 2
    y = (background_height - overlay_height) // 2
    
    return overlay_image(background, overlay, x, y)

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

def cv_resize_to_target(src_image, target_image, resize_option):   
    if src_image is None or target_image is None:
        raise ValueError("One or both images not found or unable to read")

    image_height, image_width = src_image.shape[:2]
    target_height, target_width = target_image.shape[:2]
    
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
    else:
        raise ValueError("Invalid resize option. Use 'fill' or 'fit'.")

    resized_image = cv2.resize(src_image, (new_width, new_height), interpolation=cv2.INTER_LANCZOS4)

    if resize_option == 'fill':
        left = (new_width - target_width) // 2
        top = (new_height - target_height) // 2
        right = left + target_width
        bottom = top + target_height
        cropped_image = resized_image[top:bottom, left:right]
        return cropped_image
    else:
        return resized_image

def cv_resize_to_target_size(src_image, target_height, target_width, resize_option):
    # resize the image to resize to a target size using two options: fill or fit
    image_height, image_width = src_image.shape[:2]
    
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
    else:
        raise ValueError("Invalid resize option. Use 'fill' or 'fit'.")

    #check if we're downscaling or upscaling
    if new_width < image_width or new_height < image_height:
        interpolation = cv2.INTER_AREA
    else:
        interpolation = cv2.INTER_LANCZOS4 # or INTER_CUBIC 

    resized_image = cv2.resize(src_image, (new_width, new_height), interpolation=interpolation)

    if resize_option == 'fill':
        left = (new_width - target_width) // 2
        top = (new_height - target_height) // 2
        right = left + target_width
        bottom = top + target_height
        cropped_image = resized_image[top:bottom, left:right]
        return cropped_image
    else:
        return resized_image

def pil_to_cv2(pil_img):
    '''Convert PIL Image to OpenCV image (numpy.ndarray).'''
    cv2_img = np.array(pil_img)
    cv2_img = cv2.cvtColor(cv2_img, cv2.COLOR_RGB2BGR)
    return cv2_img

def list_files(directory, extensions=None, include_paths=False):
    # List all files in the directory with the specified extensions (if provided)
    # if include_paths is True, return the full path of the files
    if extensions:
        if isinstance(extensions, str):
            extensions = [extensions]
        files = [f for f in os.listdir(directory) if os.path.isfile(os.path.join(directory, f)) and f.lower().endswith(tuple(extensions))]
    else:
        files = [f for f in os.listdir(directory) if os.path.isfile(os.path.join(directory, f))]
        
    if include_paths:
        files = [os.path.join(directory, f) for f in files]

    return files

#read an image as PIL Image from a URL
def read_image_from_url(image_url):
    response = requests.get(image_url)
    image = Image.open(BytesIO(response.content))
    return pil_to_cv2(image)
    # return image

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

def get_title(json_data):
    metadata = json_data.get('Metadata', {})
    library_section_type = metadata.get('librarySectionType')
    
    if library_section_type == 'movie':
        title = metadata.get('title')
    elif library_section_type == 'show':
        title = metadata.get('grandparentTitle')
    else:
        title = metadata.get('parentTitle')
        
    return title

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
        return True
    elif val in ('n', 'no', 'f', 'false', 'off', '0'):
        return False
    else:
        raise ValueError("invalid truth value %r" % (val,))
    
def accel_to_orientation(accel):
    
    if type(accel) is dict:
        x, y, z = accel['ax'], accel['ay'], accel['az']
    else:
        x, y, z = accel
    
    # x, y, z = accel
    # this mapping it dependent on the orientation of the sensor
    if abs(x) > abs(y):
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

def lerp(value, min_val, max_val, new_min, new_max, clamp_output=True):
    new_value = (value - min_val) / (max_val - min_val) * (new_max - new_min) + new_min
    if clamp_output:
        new_value = clamp(new_value, new_min, new_max)
        
    return new_value

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

def read_image_properties(image_path):
    with Image.open(image_path) as img:
        properties = {
            "format": img.format,
            "mode": img.mode,
            "size": img.size,  # (width, height)
            "info": img.info
        }
    return properties

def get_mean_value(array):
    values = [value for value in array if value is not None]
    if values:
        mean = sum(values) / len(values)
        return mean
    else:
        return None
    
def get_mean_values(array):
    x_values = [item['ax'] for item in array if item is not None and item['ax'] is not None]
    y_values = [item['ay'] for item in array if item is not None and item['ay'] is not None]
    z_values = [item['az'] for item in array if item is not None and item['az'] is not None]
    
    x_mean = sum(x_values) / len(x_values) if x_values else None
    y_mean = sum(y_values) / len(y_values) if y_values else None
    z_mean = sum(z_values) / len(z_values) if z_values else None

    return x_mean, y_mean, z_mean


def accel_to_rotation(accel):
    if type(accel) is dict:
        x, y, z = accel['ax'], accel['ay'], accel['az']
    else:
        x, y, z = accel
    
    #invert the sign of x to match the orientation of the sensor        
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