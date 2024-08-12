import base64
import os
import time
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import tkinter as tk
from PIL import Image, ImageTk
import io
from utils import crop_center, resize_to_target

ALLOWED_TYPES = ('.png', '.jpg', '.jpeg', '.bmp', '.webp')


class ImageHandler(FileSystemEventHandler):
    def __init__(self, add_image_function, remove_image_function):
        self.add_image_function = add_image_function
        self.remove_image_function = remove_image_function

    def on_created(self, event):
        if not event.is_directory and event.src_path.lower().endswith(ALLOWED_TYPES):
            time.sleep(1)
            self.add_image_function(event.src_path)

    def on_deleted(self, event):
        if not event.is_directory and event.src_path.lower().endswith(ALLOWED_TYPES):
            self.remove_image_function(event.src_path)


class ImageViewer:
    def __init__(self, 
                 folder_to_watch, 
                 frame_interval=5, 
                 transition_duration=5, 
                 orientation="both", 
                 display_mode="fullscreen",
                 rotation=0,
                 scale_mode='fill'):
        
        self.folder_to_watch = folder_to_watch
        self.frame_interval = frame_interval
        self.orientation = orientation
        self.display_mode = display_mode
        self.rotation = rotation
        self.scale_mode = scale_mode
        
        self.images = []
        
        self.current_image_index = -1   #start at -1 so that the first image will be 0
        self.slideshow_active = True
        self.transition_frames = 60

        self.transition_duration = transition_duration
        self.transition_step = 0
        self.current_after_id = None
        self.transitioning = False
        self.current_displayed_image = None
        self.target_image = None
        self.blended_image = None
        
        self.image_change_callback = None
        self._current_image_name = ""
        
        self.root = tk.Tk()
        
        self.screen_width = self.root.winfo_screenwidth()
        self.screen_height = self.root.winfo_screenheight()
        
        if self.display_mode == "fullscreen":
            self.root.attributes('-fullscreen', True)
            self.root.config(cursor="none")
        else:
            self.root.geometry(f"{self.screen_width//4}x{self.screen_height//4}")
        self.root.configure(background='black')

        self.canvas = tk.Canvas(self.root, highlightthickness=0)
        self.canvas.configure(background='black')
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.scan_folder()
        
        self.observer = Observer()
        self.observer.schedule(ImageHandler(self.add_image, self.remove_image), self.folder_to_watch, recursive=False)
        self.observer.start()

        self.root.bind('<Escape>', self.quit_app)
        self.root.bind('q', self.quit_app)
        self.root.bind('<Left>', self.previous_image)
        self.root.bind('<Right>', self.next_image)
        self.root.bind('<Delete>', self.delete_image)
        self.root.bind(',', self.previous_image)
        self.root.bind('.', self.next_image)

        if self.current_displayed_image is None:
            self.current_displayed_image = Image.new('RGB', (self.screen_width, self.screen_height), color='black')

        self.root.focus_set()

    @property
    def current_image_name(self):
        return self._current_image_name

    @current_image_name.setter
    def current_image_name(self, name):
        self._current_image_name = name
        if self.image_change_callback:
            self.image_change_callback(name)

    def set_display_mode(self, display_mode):
        self.display_mode = display_mode
        if self.display_mode == "fullscreen":
            self.root.attributes('-fullscreen', True)
            self.root.config(cursor="none")
        elif self.display_mode == "windowed":
            self.root.attributes('-fullscreen', False)
            self.root.geometry("800x600")
            self.root.config(cursor="arrow")

    def set_orientation(self, orientation):
        self.orientation = orientation

    def scan_folder(self):
        for filename in os.listdir(self.folder_to_watch):
            if filename.lower().endswith(ALLOWED_TYPES):
                self.add_image(os.path.join(self.folder_to_watch, filename))

    def image_orientation(self, image_path):
        try:
            with Image.open(image_path) as img:
                width, height = img.size
                is_portrait = height > width
                if is_portrait:
                    return 'portrait'
                else:
                    return 'landscape'
        except Exception as e:
            print(f"Error checking image orientation: {e}")

    def add_image(self, image_path):
        if image_path not in self.images:
            self.images.append(image_path)

    def update_parameters(self,
                          frame_interval=None, 
                          transition_duration=None, 
                          orientation=None,
                          display_mode=None,
                          rotation=None,
                          scale_mode=None):
        if frame_interval is not None and frame_interval != self.frame_interval:
            self.frame_interval = frame_interval
        if transition_duration is not None and transition_duration != self.transition_duration:
            self.transition_duration = transition_duration
        if orientation is not None and orientation != self.orientation:
            self.set_orientation(orientation)
            self.display_image(0)   #refresh the image with the new display mode
        if display_mode is not None and display_mode != self.display_mode:
            self.set_display_mode(display_mode)
        if rotation is not None and rotation != self.rotation:
            self.rotation = rotation
            self.display_image(0)   #refresh the image with the new rotation
        if scale_mode is not None and scale_mode != self.scale_mode:
            self.scale_mode = scale_mode
            self.display_image(0)   #refresh the image with the new scale mode

    def remove_image(self, image_path):
        if image_path in self.images:
            index = self.images.index(image_path)
            self.images.remove(image_path)
            if self.current_image_index >= len(self.images):
                self.current_image_index = 0
            elif index < self.current_image_index:
                self.current_image_index -= 1
            if not self.images:
                self.canvas.delete("all")
            else:
                self.display_image()

    def check_image_orientation(self, image_path):
        try:
            with Image.open(image_path) as img:
                width, height = img.size
                is_portrait = height > width
                
                if self.orientation == "both":
                    return True
                elif self.orientation == "portrait" and is_portrait:
                    return True
                elif self.orientation == "landscape" and not is_portrait:
                    return True
                else:
                    return False
        except Exception as e:
            print(f"Error checking image orientation: {e}")
            return False

    def get_image_name_from_index(self, index):
        if type(index) == int:
           return os.path.basename(self.images[index])
        elif type(index) == str:
            return index

    def display_image(self, direction=1):
        if not self.images:
            return
        
        if direction >= len(self.images):
            return
        
        if direction == 0:
            self.cancel_transition()

        try:
            next_index = (self.current_image_index + direction) % len(self.images)
            if not self.check_image_orientation(self.images[next_index]):
                self.display_image(direction=direction+1)
            else:
                next_image = Image.open(self.images[next_index]).convert('RGB')
                self.start_transition(next_image)
                self.current_image_index = next_index
                self.current_image_name = self.get_image_name_from_index(self.current_image_index)
            
        except Exception as e:
            print(f"Error displaying image: {e}")
            self.current_image_index = (self.current_image_index + direction) % len(self.images)
            self.root.after(100, lambda: self.display_image(direction))

    def process_image(self, image:Image):
        image = image.rotate(self.rotation, expand=True)
        image = resize_to_target(image, self.current_displayed_image, self.scale_mode)
        if image.size != self.current_displayed_image.size:
            image = crop_center(image, self.current_displayed_image.size)
        return image

    def display_image_by_name(self, filename):
        if not self.images:
            return

        try:
            next_index = next((i for i, path in enumerate(self.images) if os.path.basename(path) == filename), None)
            if next_index is None:
                print(f"Image {filename} not found in the current list of images.")
                return

            next_image = Image.open(self.images[next_index]).convert('RGB')
            self.start_transition(next_image)
            self.current_image_index = next_index
            self.current_image_name = filename
            
        except Exception as e:
            print(f"Error displaying image: {e}")

    def set_image(self, image, transition_duration=None):
        try:
            self.start_transition(image, transition_duration)
            self.current_image_name = "__overridden__"
        except Exception as e:
            print(f"Error displaying image): {e}")

    def select_image_from_base64(self, base64_image, trasition_duration=0):
        '''
        Display an image from a base64 string without transitioning
        '''
        try:
            image_data = base64.b64decode(base64_image)
            image = Image.open(io.BytesIO(image_data)).convert('RGB')
            self.start_transition(image, transition_duration=trasition_duration)
            self.current_image_name = "__overridden__"
        except Exception as e:
            print(f"Error displaying image: {e}")

    def set_image_no_transition(self, image):
        '''
        Display an image without transitioning
        '''
        self.cancel_transition()
        self.render_image(image)

        if self.slideshow_active:
            self.current_after_id = self.root.after(int(self.frame_interval * 1000), self.display_image)

    def start_transition(self, next_image, transition_duration=None):
        '''
        Start transitioning from the current image to the next image
        '''
        next_image = self.process_image(next_image)
        
        if transition_duration == 0:
            self.set_image_no_transition(next_image)
            return
        
        self.cancel_transition()
        self.transition_step = 0
        self.transitioning = True
    
        #if next image size is different from current image size, take a center crop of the next image to match the current image size
        if next_image.size != self.current_displayed_image.size:
            next_image = crop_center(next_image, self.current_displayed_image.size)

        if self.transitioning and self.blended_image is not None:
            self.current_displayed_image = self.blended_image
    
        self.target_image = next_image
        self.perform_transition(transition_duration=transition_duration)
    
    def render_image(self, image):
        '''
        Update the current displayed image
        '''
        self.current_displayed_image = image
        self.blended_image = image
        photo = ImageTk.PhotoImage(image)
        self.canvas.delete("all")
        width, height = photo.width(), photo.height()
        self.canvas.create_image(width // 2, height // 2, anchor=tk.CENTER, image=photo)
        self.canvas.image = photo

    def perform_transition(self, transition_duration=None):
        '''
        Perform the transition from the current image to the next image
        '''
        
        if transition_duration is None:
            transition_duration = self.transition_duration
            
        # Store the original image before starting the transition
        if self.transition_step == 0:
            self.original_displayed_image = self.current_displayed_image.copy()

        # Calculate the alpha value for blending
        alpha = self.transition_step / self.transition_frames

        # Blend using the original image and the target image
        self.blended_image = Image.blend(self.original_displayed_image, self.target_image, alpha)

        # Update the displayed image
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
                self.current_after_id = self.root.after(int(self.frame_interval * 1000), self.display_image)

    def cancel_transition(self):
        if self.current_after_id:
            self.root.after_cancel(self.current_after_id)
            self.current_after_id = None

    def select_image(self, name):
        if self.images:
            self.display_image_by_name(name)

    def previous_image(self, event=None):
        if self.images:
            if event is not None:
                if event.char == ",":
                    image = Image.open(self.get_previous_image()).convert('RGB')
                    self.set_image_no_transition(image=image)
            self.display_image(direction=-1)

    def next_image(self, event=None):
        if self.images:
            if event is not None:
                if event.char == ".":
                    image = Image.open(self.get_next_image()).convert('RGB')
                    self.set_image_no_transition(image=image)
            else:
                self.display_image(direction=1)
        
    def get_next_image(self):
        if self.images:
            return self.images[(self.current_image_index + 1) % len(self.images)]
        
    def get_previous_image(self):
        if self.images:
            return self.images[(self.current_image_index - 1) % len(self.images)]

    def run(self):
        self.display_image()
        self.root.mainloop()

    def quit_app(self, event=None):
        self.root.quit()

    def delete_image(self, event=None):
        if self.images:
            image_to_delete = self.images[self.current_image_index]
            try:
                os.remove(image_to_delete)
                self.remove_image(image_to_delete)
            except OSError as e:
                print(f"Error deleting file: {e}")

    def set_image_change_callback(self, callback):
        self.image_change_callback = callback

    def pause_slideshow(self):
        self.slideshow_active = False
        # self.cancel_transition()
        
    def resume_slideshow(self):
        self.slideshow_active = True
        self.display_image()

    def __del__(self):
        self.observer.stop()
        self.observer.join()

if __name__ == '__main__':
    viewer = ImageViewer(folder_to_watch='images', 
                         frame_interval=2, 
                         transition_duration=1, 
                         orientation='landscape', 
                         display_mode='fullscreen', 
                         rotation=0,
                         scale_mode='fit')
    viewer.run()