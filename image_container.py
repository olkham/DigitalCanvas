import base64
import os
# import random
import cv2
import numpy as np
from utils import cv2_crop_center, overlay_center, read_image_from_url, cv_resize_to_target_size, cv2_rotate_image, read_image_properties

from typing import List, Optional
from enum import Enum
import gc


class ImageContainer:
    
    DEFAULT_THUMBNAIL_DIR = 'thumbnails'
    
    class Orientation(Enum):
        UNSET = 'square'
        PORTRAIT = 'portrait'
        LANDSCAPE = 'landscape'
        BOTH = 'both'
        
        def __eq__(self, value: object) -> bool:
            return self.value == value
        
        def __str__(self) -> str:
            return self.value
        
    class ScaleMode(Enum):
        UNSET = 'unset'
        FILL = 'fill'
        FIT = 'fit'
        
        def __eq__(self, value: object) -> bool:
            return self.value == value
            return super().__eq__(value)
    
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
                self._image = cv2.imread(self.file_path)
        
        if self.source == ImageContainer.Source.URL:
            print(f'Reloading image from URL {self.file_path}')
            self._image = read_image_from_url(self.file_path)

        self._encoded_image = cv2.imencode('.jpg', self._image, [int(cv2.IMWRITE_JPEG_QUALITY), 100])[1]


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
            print('Reprocessing image')
            if int(abs(self.rotation - angle)) == 180:
                self.processed_image = cv2_rotate_image(self.processed_image, 180)
                self.rotation = angle
            else:
                self.process_image(target_height, target_width, scale_mode, angle)
        else:
            if self.processed_image is None:
                self.process_image(self.target_height, self.target_width, self.scale_mode, self.rotation)
        
    def check_for_thumbnail(self, thumbnail_dir):
        #check if thumbnail dir exists, if not create one
        if thumbnail_dir is None:
            os.makedirs(self.DEFAULT_THUMBNAIL_DIR, exist_ok=True)
            thumbnail_dir = self.DEFAULT_THUMBNAIL_DIR
        
        #check if thumbnail exists, if not create one
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
        self.thumbnail = cv_resize_to_target_size(self._image, width, height, resize_option=ImageContainer.ScaleMode.FIT.value)
        cv2.imwrite(self.thumbnail_path, self.thumbnail)
        self.has_thumbnail = True

    def populate_properties(self):
        if self._image is None:
            #read the properties from the file without loading the image
            size = read_image_properties(self.file_path)['size']
            self.width, self.height = size
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