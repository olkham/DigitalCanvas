import os
import json
import random
import cv2
import numpy as np
from utils import cv2_crop_center, read_image_from_url, quick_read_image, cv_resize_to_target_size, cv2_rotate_image

from typing import List, Optional
from enum import Enum


class ImageContainer:
    
    DEFAULT_THUMBNAIL_DIR = 'thumbnails'
    
    class Orientation(Enum):
        UNSET = 'unset'
        PORTRAIT = 'portrait'
        LANDSCAPE = 'landscape'
        
    class ScaleMode(Enum):
        UNSET = 'unset'
        FILL = 'fill'
        FIT = 'fit'
    
    #this class ImageContainer is responsible for reading file with opencv and storing the image object in the memory
    #it will keep a record of the orientation of the image 
    #it will keep the original image object and the resized image object
    def __init__(self, file_path, thumbnail_dir=None, thumbnail_width=100, thumbnail_height=100):
        
        #strings
        self.file_path: str = file_path
        self.filename = os.path.basename(file_path)

        #image data
        self.image = cv2.imread(file_path)
        self.thumbnail: np.ndarray = None
        self.processed_image: np.ndarray = None

        #properties
        self.orientation = ImageContainer.Orientation.UNSET
        self.is_portrait: bool = False
        self.target_height: int = 0
        self.target_width: int = 0
        self.scale_mode = ImageContainer.ScaleMode.UNSET
        self.rotation = 0
        self.thumbnail_height = thumbnail_height
        self.thumbnail_width = thumbnail_width
        
        #default actions
        self.check_for_thumbnail(thumbnail_dir)         #check if thumbnail exists, if not create one
        self.populate_properties()                      #populate the properties of the image


    def check_processing_parameters(self, target_height, target_width, scale_mode, angle):
        #if the processing parameters are different from the current processing parameters, then reprocess the image
        #this is to avoid reprocessing the image if the processing parameters are the same
        #but if the processing parameters are different, then reprocess the image
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

    def blend_image(self, image, alpha):
        if self.processed_image is None:
            return image
        if image is None:
            return self.processed_image
        if alpha == 0:
            return self.processed_image
        if alpha == 1:
            return image
        if image.shape != self.processed_image.shape:
            image = cv_resize_to_target_size(image, self.processed_image.shape[0], self.processed_image.shape[1], self.scale_mode)

        return cv2.addWeighted(self.processed_image, alpha, image, 1 - alpha, 0)


#this class MediaManager is responsible for managing the media files
#it will be responsible for loading the media files from the media directory
#it will also be responsible for managing the media files in the playlist
#it will be responsible for storing the Image objects in the memory

class MediaManager:
    
    ALLOWED_TYPES = ('.png', '.jpg', '.jpeg', '.bmp', '.webp')
    
    def __init__(self, media_dir, thumbnail_dir=None, thumbnail_width=100, thumbnail_height=100):
        self.media_dir = media_dir
        self.thumbnail_dir = thumbnail_dir
        self.media_files: List[ImageContainer] = None
        self.current_index = 0
        self.current_media = None
        
        self.thumbnail_width = thumbnail_width
        self.thumbnail_height = thumbnail_height
        
    def populate_media_files(self):
        self.media_files = self.load_media_files()

    def load_media_files(self):
        media_files = []
        for file in os.listdir(self.media_dir):
            if file.lower().endswith(MediaManager.ALLOWED_TYPES):
                img = ImageContainer(os.path.join(self.media_dir, file), self.thumbnail_dir, self.thumbnail_width, self.thumbnail_height)
                media_files.append(img)
        return media_files

    def get_next_media(self):
        self.current_index = (self.current_index + 1) % len(self.playlist)
        self.current_media = self.playlist[self.current_index]
        return self.current_media

    def get_prev_media(self):
        self.current_index = (self.current_index - 1) % len(self.playlist)
        self.current_media = self.playlist[self.current_index]
        return self.current_media

    def get_current_media(self):
        return self.current_media

    def get_media_files(self):
        if self.media_files is None:
            self.populate_media_files()
        return self.media_files
    
    def get_random_media(self):
        return random.choice(self.media_files)
    
    def get_media_by_index(self, index):
        return self.media_files[index]
    
    def get_media_by_filename(self, filename):
        for media in self.media_files:
            if media.filename == filename:
                return media
        return None
    
    def get_media_by_orientation(self, orientation):
        return [media for media in self.media_files if media.orientation == orientation]
    
    def preprocess_media(self, target_height, target_width, scale_mode, angle):
        for media in self.media_files:
            media.process_image(target_height, target_width, scale_mode, angle)
            
    
    
if __name__ == '__main__':
    media_dir = 'images'
    thumbnail_dir = 'thumbnails'
    media_manager = MediaManager(media_dir, thumbnail_dir, 200, 200)
    media_files = media_manager.get_media_files()
    print(len(media_files))
    for media in media_files:
        print(media.filename)
        print(media.orientation)
        print(media.is_portrait)
        print(media.height, media.width)
        print(media.thumbnail_path)
        print(media.get_thumbnail().shape)
        print(media.get_image().shape)
        print('---------------------------------')
    print('---------------------------------')
    print('---------------------------------')
    print('---------------------------------')
    media_manager.preprocess_media(1080, 1920, ImageContainer.ScaleMode.FIT.value, 0)
    for media in media_files:
        print(media.filename)
        print(media.orientation)
        print(media.is_portrait)
        print(media.height, media.width)
        print(media.thumbnail_path)
        print(media.get_thumbnail().shape)
        print(media.get_image().shape) 
        print(media.get_processed_image().shape)
        cv2.imshow('image', media.get_processed_image())
        cv2.waitKey(0)
        print('---------------------------------')
    print('---------------------------------')
    print('---------------------------------')
    print('---------------------------------')
    
    
    for media in media_files:
        media.check_processing_parameters(1080, 1920, ImageContainer.ScaleMode.FIT.value, 90)
        print(media.filename)
        print(media.orientation)
        print(media.is_portrait)
        print(media.height, media.width)
        print(media.thumbnail_path)
        print(media.get_thumbnail().shape)
        print(media.get_image().shape) 
        print(media.get_processed_image().shape)
        cv2.imshow('image', media.get_processed_image())
        cv2.waitKey(0)
        print('---------------------------------')
    print('---------------------------------')
    print('---------------------------------')
    print('---------------------------------')