# import base64
import os
import random
import cv2
import numpy as np
# from utils import cv2_crop_center, read_image_from_url, cv_resize_to_target_size, cv2_rotate_image

from typing import List, Optional
# from enum import Enum
import random

from image_container import ImageContainer

#this class MediaManager is responsible for managing the media files
#it will be responsible for loading the media files from the media directory
#it will also be responsible for managing the media files in the playlist
#it will be responsible for storing the Image objects in the memory

class MediaManager:

    ALLOWED_TYPES = ('.png', '.jpg', '.jpeg', '.bmp', '.webp')

    @property
    def orientation_filter(self) -> ImageContainer.Orientation:
        return self._orientation_filter

    @orientation_filter.setter
    def orientation_filter(self, orientation: ImageContainer.Orientation) -> None:
        if orientation != self._orientation_filter:
            self.filter_media_by_orientation(orientation)
            self._orientation_filter = orientation

    def __init__(self, media_dir, thumbnail_dir=None, thumbnail_width=100, thumbnail_height=100) -> None:
        self.media_dir = media_dir
        self.thumbnail_dir = thumbnail_dir
        self.all_media_files: List[ImageContainer] = []
        self.playlist = self.all_media_files
        self.current_index = 0
        self.current_media = None
        self.thumbnail_width = thumbnail_width
        self.thumbnail_height = thumbnail_height
        self._orientation_filter = ImageContainer.Orientation.BOTH
        self._pre_load_media = False
        
        self.media_files_changed_callback = None
        

    def to_list(self):
        return [media.filename for media in self.all_media_files]

    def populate_media_files(self) -> None:
        self.all_media_files = self.load_media_files()

    def create_playlist(self, media_files=None) -> None:
        if media_files is None:
            if self.all_media_files is None:
                self.populate_media_files()
            media_files = self.all_media_files

        # for media in media_files:
            self.playlist = media_files

    def load_media_files(self) -> List[ImageContainer]:
        # media_files = []
        for file in os.listdir(self.media_dir):
            if file.lower().endswith(MediaManager.ALLOWED_TYPES):
                self.add_media_file(os.path.join(self.media_dir, file))
        return self.all_media_files

    def add_media_file(self, file_path) -> None:
        img = ImageContainer()
        img.from_file(file_path, self.thumbnail_dir, self.thumbnail_width, self.thumbnail_height)
        self.all_media_files.append(img)
        if self.media_files_changed_callback is not None:
            self.media_files_changed_callback()

    def remove_media_file(self, file_path) -> None:
        for media in self.all_media_files:
            if media.file_path == file_path:
                self.all_media_files.remove(media)
                break

        for media in self.playlist:
            if media.file_path == file_path:
                self.playlist.remove(media)
                break
    
        if self.media_files_changed_callback is not None:
            self.media_files_changed_callback()

    def get_next_media(self) -> ImageContainer:
        if len(self.playlist) == 0:
            return None
        self.current_index = (self.current_index + 1) % len(self.playlist)
        self.current_media = self.playlist[self.current_index]
        # self.clear_memory()
        return self.current_media

    def get_prev_media(self) -> ImageContainer:
        if len(self.playlist) == 0:
            return None
        self.current_index = (self.current_index - 1) % len(self.playlist)
        self.current_media = self.playlist[self.current_index]
        return self.current_media

    def clear_memory(self) -> None:
        #look backwards at least 3 images in the playlist and free the memory 
        #but make sure the current image is not freed
        if len(self.playlist) < 3:
            return

        for i in range(self.current_index - 3, self.current_index):
            index = i % len(self.playlist)
            self.playlist[index].free_memory()

        # look forwards at least 2 images and preprocess them
        for i in range(self.current_index + 1, self.current_index + 3):
            index = i % len(self.playlist)
            self.playlist[index].check_processing_parameters()

    def get_current_media(self) -> ImageContainer:
        return self.current_media

    def get_media_files(self, orientation = None) -> List[ImageContainer]:
        if len(self.all_media_files) == 0:
            self.populate_media_files()

        if orientation is not None:
            if self.orientation_filter != orientation:
                self.orientation_filter = orientation
            return self.get_media_by_orientation(orientation)

        return self.all_media_files

    def get_current_playlist(self) -> List[ImageContainer]:
        return self.playlist

    def get_random_media(self, orientation = None) -> ImageContainer:
        if orientation is not None:
            media_files = self.get_media_by_orientation(orientation)
        else:
            media_files = self.all_media_files

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
        if orientation == 'both':
            return self.all_media_files
        return [media for media in self.all_media_files if media.orientation == orientation]

    def filter_media_by_orientation(self, orientation) -> None:
        self.playlist = self.get_media_by_orientation(orientation)

    def get_media_by_index(self, index) -> Optional[ImageContainer]:
        if index < 0 or index >= len(self.playlist):
            return None
        return self.playlist[index]

    def get_media_by_filename(self, filename) -> Optional[ImageContainer]:
        for media in self.playlist:
            if media.filename == filename:
                #get the index of the media file
                self.current_index = self.playlist.index(media)                
                return media
        return None

    def preprocess_media(self, target_height, target_width, scale_mode, angle) -> None:
        for media in self.all_media_files:
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
