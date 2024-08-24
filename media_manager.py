import os
import json
import random
import cv2
import numpy as np
from utils import cv2_crop_center, read_image_from_url, quick_read_image, cv_resize_to_target_size, cv2_rotate_image

from typing import List, Optional
from enum import Enum
from queue import Queue
import random


class ImageContainer:
    
    DEFAULT_THUMBNAIL_DIR = 'thumbnails'
    
    class Orientation(Enum):
        UNSET = 'square'
        PORTRAIT = 'portrait'
        LANDSCAPE = 'landscape'
        
        def __eq__(self, value: object) -> bool:
            return super().__eq__(value)
        
        def __str__(self) -> str:
            return self.value
        
    class ScaleMode(Enum):
        UNSET = 'unset'
        FILL = 'fill'
        FIT = 'fit'
        
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
        self.filename = None
        
        #image data
        self.image: np.ndarray = None
        self.thumbnail: np.ndarray = None
        self.processed_image: np.ndarray = None
        
        #properties
        self.orientation = ImageContainer.Orientation.UNSET
        self.is_portrait: bool = False
        self.target_height: int = 0
        self.target_width: int = 0
        self.scale_mode = ImageContainer.ScaleMode.UNSET
        self.rotation = 0

    def __eq__(self, other) -> bool:
        if not isinstance(other, ImageContainer):
            return False
        return self.filename == other.filename

    def from_file(self, file_path, thumbnail_dir=None, thumbnail_width=100, thumbnail_height=100):
        
        #strings
        self.file_path: str = file_path
        self.filename = os.path.basename(file_path)

        #image data
        self.image = cv2.imread(file_path)

        #properties
        self.thumbnail_height = thumbnail_height
        self.thumbnail_width = thumbnail_width
        
        #default actions
        self.check_for_thumbnail(thumbnail_dir)         #check if thumbnail exists, if not create one
        self.populate_properties()                      #populate the properties of the image
        return self

    def from_url(self, url, thumbnail_dir=None, thumbnail_width=100, thumbnail_height=100):
            
            #strings
            self.file_path: str = url
            self.filename = os.path.basename(url)
    
            #image data
            self.image = read_image_from_url(url)
    
            #properties
            self.thumbnail_height = thumbnail_height
            self.thumbnail_width = thumbnail_width
            
            #default actions
            # self.check_for_thumbnail(thumbnail_dir)       #TODO decide what to do with the thumbnail
            self.populate_properties()                      #populate the properties
            return self

    def from_image(self, image, thumbnail_dir=None, thumbnail_width=100, thumbnail_height=100):
            
            #strings
            self.file_path: str = 'image'
            self.filename = 'image'
            
            #image data
            self.image = image

            self.thumbnail_height = thumbnail_height
            self.thumbnail_width = thumbnail_width
            
            #default actions
            #self.check_for_thumbnail(thumbnail_dir)        #TODO decide what to do with the thumbnail
            self.populate_properties()                      #populate the properties
            return self


    def check_processing_parameters(self, target_height, target_width, scale_mode, angle):
        #if the processing parameters are different from the current processing parameters, then reprocess the image
        #this is to avoid reprocessing the image if the processing parameters are the same
        #but if the processing parameters are different, then reprocess the image
        
        if isinstance(scale_mode, ImageContainer.ScaleMode):
            scale_mode = scale_mode.value
        
        if self.target_height != target_height or self.target_width != target_width or self.scale_mode != scale_mode or self.rotation != angle:
            self.process_image(target_height, target_width, scale_mode, angle)
        
    def check_for_thumbnail(self, thumbnail_dir):
        #check if thumbnail dir exists, if not create one
        if thumbnail_dir is None:
            os.makedirs(self.DEFAULT_THUMBNAIL_DIR, exist_ok=True)
            thumbnail_dir = self.DEFAULT_THUMBNAIL_DIR
        
        #check if thumbnail exists, if not create one
        self.thumbnail_path = os.path.join(thumbnail_dir, self.filename)
        if os.path.exists(self.thumbnail_path):
            self.has_thumbnail = True
            self.check_thumnail_size(self.thumbnail_width, self.thumbnail_height)
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
        self.thumbnail = cv_resize_to_target_size(self.image, width, height, resize_option=ImageContainer.ScaleMode.FIT.value)
        cv2.imwrite(self.thumbnail_path, self.thumbnail)
        self.has_thumbnail = True

    def populate_properties(self):
        self.height, self.width = self.image.shape[:2]
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
        #do the processing of the image once
        self.target_height = target_height
        self.target_width = target_width
        self.scale_mode = scale_mode
        self.rotation = angle
        
        self.scale_mode = scale_mode
        self.rotation = angle
        rotated_image = cv2_rotate_image(self.image, self.rotation)
        self.processed_image = cv_resize_to_target_size(rotated_image, self.target_height, self.target_width, self.scale_mode)
        self.processed_image = cv2_crop_center(self.processed_image, (self.target_height, self.target_width))
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


#this class MediaManager is responsible for managing the media files
#it will be responsible for loading the media files from the media directory
#it will also be responsible for managing the media files in the playlist
#it will be responsible for storing the Image objects in the memory

class MediaManager:

    ALLOWED_TYPES = ('.png', '.jpg', '.jpeg', '.bmp', '.webp')
    
    def __init__(self, media_dir, thumbnail_dir=None, thumbnail_width=100, thumbnail_height=100) -> None:
        self.media_dir = media_dir
        self.thumbnail_dir = thumbnail_dir
        self.media_files: List[ImageContainer] = None
        self.current_index = 0
        self.current_media = None
        
        self.thumbnail_width = thumbnail_width
        self.thumbnail_height = thumbnail_height
        
        #todo - implement the playlist and make it accessible to slideshow_manager and image_viewer
        self.playlist = Queue()     #queue to store the media files
        
    def to_list(self):
        return [media.filename for media in self.media_files]
        
    def populate_media_files(self) -> None:
        self.media_files = self.load_media_files()
        
    def create_playlist(self, media_files=None) -> None:
        if media_files is None:
            if self.media_files is None:
                self.populate_media_files()
            media_files = self.media_files
            
        for media in media_files:
            self.playlist.put(media)

    def load_media_files(self) -> List[ImageContainer]:
        media_files = []
        for file in os.listdir(self.media_dir):
            if file.lower().endswith(MediaManager.ALLOWED_TYPES):
                img = ImageContainer()
                img.from_file(os.path.join(self.media_dir, file), self.thumbnail_dir, self.thumbnail_width, self.thumbnail_height)
                media_files.append(img)
        return media_files

    def get_next_media(self) -> ImageContainer:
        self.current_index = (self.current_index + 1) % len(self.media_files)
        self.current_media = self.media_files[self.current_index]
        return self.current_media

    def get_prev_media(self) -> ImageContainer:
        self.current_index = (self.current_index - 1) % len(self.media_files)
        self.current_media = self.media_files[self.current_index]
        return self.current_media

    def get_current_media(self) -> ImageContainer:
        return self.current_media

    def get_media_files(self, orientation=None) -> List[ImageContainer]:
        if self.media_files is None:
            self.populate_media_files()
            
        if orientation is not None:
            return self.get_media_by_orientation(orientation)
            
        return self.media_files
    
    def get_random_media(self, orientation=None) -> ImageContainer:
        if orientation is not None:
            media_files = self.get_media_by_orientation(orientation)
        else:
            media_files = self.media_files
        
        # Filter out the current image
        available_media = [media for media in media_files if media != self.current_media]
        
        # If no other media is available, just pick a random media file
        if not available_media:
            self.current_media = None
        else:
            # Select a random media file from the available media
            self.current_media = random.choice(available_media)

        return self.current_media

    def get_media_by_orientation(self, orientation) -> List[ImageContainer]:
        return [media for media in self.media_files if media.orientation == orientation]

    def get_media_by_index(self, index) -> Optional[ImageContainer]:
        if index < 0 or index >= len(self.media_files):
            return None
        return self.media_files[index]

    def get_media_by_filename(self, filename) -> Optional[ImageContainer]:
        for media in self.media_files:
            if media.filename == filename:
                return media
        return None

    def preprocess_media(self, target_height, target_width, scale_mode, angle) -> None:
        for media in self.media_files:
            media.process_image(target_height, target_width, scale_mode, angle)

    def get_blended_by_name(self, filename1, filename2, alpha) -> Optional[np.ndarray]:
        media1 = self.get_media_by_filename(filename1)
        media2 = self.get_media_by_filename(filename2)
        return media1.blend_image(media2, alpha)

    def get_blended_by_index(self, index1, index2, alpha) -> Optional[np.ndarray]:
        media1 = self.get_media_by_index(index1)
        media2 = self.get_media_by_index(index2)
        return media1.blend_image(media2, alpha)



if __name__ == '__main__':
    media_dir = 'images'
    thumbnail_dir = 'thumbnails'
    media_manager = MediaManager(media_dir, thumbnail_dir, 200, 200)
    media_files = media_manager.get_media_files()
    # print(len(media_files))
    # for media in media_files:
    #     print(media.filename)
    #     print(media.orientation)
    #     print(media.is_portrait)
    #     print(media.height, media.width)
    #     print(media.thumbnail_path)
    #     print(media.get_thumbnail().shape)
    #     print(media.get_image().shape)
    #     print('---------------------------------')
    # print('---------------------------------')

    # media_manager.preprocess_media(1080, 1920, ImageContainer.ScaleMode.FIT.value, 0)
    # for media in media_files:
    #     print(media.filename)
    #     print(media.orientation)
    #     print(media.is_portrait)
    #     print(media.height, media.width)
    #     print(media.thumbnail_path)
    #     print(media.get_thumbnail().shape)
    #     print(media.get_image().shape) 
    #     print(media.get_processed_image().shape)
    #     cv2.imshow('image', media.get_processed_image())
    #     cv2.waitKey(100)
    #     print('---------------------------------')
    # print('---------------------------------')

    
    
    # for media in media_files:
    #     media.check_processing_parameters(1080, 1920, ImageContainer.ScaleMode.FIT.value, 90)
    #     print(media.filename)
    #     print(media.orientation)
    #     print(media.is_portrait)
    #     print(media.height, media.width)
    #     print(media.thumbnail_path)
    #     print(media.get_thumbnail().shape)
    #     print(media.get_image().shape) 
    #     print(media.get_processed_image().shape)
    #     cv2.imshow('image', media.get_processed_image())
    #     cv2.waitKey(100)
    #     print('---------------------------------')
    # print('---------------------------------')

    
    
    while True:
        media = media_manager.get_random_media()
        media2 = media_manager.get_random_media()
        
        media.check_processing_parameters(1080, 1920, random.choice([ImageContainer.ScaleMode.FIT, ImageContainer.ScaleMode.FILL]), random.choice([0, 90, 180, 270]))
        media2.check_processing_parameters(1080, 1920, random.choice([ImageContainer.ScaleMode.FIT, ImageContainer.ScaleMode.FILL]), random.choice([0, 90, 180, 270]))
        cv2.imshow('image', media.blend_image(media2, 0.5))
        key = cv2.waitKey(0)
        if key == ord('q') or key == 27:
            break
        print('---------------------------------')
