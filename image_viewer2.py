import tkinter as tk
from PIL import ImageTk
import numpy as np
from config_manager import ConfigManager
from media_manager import ImageContainer, MediaManager
from utils import cv2_crop_center, cv2_rotate_image, cv2_to_pil, cv_resize_to_target, quick_read_image

ALLOWED_TYPES = ('.png', '.jpg', '.jpeg', '.bmp', '.webp')
__OVERRIDDEN__ = '__overridden__'

class ImageViewer:
    def __init__(self, 
                 folder_to_watch,
                 config_manager=None):
        
        self.config_manager = config_manager
        self.frame_interval = self.config_manager['frame_interval']
        self.transition_duration = self.config_manager['transition_duration']
        self.media_orientation_filter = self.config_manager['media_orientation_filter']
        self.display_mode = self.config_manager['display_mode']
        self.rotation = self.config_manager['rotation']
        self.scale_mode = self.config_manager['scale_mode']
        self.auto_rotate = self.config_manager['auto_rotation']
        self.auto_brightness = self.config_manager['auto_brightness']
        self.transition_frames = 30

        self.media_manager = MediaManager(config_manager.config['image_folder'], config_manager.config['thumbnail_folder'], 200, 200)
        self.media_files = self.media_manager.get_media_files()
        
        self.current_image: ImageContainer = None
        
        self.slideshow_active = True

        self.transition_step = 0
        self.current_after_id = None
        self.transitioning = False
        self.current_displayed_image = None
        self.target_image = None
        self.blended_image = None
        
        self.image_change_callback = None
        self._current_image_name = ""
        
        self.create_ui()
        
        self.media_manager.preprocess_media(self.screen_height, 
                                    self.screen_width, 
                                    self.scale_mode, 
                                    self.rotation)

        self.current_image = self.media_manager.get_media_by_index(0)

    @property
    def current_image_name(self):
        return self._current_image_name

    @current_image_name.setter
    def current_image_name(self, name):
        self._current_image_name = name


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
        # self.root.bind('<Left>', self.previous_image)
        # self.root.bind('<Right>', self.next_image)
        # self.root.bind('<Delete>', self.delete_image)
        # self.root.bind(',', self.previous_image)
        # self.root.bind('.', self.next_image)
        self.root.focus_set()


    def set_display_mode(self, display_mode):
        self.display_mode = display_mode
        if self.display_mode == "fullscreen":
            self.root.attributes('-fullscreen', True)
            self.root.config(cursor="none")
        elif self.display_mode == "windowed":
            self.root.attributes('-fullscreen', False)
            self.root.geometry("800x600")
            self.root.config(cursor="arrow")


    def get_image_name_from_index(self, index):
        media = self.media_manager.get_media_by_index(index)
        if media:
            return media.filename
        return None

    def display_image(self, direction=1):
        pass
        # if not self.media_manager.media_files:
        #     return
        
        # self.current_image_index = (self.current_image_index + direction) % len(self.media_manager.media_files)
        # media = self.media_manager.get_media_by_index(self.current_image_index)
        # if media:
        #     self.set_image(media.get_processed_image())


    def display_image_by_name(self, filename):
        pass
        # media = self.media_manager.get_media_by_filename(filename)
        # if media:
        #     self.set_image(media.get_processed_image())

    def set_image(self, image, transition_duration=None):
        pass
        # try:
        #     self.current_displayed_image = ImageTk.PhotoImage(image=cv2_to_pil(image))
        #     self.canvas.create_image(0, 0, anchor=tk.NW, image=self.current_displayed_image)
        # except Exception as e:
        #     print(f"Error setting image: {e}")

    def select_image_from_base64(self, base64_image, trasition_duration=0):
        pass
        # try:
        #     image = quick_read_image(base64_image)
        #     self.set_image(image)
        # except Exception as e:
        #     print(f"Error selecting image from base64: {e}")

    def set_image_no_transition(self, image):
        self.cancel_transition()
        self.render_image(image)

        # if self.slideshow_active:
        #     self.root.after(self.frame_interval, self.next_image)

    def start_transition(self, next_image, transition_duration=None):
        pass
        # next_image = self.process_image(next_image)
        
        # if transition_duration is None:
        #     transition_duration = self.transition_duration
        
        # if transition_duration == 0:
        #     self.set_image_no_transition(next_image)
        #     return
        
        # self.cancel_transition()
        # self.transition_step = 0
        # self.transitioning = True
    
        # if next_image.shape != self.current_displayed_image.shape:
        #     next_image = cv2_crop_center(next_image, self.current_displayed_image.shape[:2])

        # self.target_image = next_image
        # self.perform_transition(transition_duration)

        
    def render_image(self, image: np.ndarray):
        '''
        Update the current displayed image
        '''
        self.current_displayed_image = image
        self.current_image.from_image(image)
        self.blended_image = image
        photo = ImageTk.PhotoImage(cv2_to_pil(image))
        self.canvas.delete("all")
        width, height = photo.width(), photo.height()
        self.canvas.create_image(width // 2, height // 2, anchor=tk.CENTER, image=photo)
        self.canvas.image = photo
        

    def transition_to(self, target_image: ImageContainer, transition_duration=None):
        #this function should progressivly blend from the current image to the target image
        
        if not target_image:
            return
        
        if transition_duration is None:
            transition_duration = self.transition_duration
            
        if transition_duration == 0:
            self.set_image_no_transition(target_image.get_processed_image())
            return  
        
        self.cancel_transition()
        self.transition_step = 0
        self.transitioning = True
        self.target_image = target_image.get_processed_image()
        self.perform_transition(transition_duration)
        
        pass
        # if not self.transitioning:
        #     return
        
        # alpha = self.transition_step / self.transition_frames        
        # self.blended_image = self.current_image.blend_image(target_image.get_processed_image(), alpha)
        
        # self.render_image(self.blended_image)
        
        # self.transition_step += 1
        # if self.transition_step >= self.transition_frames:
        #     self.transitioning = False
        #     self.render_image(self.target_image)
        # else:
        #     self.current_after_id = self.root.after(int(transition_duration / self.transition_frames), self.perform_transition, transition_duration)

    def perform_transition(self, transition_duration):
        if not self.transitioning:
            return
        
        alpha = self.transition_step / self.transition_frames
        self.blended_image = self.current_image.blend_image(self.target_image, alpha)
        
        self.render_image(self.blended_image)
        
        self.transition_step += 1
        if self.transition_step <= self.transition_frames:
            self.current_after_id = self.root.after(
                int(1000 * transition_duration / self.transition_frames), 
                self.perform_transition
            )
        else:
            self.transitioning = False
            self.current_displayed_image = self.target_image
            if self.slideshow_active:
                trigger_in = int(self.frame_interval * 1000)
                next_image = self.media_manager.get_next_media()
                self.current_after_id = self.root.after(trigger_in, self.transition_to, next_image)


    def cancel_transition(self):
        if self.current_after_id:
            self.root.after_cancel(self.current_after_id)
            self.current_after_id = None
        self.transitioning = False

    def select_image(self, name):
        media = self.media_manager.get_media_by_filename(name)
        if media:
            self.target_image = media
            self.perform_transition_to(self.target_image)


    def run(self):
        self.transition_to(self.current_image, 0)
        self.root.mainloop()

    def quit_app(self, event=None):
        self.root.quit()



if __name__ == '__main__':
    config_manager = ConfigManager('config.json')  
    viewer = ImageViewer(folder_to_watch='images', 
                         config_manager=config_manager)
    viewer.run()