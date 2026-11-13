import base64
import hashlib
import os
# import random
import cv2
import numpy as np
from utils import cv2_crop_center, overlay_center, read_image_from_url, cv_resize_to_target_size, cv2_rotate_image, read_image_properties, is_video_file
from constants import Orientation as ConstOrientation, ScaleMode as ConstScaleMode

from typing import List, Optional, Dict, Tuple
from enum import Enum
import gc

# Global LRU cache for processed images (shared across all ImageContainers)
_processed_image_cache: Dict[str, np.ndarray] = {}
_cache_max_size = 10  # Maximum number of cached processed images
_cache_order: list = []  # Track access order for LRU eviction


def _get_cache_key(file_path: str, target_height: int, target_width: int, scale_mode: str, rotation: int) -> str:
    """Generate a hash-based cache key for processed image parameters."""
    key_str = f"{file_path}|{target_height}|{target_width}|{scale_mode}|{rotation}"
    return hashlib.md5(key_str.encode()).hexdigest()


def _cache_get(key: str) -> Optional[np.ndarray]:
    """Get item from cache and update access order."""
    if key in _processed_image_cache:
        # Move to end (most recently used)
        if key in _cache_order:
            _cache_order.remove(key)
        _cache_order.append(key)
        return _processed_image_cache[key]
    return None


def _cache_put(key: str, image: np.ndarray) -> None:
    """Put item in cache with LRU eviction."""
    global _processed_image_cache, _cache_order
    
    # Evict oldest if at capacity
    while len(_cache_order) >= _cache_max_size:
        oldest_key = _cache_order.pop(0)
        if oldest_key in _processed_image_cache:
            del _processed_image_cache[oldest_key]
    
    _processed_image_cache[key] = image
    _cache_order.append(key)


class ImageContainer:
    
    DEFAULT_THUMBNAIL_DIR = 'thumbnails'
    
    __slots__ = (
        'file_path', 'thumbnail_path', 'filename', 'source',
        '_image', '_encoded_image', 'thumbnail', 'processed_image',
        'orientation', 'is_portrait', 'target_height', 'target_width',
        'scale_mode', 'rotation', 'thumbnail_height', 'thumbnail_width',
        'has_thumbnail', 'height', 'width', 'is_video', 'video_fps', 'video_frame_count'
    )
    
    # Keep nested classes for backward compatibility but they now reference the shared enums
    class Orientation(Enum):
        UNSET = 'square'
        PORTRAIT = ConstOrientation.PORTRAIT.value
        LANDSCAPE = ConstOrientation.LANDSCAPE.value
        BOTH = ConstOrientation.BOTH.value
        
        def __eq__(self, value: object) -> bool:
            return self.value == value
        
        def __str__(self) -> str:
            return self.value
        
    class ScaleMode(Enum):
        UNSET = 'unset'
        FILL = ConstScaleMode.FILL.value
        FIT = ConstScaleMode.FIT.value
        
        def __eq__(self, value: object) -> bool:
            return self.value == value
    
        def __str__(self) -> str:
            return self.value
    
    class Source(Enum):
        FILE = 'file'
        URL = 'url'
        BASE64 = 'base64'
        IMAGE = 'image'
        
        def __eq__(self, value: object) -> bool:
            return super().__eq__(value)
    
        def __str__(self) -> str:
            return self.value
    
    #this class ImageContainer is responsible for reading file with opencv and storing the image object in the memory
    #it will keep a record of the orientation of the image 
    #it will keep the original image object and the resized image object
    def __init__(self) -> None:
        #strings
        self.file_path: str = None
        self.thumbnail_path: str = None
        self.filename: str = None
        self.source: ImageContainer.Source = None
        
        #image data
        self._image: np.ndarray = None
        self._encoded_image = None
        self.thumbnail: np.ndarray = None
        self.processed_image: np.ndarray = None
        # self._encoded_processed_image = None
        
        #properties
        self.orientation = ImageContainer.Orientation.UNSET
        self.is_portrait: bool = False
        self.target_height: int = 0
        self.target_width: int = 0
        self.scale_mode = ImageContainer.ScaleMode.UNSET
        self.rotation = 0
        
        # Video properties
        self.is_video: bool = False
        self.video_fps: float = 30.0
        self.video_frame_count: int = 0

    def __str__(self) -> str:
        #used for printing the object
        #it should display the path, filename, orientation, height, width, thumbnail path, thumbnail size, image size, processed image size
        return (
            f"Path: {self.file_path}\n"
            f"Filename: {self.filename}\n"
            f"Orientation: {self.orientation}\n"
            f"Height: {self.height}\n"
            f"Width: {self.width}\n"
            f"Thumbnail Path: {self.thumbnail_path}\n"
            f"Thumbnail Size: {self.thumbnail.shape[:2] if self.thumbnail is not None else 'N/A'}\n"
            f"Image Size: {self._image.shape[:2] if self._image is not None else 'N/A'}\n"
            f"Processed Image Size: {self.processed_image.shape[:2] if self.processed_image is not None else 'N/A'}"
        )
        
    def __eq__(self, other) -> bool:
        if not isinstance(other, ImageContainer):
            return False
        return self.filename == other.filename


    def exists(self) -> bool:
        return os.path.exists(self.file_path)

    @property
    def image(self) -> np.ndarray:
        if self._image is None:
            self.reload_image()
            
        return self._image
    
    @image.setter
    def image(self, image: np.ndarray) -> None:
        self._image = image
        if image is not None:
            self.populate_properties()


    # @property
    # def processed_image(self) -> np.ndarray:
    #     if self._encoded_processed_image is not None:
    #         self._processed_image = cv2.imdecode(self._encoded_processed_image, cv2.IMREAD_COLOR)
    #     return self._processed_image
    
    # @processed_image.setter
    # def processed_image(self, image: np.ndarray) -> None:
    #     if image is None:
    #         self._processed_image = None
    #         return
    #     self._encoded_processed_image = cv2.imencode('.jpg', self.image, [int(cv2.IMWRITE_JPEG_QUALITY), 100])[1]
      


    def from_file(self, file_path, thumbnail_dir=None, thumbnail_width=100, thumbnail_height=100, read_image=False):
        self.source = ImageContainer.Source.FILE
        #strings
        self.file_path: str = file_path
        self.filename = os.path.basename(file_path)
        
        # Check if this is a video file
        self.is_video = is_video_file(file_path)

        #image data
        if read_image:
            self.reload_image()

        #properties
        self.thumbnail_height = thumbnail_height
        self.thumbnail_width = thumbnail_width
        
        #default actions
        self.check_for_thumbnail(thumbnail_dir)         #check if thumbnail exists, if not create one
        self.populate_properties()                      #populate the properties of the image
        
        return self

    def from_url(self, url, thumbnail_dir=None, thumbnail_width=100, thumbnail_height=100, read_image=False):
        self.source = ImageContainer.Source.URL
        #strings
        self.file_path: str = url
        self.filename = os.path.basename(url)

        #image data
        if read_image:
            self._image = read_image_from_url(url)

        #properties
        self.thumbnail_height = thumbnail_height
        self.thumbnail_width = thumbnail_width
        
        #default actions
        # self.check_for_thumbnail(thumbnail_dir)       #TODO decide what to do with the thumbnail
        self.populate_properties()                      #populate the properties
        
        return self

    def from_image(self, image, filename='', thumbnail_dir=None, thumbnail_width=100, thumbnail_height=100):  
        self.source = ImageContainer.Source.IMAGE
        #strings
        self.file_path: str = '_from_image_'
        self.filename = filename

        #image data
        self._image = image
        self.thumbnail_height = thumbnail_height
        self.thumbnail_width = thumbnail_width

        #default actions
        #self.check_for_thumbnail(thumbnail_dir)        #TODO decide what to do with the thumbnail
        self.populate_properties()                      #populate the properties
        
        return self

    def from_base64(self, base64_string, filename='', thumbnail_width=100, thumbnail_height=100):
        self.source = ImageContainer.Source.BASE64
        self.file_path: str = '_from_base64_'
        self.filename = filename
        image_data = base64.b64decode(base64_string)
        nparr = np.frombuffer(image_data, np.uint8)
        self._image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        self.thumbnail_height = thumbnail_height
        self.thumbnail_width = thumbnail_width
        
        #default actions
        #self.check_for_thumbnail(thumbnail_dir)        #TODO decide what to do with the thumbnail
        self.populate_properties()                      #populate the properties
        return self
    
    def reload_image(self):        
        if self._encoded_image is not None:
            print(f'Reloading image from memory')
            self._image = cv2.imdecode(self._encoded_image, cv2.IMREAD_COLOR)
            return
        
        if self.source == ImageContainer.Source.FILE:
            if self.exists():
                print(f'Reloading image from file {self.filename}')
                if is_video_file(self.file_path):
                    # Extract a frame from video
                    self._image = self._extract_video_frame(self.file_path)
                else:
                    self._image = cv2.imread(self.file_path)
        
        if self.source == ImageContainer.Source.URL:
            print(f'Reloading image from URL {self.file_path}')
            self._image = read_image_from_url(self.file_path)

        if self._image is not None:
            self._encoded_image = cv2.imencode('.jpg', self._image, [int(cv2.IMWRITE_JPEG_QUALITY), 100])[1]

    def _extract_video_frame(self, video_path, frame_position=0.1):
        """Extract a frame from a video file.
        
        Args:
            video_path: Path to the video file
            frame_position: Position to extract frame (0.0-1.0, default 10% into video)
        
        Returns:
            numpy array of the frame, or None if failed
        """
        cap = cv2.VideoCapture(video_path)
        try:
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            if total_frames > 0:
                target_frame = int(total_frames * frame_position)
                cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
            
            ret, frame = cap.read()
            if ret:
                return frame
            
            # Fallback to first frame
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ret, frame = cap.read()
            return frame if ret else None
        finally:
            cap.release()


    def check_processing_parameters(self, target_height=None, target_width=None, scale_mode=None, angle=None):
        #if the processing parameters are different from the current processing parameters, then reprocess the image
        #this is to avoid reprocessing the image if the processing parameters are the same
        #but if the processing parameters are different, then reprocess the image
        
        #if any parameter is None, then use the current value
        scale_mode = scale_mode if scale_mode is not None else self.scale_mode
        angle = angle if angle is not None else self.rotation
        target_height = target_height if target_height is not None else self.target_height
        target_width = target_width if target_width is not None else self.target_width
        
        if isinstance(scale_mode, ImageContainer.ScaleMode):
            scale_mode = scale_mode.value
        
        if self.target_height != target_height or self.target_width != target_width or self.scale_mode != scale_mode or self.rotation != angle:
            # Check cache first
            cache_key = _get_cache_key(self.file_path, target_height, target_width, scale_mode, angle)
            cached = _cache_get(cache_key)
            if cached is not None:
                self.processed_image = cached
                self.target_height = target_height
                self.target_width = target_width
                self.scale_mode = scale_mode
                self.rotation = angle
            elif int(abs(self.rotation - angle)) == 180:
                self.processed_image = cv2_rotate_image(self.processed_image, 180)
                self.rotation = angle
                _cache_put(cache_key, self.processed_image)
            else:
                self.process_image(target_height, target_width, scale_mode, angle)
                _cache_put(cache_key, self.processed_image)
        else:
            if self.processed_image is None:
                cache_key = _get_cache_key(self.file_path, self.target_height, self.target_width, self.scale_mode, self.rotation)
                cached = _cache_get(cache_key)
                if cached is not None:
                    self.processed_image = cached
                else:
                    self.process_image(self.target_height, self.target_width, self.scale_mode, self.rotation)
                    _cache_put(cache_key, self.processed_image)
        
    def check_for_thumbnail(self, thumbnail_dir):
        #check if thumbnail dir exists, if not create one
        if thumbnail_dir is None:
            os.makedirs(self.DEFAULT_THUMBNAIL_DIR, exist_ok=True)
            thumbnail_dir = self.DEFAULT_THUMBNAIL_DIR
        
        #check if thumbnail exists, if not create one
        # For videos, use .jpg extension for thumbnails
        if is_video_file(self.file_path):
            thumb_filename = os.path.splitext(self.filename)[0] + '.jpg'
            self.thumbnail_path = os.path.join(thumbnail_dir, thumb_filename)
        else:
            self.thumbnail_path = os.path.join(thumbnail_dir, self.filename)
        
        if os.path.exists(self.thumbnail_path):
            self.has_thumbnail = True
            # self.check_thumnail_size(self.thumbnail_width, self.thumbnail_height)
        else:
            self.has_thumbnail = False
            self.create_thumbnail(self.thumbnail_width, self.thumbnail_height)

    def check_thumnail_size(self, width, height):
        # if either of the thumbnail dimensions differs from the target size by more than 10%, then recreate the thumbnail
        self.thumbnail = cv2.imread(self.thumbnail_path)
        if abs(self.thumbnail.shape[0] - height) > height * 0.1 or abs(self.thumbnail.shape[1] - width) > width * 0.1:
            self.has_thumbnail = False              #because the thumbnail is not of the correct size
            self.create_thumbnail(width, height)
        
    def create_thumbnail(self, width, height):
        if self.has_thumbnail:
            return
        
        # For videos or when image isn't loaded, use the utils function
        if is_video_file(self.file_path) or self._image is None:
            from utils import create_thumbnail as utils_create_thumbnail
            # Change extension to .jpg for video thumbnails
            thumb_path = self.thumbnail_path
            if is_video_file(self.file_path):
                thumb_path = os.path.splitext(self.thumbnail_path)[0] + '.jpg'
                self.thumbnail_path = thumb_path
            utils_create_thumbnail(self.file_path, thumb_path, (width, height))
            self.thumbnail = cv2.imread(thumb_path)
        else:
            self.thumbnail = cv_resize_to_target_size(self._image, width, height, resize_option=ImageContainer.ScaleMode.FIT.value)
            cv2.imwrite(self.thumbnail_path, self.thumbnail)
        
        self.has_thumbnail = True

    def populate_properties(self):
        if self._image is None:
            #read the properties from the file without loading the image
            props = read_image_properties(self.file_path)
            size = props['size']
            self.width, self.height = size
            
            # Get video-specific properties
            if self.is_video and 'info' in props:
                self.video_fps = props['info'].get('fps', 30.0)
                self.video_frame_count = props['info'].get('frame_count', 0)
        else:
            self.height, self.width = self._image.shape[:2]
            
        self.is_portrait = self.height > self.width

        if self.is_portrait:
            self.orientation = ImageContainer.Orientation.PORTRAIT
        else:
            self.orientation = ImageContainer.Orientation.LANDSCAPE

    def get_thumbnail(self) -> Optional[np.ndarray]: 
        return self.thumbnail

    def get_image(self) -> Optional[np.ndarray]:
        return self.image
    
    def get_processed_image(self) -> Optional[np.ndarray]: 
        return self.processed_image
    
    def process_image(self, target_height, target_width, scale_mode, angle):
        if not self.exists() and self._image is None:
            return None

        #do the processing of the image once
        self.target_height = target_height
        self.target_width = target_width
        self.scale_mode = scale_mode
        self.rotation = angle
        
        self.scale_mode = scale_mode
        self.rotation = angle
        rotated_image = cv2_rotate_image(self.image, self.rotation)
        self.processed_image = cv_resize_to_target_size(rotated_image, self.target_height, self.target_width, self.scale_mode)
        # self.processed_image = cv2_crop_center(self.processed_image, (self.target_height, self.target_width))
        
        if self.scale_mode == ImageContainer.ScaleMode.FIT:
            background = cv_resize_to_target_size(rotated_image, self.target_height, self.target_width, ImageContainer.ScaleMode.FILL)
            background = cv2.GaussianBlur(background, (101, 101), 0)
            background = cv2.multiply(background, 0.5)
            self.processed_image = cv2_crop_center(self.processed_image, (self.target_height, self.target_width), background=background)
        else:
            self.processed_image = cv2_crop_center(self.processed_image, (self.target_height, self.target_width))
                        
            # background = cv_resize_to_target_size(rotated_image, self.target_height, self.target_width, ImageContainer.ScaleMode.FILL)
            # self.processed_image = overlay_center(background, self.processed_image)
        
        if self.source == ImageContainer.Source.FILE:
            #if it's from file we can clear the image from memory as we can easily reload it
            self.image = None
        return self.processed_image

    def blend_image(self, image: 'ImageContainer', alpha: float) -> Optional[np.ndarray]:
        # if self.processed_image is None:
        #     return image.processed_image
        # alpha 0 means only the current image, alpha 1 means only the new image

        if alpha == 0:
            return self.processed_image
        if alpha == 1:
            return image.processed_image
        
        if image.processed_image.shape != self.processed_image.shape:
            image.process_image(self.processed_image.shape[0], self.processed_image.shape[1], self.scale_mode, self.rotation)

        return cv2.addWeighted(self.processed_image, alpha, image.processed_image, 1 - alpha, 0)

    def free_memory(self):
        self._image = None
        self.thumbnail = None
        self.processed_image = None
        gc.collect()