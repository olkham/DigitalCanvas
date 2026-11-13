"""Image processing utilities - resize, crop, rotate, convert between formats."""

import os
import cv2
import numpy as np
import requests
from io import BytesIO
from PIL import Image


IMAGE_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.bmp', '.webp')
VIDEO_EXTENSIONS = ('.mp4', '.mov', '.avi', '.webm', '.mkv', '.gif')


def is_video_file(file_path: str) -> bool:
    """Check if a file is a video based on extension."""
    return file_path.lower().endswith(VIDEO_EXTENSIONS)


def is_image_file(file_path: str) -> bool:
    """Check if a file is an image based on extension."""
    return file_path.lower().endswith(IMAGE_EXTENSIONS)


def create_thumbnail(image_path, thumbnail_path, size=(200, 200)):
    """Create a thumbnail from an image or video file."""
    if is_video_file(image_path):
        create_video_thumbnail(image_path, thumbnail_path, size)
    else:
        with Image.open(image_path) as img:
            img.thumbnail(size, Image.LANCZOS)
            img.save(thumbnail_path)


def create_video_thumbnail(video_path, thumbnail_path, size=(200, 200)):
    """Create a thumbnail from a video file by extracting a frame."""
    cap = cv2.VideoCapture(video_path)
    try:
        # Try to get a frame from 10% into the video
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total_frames > 0:
            cap.set(cv2.CAP_PROP_POS_FRAMES, total_frames // 10)
        
        ret, frame = cap.read()
        if ret:
            # Convert BGR to RGB for PIL
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(frame_rgb)
            img.thumbnail(size, Image.LANCZOS)
            img.save(thumbnail_path)
        else:
            # If we can't read a frame, try the first frame
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ret, frame = cap.read()
            if ret:
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                img = Image.fromarray(frame_rgb)
                img.thumbnail(size, Image.LANCZOS)
                img.save(thumbnail_path)
    finally:
        cap.release()


def is_portrait(image_path):
    """Check if an image is portrait orientation."""
    with Image.open(image_path) as img:
        return img.height > img.width


def is_landscape(image_path):
    """Check if an image is landscape orientation."""
    with Image.open(image_path) as img:
        return img.width > img.height


def max_usful_size(image_path, max_size):
    """Scale image so minimum dimension equals max_size, overwriting original.
    
    Skips video files as they don't need resizing.
    """
    if is_video_file(image_path):
        return  # Don't resize videos
    
    with Image.open(image_path) as img:
        smallest_dimension = min(img.width, img.height)
        if smallest_dimension <= max_size:
            return
        
        scale_factor = max_size / smallest_dimension
        new_width = int(img.width * scale_factor)
        new_height = int(img.height * scale_factor)
        img = img.resize((new_width, new_height), Image.LANCZOS)
        img.save(image_path, quality=90)


def resize_image(image, screen_width, screen_height, orientation, rotation):
    """Resize image based on screen and orientation settings."""
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
    """Calculate dimensions to fill screen while maintaining aspect ratio."""
    aspect_ratio = min(screen_width / image_width, screen_height / image_height)
    return int(image_width * aspect_ratio), int(image_height * aspect_ratio)


def resize_to_fit_height(image_width, image_height, screen_height):
    """Calculate dimensions to fit screen height while maintaining aspect ratio."""
    aspect_ratio = screen_height / image_height
    return int(image_width * aspect_ratio), screen_height


def resize_to_fit_width(image_width, image_height, screen_width):
    """Calculate dimensions to fit screen width while maintaining aspect ratio."""
    aspect_ratio = screen_width / image_width
    return screen_width, int(image_height * aspect_ratio)


def crop_center(image, size):
    """Crop PIL image to specified size from center."""
    width, height = image.size
    new_width, new_height = size
    left = (width - new_width) // 2
    top = (height - new_height) // 2
    right = (width + new_width) // 2
    bottom = (height + new_height) // 2
    return image.crop((left, top, right, bottom))


def cv2_crop_center(image, size, background=None):
    """Crop OpenCV image to specified size from center, expanding with black if needed."""
    height, width = image.shape[:2]
    new_height, new_width = size[:2]
    
    if new_height > height or new_width > width:
        if background is not None:
            result = background
        else:
            result = np.zeros((new_height, new_width, 3), dtype=np.uint8)
        
        left = (new_width - width) // 2
        top = (new_height - height) // 2
        right = left + width
        bottom = top + height
        
        result[top:bottom, left:right] = image
        return result
    else:
        left = (width - new_width) // 2
        top = (height - new_height) // 2
        right = left + new_width
        bottom = top + new_height
        return image[top:bottom, left:right]


def quick_read_image(image_path):
    """Quickly read an image file as OpenCV format."""
    return cv2.cvtColor(np.array(Image.open(image_path)), cv2.COLOR_RGB2BGR)


def cv2_to_pil(cv2_img):
    """Convert OpenCV image (numpy.ndarray) to PIL Image."""
    return Image.fromarray(cv2.cvtColor(cv2_img, cv2.COLOR_BGR2RGB))


def pil_to_cv2(pil_img):
    """Convert PIL Image to OpenCV image (numpy.ndarray)."""
    cv2_img = np.array(pil_img)
    cv2_img = cv2.cvtColor(cv2_img, cv2.COLOR_RGB2BGR)
    return cv2_img


def cv2_rotate_image(image, angle):
    """Rotate OpenCV image by specified angle (0, 90, 180, 270 optimized)."""
    if angle == 0:
        return image
    
    if angle == 90:
        rotated_image = cv2.transpose(image)
        rotated_image = cv2.flip(rotated_image, 1)
    elif angle == 180:
        rotated_image = cv2.flip(image, -1)
    elif angle == 270:
        rotated_image = cv2.transpose(image)
        rotated_image = cv2.flip(rotated_image, 0)
    else:
        (h, w) = image.shape[:2]
        center = (w // 2, h // 2)
        M = cv2.getRotationMatrix2D(center, angle, 1.0)
        cos = np.abs(M[0, 0])
        sin = np.abs(M[0, 1])
        new_w = int((h * sin) + (w * cos))
        new_h = int((h * cos) + (w * sin))
        M[0, 2] += (new_w / 2) - center[0]
        M[1, 2] += (new_h / 2) - center[1]
        rotated_image = cv2.warpAffine(image, M, (new_w, new_h))
    
    return rotated_image


def overlay_image(background, overlay, x, y):
    """Overlay an image on top of background at specified position."""
    background_height, background_width = background.shape[:2]
    overlay_height, overlay_width = overlay.shape[:2]
    
    if x + overlay_width > background_width or y + overlay_height > background_height:
        raise ValueError("Overlay image exceeds the dimensions of the background image.")
    
    background_copy = background.copy()
    background_copy[y:y + overlay_height, x:x + overlay_width] = overlay
    return background_copy


def overlay_center(background, overlay):
    """Overlay an image on top of background at center."""
    background_height, background_width = background.shape[:2]
    overlay_height, overlay_width = overlay.shape[:2]
    
    x = (background_width - overlay_width) // 2
    y = (background_height - overlay_height) // 2
    
    return overlay_image(background, overlay, x, y)


def resize_to_target(src_image, target_image, resize_option):
    """Resize PIL image to target size using fill or fit option."""
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
    """Resize OpenCV image to target image size using fill or fit option."""
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
    """Resize OpenCV image to target dimensions using fill or fit option."""
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

    if new_width < image_width or new_height < image_height:
        interpolation = cv2.INTER_AREA
    else:
        interpolation = cv2.INTER_LANCZOS4

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


def read_image_from_url(image_url):
    """Read an image from URL and return as OpenCV format."""
    response = requests.get(image_url)
    image = Image.open(BytesIO(response.content))
    return pil_to_cv2(image)


def read_image_properties(image_path):
    """Read basic properties of an image or video file."""
    if is_video_file(image_path):
        return read_video_properties(image_path)
    
    with Image.open(image_path) as img:
        properties = {
            "format": img.format,
            "mode": img.mode,
            "size": img.size,
            "info": img.info
        }
    return properties


def read_video_properties(video_path):
    """Read basic properties of a video file."""
    cap = cv2.VideoCapture(video_path)
    try:
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = frame_count / fps if fps > 0 else 0
        
        properties = {
            "format": "video",
            "mode": "RGB",
            "size": (width, height),
            "info": {
                "fps": fps,
                "frame_count": frame_count,
                "duration": duration
            }
        }
        return properties
    finally:
        cap.release()


def save_remote_image(image_url, upload_folder, size=None):
    """Download and save an image from URL."""
    from .file_utils import check_for_duplicate_files, replace_webp_extension
    
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
    """Create missing thumbnails and remove orphaned thumbnails."""
    from .file_utils import check_and_create
    
    check_and_create(images)
    check_and_create(thumbs)
    
    # Use os.scandir() for better performance
    image_files = {f.name for f in os.scandir(images) if f.is_file()}
    
    for filename in image_files:
        file_path = os.path.join(images, filename)
        thumbnail_path = os.path.join(thumbs, filename)
        if not os.path.exists(thumbnail_path):
            create_thumbnail(file_path, thumbnail_path)

    # Remove orphaned thumbnails
    for entry in os.scandir(thumbs):
        if entry.is_file() and entry.name not in image_files:
            os.remove(entry.path)
