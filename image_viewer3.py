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

import time
import tkinter as tk
from PIL import ImageTk
from config_manager import ConfigManager
from media_manager import MediaManager
from image_container import ImageContainer
from utils import cv2_to_pil
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
        self._next_image_job_id = None
        self._transition_job_id = None
        self._media_orientation_filter = None
        
        # the current image as ImageContainer
        self.current_image: ImageContainer = None
        self.canvas_image: np.ndarray = None

        # make the UI
        self.create_ui()

        #set the initial values from the configuration        
        self.display_mode = self.config_manager.config['display_mode']
        self.scale_mode = self.config_manager.config['scale_mode']
        self.rotation = self.config_manager.config['rotation']
        self.frame_interval = self.config_manager.config['frame_interval']
        self.transition_duration = self.config_manager.config['transition_duration']
        self.media_orientation_filter = self.config_manager.config['media_orientation_filter']
        
        #preprocess the media
        self.media_manager.preprocess_media(self.screen_height, 
                                            self.screen_width, 
                                            self.scale_mode, 
                                            self.rotation)
        
        #set the initial image
        self.current_image = self.media_manager.get_media_by_index(0)
        self.canvas_image = self.current_image.get_processed_image()
        self.update_canvas()

        self.image_change_callback = None
        
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
        self.root.bind('a', self.rotate_image)
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
                    self.current_image.check_processing_parameters(self.screen_height, self.screen_width, self.scale_mode, self.rotation)
                    self.fade_to_image(self.current_image, self.transition_duration)

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
                    self.current_image.check_processing_parameters(self.screen_height, self.screen_width, self.scale_mode, self.rotation)
                    self.fade_to_image(self.current_image, self.transition_duration)
                    

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
    def next_image_job_id(self):
        return self._next_image_job_id
    
    @next_image_job_id.setter
    def next_image_job_id(self, id):
        if self._next_image_job_id is not None:
            self.root.after_cancel(self._next_image_job_id)
        self._next_image_job_id = id
    
    
    @property
    def transition_job_id(self):
        return self._transition_job_id
    
    @transition_job_id.setter
    def transition_job_id(self, id):
        if self._transition_job_id is not None:
            self.root.after_cancel(self._transition_job_id)
        self._transition_job_id = id
    
    
    @property
    def current_image_name(self):
        return self.current_image.filename
    
    
    @property
    def media_orientation_filter(self):
        return self._media_orientation_filter
    
    @media_orientation_filter.setter
    def media_orientation_filter(self, orientation):
        if ConfigManager.is_valid_value('media_orientation_filter', orientation):
            if self._media_orientation_filter != orientation:
                self._media_orientation_filter = orientation
                self.config_manager.update_parameter('media_orientation_filter', orientation)
                self.media_manager.filter_media_by_orientation(self.media_orientation_filter)
    
    
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
    
    def rotate_image(self, event=None):
        self.rotation = (self.rotation + 90) % 360
           
           
    def update_parameters(self, display_mode=None, scale_mode=None, rotation=None, frame_interval=None, transition_duration=None,
                          auto_brightness=None, auto_rotation=None, media_orientation_filter=None):
        if display_mode is not None:
            self.display_mode = display_mode
        if scale_mode is not None:
            self.scale_mode = scale_mode
        if rotation is not None:
            self.rotation = rotation
        if frame_interval is not None:
            self.frame_interval = frame_interval
        if transition_duration is not None:
            self.transition_duration = transition_duration
        if auto_brightness is not None:
            self.auto_brightness = auto_brightness
        if auto_rotation is not None:
            self.auto_rotation = auto_rotation
        if media_orientation_filter is not None:
            self.media_orientation_filter = media_orientation_filter

    def update_canvas(self):
        '''
        Update the current displayed image
        '''
        # photo = ImageTk.PhotoImage(cv2_to_pil(self.canvas_image))
        # self.canvas.delete("all")
        # width, height = photo.width(), photo.height()
        # self.canvas.create_image(width // 2, height // 2, anchor=tk.CENTER, image=photo)
        # self.canvas.image = photo

        photo = ImageTk.PhotoImage(cv2_to_pil(self.canvas_image))
        width, height = photo.width(), photo.height()

        # Check if an image already exists on the canvas
        if hasattr(self.canvas, 'image_id'):
            # Update the existing image
            self.canvas.itemconfig(self.canvas.image_id, image=photo)
        else:
            # Create a new image if it doesn't exist
            self.canvas.image_id = self.canvas.create_image(width // 2, height // 2, anchor=tk.CENTER, image=photo)

        # Store the reference to the photo to prevent garbage collection
        self.canvas.image = photo    
    
    def set_image_from_url(self, url: str):
        image = ImageContainer()
        image.from_url(url)
        self.fade_to_image(image, self.transition_duration)
    
    def set_image(self, image: np.ndarray, title: str='plex_image'):
        plex_image = ImageContainer()
        plex_image.from_image(image, filename=title)
        plex_image.check_processing_parameters(self.screen_height, self.screen_width, self.scale_mode, self.rotation)
        self.fade_to_image(plex_image, self.transition_duration)
    
    def set_image_from_base64(self, base64_image: str, name: str='remote_image'):
        self.next_image_job_id = None
        self.transition_job_id = None
        remote_image = ImageContainer()
        remote_image.from_base64(base64_image, filename=name)
        remote_image.check_processing_parameters(self.screen_height, self.screen_width, self.scale_mode, self.rotation)
        self.fade_to_image(remote_image, self.transition_duration)
    
    def select_image(self, image_name: str):
        #find the image from the MediaManager with the matching name
        self.next_image_job_id = None
        self.transition_job_id = None
        image = self.media_manager.get_media_by_filename(image_name)
        image.check_processing_parameters(self.screen_height, self.screen_width, self.scale_mode, self.rotation)
        self.fade_to_image(image, self.transition_duration)
    
    def fade_to_image(self, to_image: ImageContainer, duration: float):
        self.current_image = to_image
        self.fade_in_progress = True
        self.fade_start_time = time.time()
        self.fade_from_image = self.canvas_image
        to_image.check_processing_parameters(self.screen_height, self.screen_width, self.scale_mode, self.rotation) 
        self.target_image = to_image.get_processed_image()
        if self.target_image is None:
            self.target_image = self.canvas_image
            return
        self.fade_duration = duration
        self._fade_step()

    def _fade_step(self):
        if not self.fade_in_progress:
            return

        current_time = time.time()
        elapsed_time = current_time - self.fade_start_time
        if self.fade_duration == 0:
            progress = 1.0
        else:
            progress = min(elapsed_time / self.fade_duration, 1.0)

        self.canvas_image = cv2.addWeighted(
            self.fade_from_image, 1 - progress,
            self.target_image, progress,
            0
        )

        self.update_canvas()

        if progress < 1.0:
            self.transition_job_id = self.root.after(33, self._fade_step)  # Approximately 30 FPS
        else:
            self.fade_in_progress = False
            if self.slideshow_active:
                self.next_image_job_id = self.root.after(int(self.frame_interval * 1000), self.show_next_image)
                # self.current_image = self.target_image
        
    def quit_app(self, event=None):
        self.root.quit()
    
    def run(self):
        self.play_slideshow()
        self.root.mainloop()
    
    def pause_slideshow(self, event=None):  
        self.slideshow_active = False
        self.next_image_job_id = None
        self.transition_job_id = None
        
    def play_slideshow(self, event=None):
        if self.slideshow_active and self.next_image_job_id is not None:
            #slideshow is already running and a scheduled id is set
            return
        self.slideshow_active = True
        self.next_image_job_id = self.root.after(int(self.frame_interval * 1000), self.show_next_image)
    
    def show_next_image(self, event=None):
        self.next_image = self.media_manager.get_next_media()
        self.next_image.check_processing_parameters(self.screen_height, self.screen_width, self.scale_mode, self.rotation)
        
        self.fade_to_image(self.next_image, self.transition_duration)
        
        self.current_image = self.next_image
        if self.slideshow_active:
            self.next_image_job_id = self.root.after(int(self.frame_interval * 1000), self.show_next_image)

    def show_previous_image(self, event=None):
        self.next_image = self.media_manager.get_prev_media()
        self.next_image.check_processing_parameters(self.screen_height, self.screen_width, self.scale_mode, self.rotation)
        
        self.fade_to_image(self.next_image, self.transition_duration)
        
        self.current_image = self.next_image
        if self.slideshow_active:
            self.next_image_job_id = self.root.after(int(self.frame_interval * 1000), self.show_next_image)
        
    def quit_slideshow(self):
        pass
    
    
if __name__ == "__main__":
    config_manager = ConfigManager('config.json')
    viewer = ImageViewer(config_manager)
    viewer.run()