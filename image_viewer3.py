# create a class that will create a TK based image viewer
# it should have the following methods:
# - select_image(image_path) - this will display the image at the given path
# - select_image_from_base64(base64_image) - this will display the image from a base64 encoded string


# - set_display_mode(mode) - this will set the display mode (fullscreen or windowed)
# - set_scale_mode(mode) - this will set the scale mode (fit or fill)
# - set_rotation(rotation) - this will set the rotation of the image (0, 90, 180, 270)
# - quit_app() - this will close the application
# - run() - this will start the application will will display a slideshow of images

#the class should use the following libraries:
# - tkinter
# - MediaManager
# - ImageContainer
# - ConfigManager
# from utils import cv2_crop_center, cv2_rotate_image, cv2_to_pil, cv_resize_to_target, quick_read_image


# the application will show an image based on the configuration settings
# images will be displayed for a set amount of time, frame_interval, before transitioning to the next image
# the transition will be a crossfade effect and last for a duration transition_duration
# the application will have a method to pause the slideshow
# the application will have a method to resume the slideshow
# the application will have a method to go to the next image
# the application will have a method to go to the previous image
# the application will have a method to quit the slideshow
# the application will have an option to ransomise the next image

import base64
import os
import time
import tkinter as tk
from PIL import ImageTk
from config_manager import ConfigManager
from media_manager import ImageContainer, MediaManager
from utils import cv2_crop_center, cv2_rotate_image, cv2_to_pil, cv_resize_to_target, quick_read_image
import cv2
import numpy as np

class ImageViewer:
    def __init__(self, config_manager: ConfigManager):
        
        #objects
        self.config_manager = config_manager
        self.media_manager = MediaManager(config_manager.config['image_folder'], config_manager.config['thumbnail_folder'], 200, 200)
        self.media_files = self.media_manager.get_media_files()
        self.media_manager.create_playlist()

        #internal variables    
        self._display_mode = None
        self._scale_mode = None
        self._rotation = None
        self._slideshow_active = True
        self._frame_interval = 0
        self._transition_duration = 0
        self._scheduled_id = None
        
        # the current image as ImageContainer
        self.current_image = None
        
        # make the UI
        self.create_ui()

        #set the initial values from the configuration        
        self.display_mode = self.config_manager.config['display_mode']
        self.scale_mode = self.config_manager.config['scale_mode']
        self.rotation = self.config_manager.config['rotation']
        self.frame_interval = self.config_manager.config['frame_interval']
        self.transition_duration = self.config_manager.config['transition_duration']
        
        #preprocess the media
        self.media_manager.preprocess_media(self.screen_height, 
                                            self.screen_width, 
                                            self.scale_mode, 
                                            self.rotation)
        
        #set the initial image
        self.current_image = self.media_manager.get_media_by_index(0)
        self.render_image(self.current_image.get_processed_image())
        
        
    def create_ui(self):
        self.root = tk.Tk()
        
        self.screen_width = self.root.winfo_screenwidth()
        self.screen_height = self.root.winfo_screenheight()
        
        if self.display_mode == "fullscreen":
            self.root.attributes('-fullscreen', True)
        else:
            self.root.geometry(f"{self.screen_width}x{self.screen_height}")
        
        self.root.configure(background='black')

        self.canvas = tk.Canvas(self.root, highlightthickness=0)
        self.canvas.configure(background='black')
        self.canvas.pack(fill=tk.BOTH, expand=True)
        
        self.root.bind('<Escape>', self.quit_app)
        self.root.bind('q', self.quit_app)
        self.root.bind('<Left>', self.show_previous_image)
        self.root.bind('<Right>', self.show_next_image)
        # self.root.bind('<Delete>', self.delete_image)
        self.root.bind('f', self.toggle_fullscreen)
        self.root.bind('s', self.toggle_scale_mode)
        self.root.bind('p', self.pause_slideshow)
        self.root.bind('r', self.play_slideshow)
        self.root.focus_set()

    
    @property
    def display_mode(self):
        return self._display_mode

    @display_mode.setter
    def display_mode(self, mode):
        if ConfigManager.is_valid_value('display_mode', mode):
            if self._display_mode != mode:
                self._display_mode = mode
                if self.display_mode == "fullscreen":
                    self.root.attributes('-fullscreen', True)
                    self.root.config(cursor="none")
                elif self.display_mode == "windowed":
                    self.root.attributes('-fullscreen', False)
                    self.root.geometry("800x600")
                    self.root.config(cursor="arrow")
                self.config_manager.update_parameter('display_mode', mode)


    @property
    def scale_mode(self):
        return self._scale_mode

    @scale_mode.setter
    def scale_mode(self, mode):
        if ConfigManager.is_valid_value('scale_mode', mode):
            if self._scale_mode != mode:
                self._scale_mode = mode
                self.config_manager.update_parameter('scale_mode', mode)
                if self.current_image is not None:
                    self.show_image(self.current_image)


    @property
    def rotation(self):
        return self._rotation

    @rotation.setter
    def rotation(self, rotation):
        if ConfigManager.is_valid_value('rotation', rotation):
            if self._rotation != rotation:
                self._rotation = rotation
                self.config_manager.update_parameter('rotation', rotation)
                if self.current_image is not None:
                    self.show_image(self.current_image)


    @property
    def slideshow_active(self):
        return self._slideshow_active

    @slideshow_active.setter
    def slideshow_active(self, state):
        if isinstance(state, bool):
            if self._slideshow_active != state:
                if state:
                    self._slideshow_active = True
                else:
                    self._slideshow_active = False
                
    
    
    @property
    def frame_interval(self):
        return self._frame_interval
    
    @frame_interval.setter
    def frame_interval(self, interval):
        self._frame_interval = interval
        
    @property
    def transition_duration(self):
        return self._transition_duration
    
    @transition_duration.setter
    def transition_duration(self, duration):
        self._transition_duration = duration
    
    
    @property
    def scheduled_id(self):
        return self._scheduled_id
    
    @scheduled_id.setter
    def scheduled_id(self, id):
        if self._scheduled_id is not None:
            self.root.after_cancel(self._scheduled_id)
        self._scheduled_id = id
    
    
    def toggle_fullscreen(self, event=None):
        if self.display_mode == "fullscreen":
            self.display_mode = "windowed"
        else:    
            self.display_mode = "fullscreen"
            

    def toggle_scale_mode(self, event=None):
        if self.scale_mode == "fit":
            self.scale_mode = "fill"
        else:
            self.scale_mode = "fit"
    
    
    def render_image(self, image):
        '''
        Update the current displayed image
        '''
        self.current_displayed_image = image
        self.blended_image = image
        photo = ImageTk.PhotoImage(cv2_to_pil(image))
        self.canvas.delete("all")
        width, height = photo.width(), photo.height()
        self.canvas.create_image(width // 2, height // 2, anchor=tk.CENTER, image=photo)
        self.canvas.image = photo
    
    def select_image(self, image_name):
        pass
    
    def select_image_from_base64(self, base64_image):
        pass

    def cross_fade(self, image1:ImageContainer, image2:ImageContainer, alpha):
        #blend the two images together
        blended_image = image1.blend_image(image2, alpha)
        self.render_image(blended_image)
    
    def show_image(self, image: ImageContainer):
        image.check_processing_parameters(self.screen_height, self.screen_width, self.scale_mode, self.rotation)
        self.render_image(image.get_processed_image())
        self.current_image = image
    
        
    def quit_app(self, event=None):
        self.root.quit()
    
    def run(self):
        self.play_slideshow()
        self.root.mainloop()
    
    def pause_slideshow(self, event=None):  
        self.slideshow_active = False
        self.scheduled_id = None
        
    def play_slideshow(self, event=None):
        self.slideshow_active = True
        if self.slideshow_active:
            self.scheduled_id = self.root.after(int(self.frame_interval * 1000), self.show_next_image)
    
    def show_next_image(self, event=None):
        self.next_image = self.media_manager.get_next_media()
        self.next_image.check_processing_parameters(self.screen_height, self.screen_width, self.scale_mode, self.rotation)
        self.render_image(self.next_image.get_processed_image())
        self.current_image = self.next_image
        
        if self.slideshow_active:
            self.scheduled_id = self.root.after(int(self.frame_interval * 1000), self.show_next_image)

    def show_previous_image(self, event=None):
        self.next_image = self.media_manager.get_prev_media()
        self.next_image.check_processing_parameters(self.screen_height, self.screen_width, self.scale_mode, self.rotation)
        self.render_image(self.next_image.get_processed_image())
        self.current_image = self.next_image
        
    def quit_slideshow(self):
        pass
    
    
if __name__ == "__main__":
    config_manager = ConfigManager('config.json')
    viewer = ImageViewer(config_manager)
    viewer.run()