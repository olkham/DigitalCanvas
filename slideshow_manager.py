from image_viewer import ImageViewer

class SlideshowManager:
    def __init__(self, 
                 folder, 
                 frame_interval=5, 
                 transition_duration=100, 
                 orientation="landscape", 
                 display_mode="fullscreen",
                 rotation=0,
                 scale_mode="fill",
                 auto_rotate=False,
                 auto_brightness=False):
        self.folder = folder
        self.frame_interval = frame_interval
        self.transition_duration = transition_duration
        self.orientation = orientation
        self.display_mode = display_mode
        self.rotation = rotation
        self.scale_mode = scale_mode
        
        self.viewer = None
        self.image_selection_queue = None
        self.image_change_callback = None
        
        self.auto_rotate = auto_rotate
        self.auto_brightness = auto_brightness

    def update_parameters(self, 
                          frame_interval=None, 
                          transition_duration=None, 
                          orientation=None,
                          display_mode=None,
                          rotation=None,
                          scale_mode=None):
        if frame_interval is not None and frame_interval >= 0 and frame_interval != self.frame_interval:
            self.frame_interval = frame_interval
        if transition_duration is not None and transition_duration >= 0 and transition_duration != self.transition_duration:
            self.transition_duration = transition_duration
        if orientation is not None and orientation in ["landscape", "portrait"] and orientation != self.orientation:
            self.orientation = orientation
        if display_mode is not None and display_mode in ["fullscreen", "windowed"] and display_mode != self.display_mode:
            self.display_mode = display_mode
        if rotation is not None and rotation in [0, 90, 180, 270] and rotation != self.rotation:
            self.rotation = rotation
        if scale_mode is not None and scale_mode in ["fill", "fit"] and scale_mode != self.scale_mode:
            self.scale_mode = scale_mode

        if self.viewer:
            self.viewer.update_parameters(frame_interval=self.frame_interval,
                                        transition_duration=self.transition_duration,
                                        orientation=self.orientation,
                                        display_mode=self.display_mode,
                                        rotation=self.rotation,
                                        scale_mode=self.scale_mode)

    def get_current_image_name(self):
        if self.viewer:
            return self.viewer.current_image_name

    def set_image_selection_queue(self, queue):
        self.image_selection_queue = queue

    def check_for_image_selection(self):
        if self.image_selection_queue and not self.image_selection_queue.empty():
            filename = self.image_selection_queue.get()
            self.select_image(filename)
        if self.viewer:
            self.viewer.root.after(100, self.check_for_image_selection)

    def start_slideshow(self):
        self.viewer = ImageViewer(self.folder, 
                                   self.frame_interval, 
                                   self.transition_duration, 
                                   self.orientation, 
                                   self.display_mode,
                                   self.rotation,
                                   self.scale_mode)
        self.viewer.image_change_callback = self.image_change_callback
        self.viewer.root.after(100, self.check_for_image_selection)
        self.viewer.run()

    def select_image_from_base64(self, base64_image, transition_duration=0):
        if self.viewer:
            self.viewer.select_image_from_base64(base64_image, transition_duration)

    def set_image(self, image_path, transition_duration=0):
        if self.viewer:
            self.viewer.set_image(image_path, transition_duration)

    def select_image(self, name):
        if self.viewer:
            self.viewer.select_image(name)

    def next_image(self):
        if self.viewer:
            self.viewer.next_image()

    def previous_image(self):
        if self.viewer:
            self.viewer.previous_image()

    def delete_image(self):
        if self.viewer:
            self.viewer.delete_image()

    def quit_slideshow(self):
        if self.viewer:
            self.viewer.quit_app()

    def pause_slideshow(self):
        if self.viewer:
            self.viewer.pause_slideshow()
            
    def resume_slideshow(self):
        if self.viewer:
            self.viewer.resume_slideshow()

    def set_image_change_callback(self, callback):
        self.viewer.image_change_callback = callback
        
    def is_running(self):
        return self.viewer.slideshow_active
    
    # def play_slideshow(self):
    #     if self.viewer:
    #         self.viewer.resume_slideshow()
            
    # def pause_slideshow(self):
        # if self.viewer:
            # self.viewer.slideshow_active = False