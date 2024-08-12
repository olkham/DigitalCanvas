import os
import time
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import tkinter as tk
from tkinter import filedialog, messagebox
from PIL import Image, ImageTk

class ConfigGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Slideshow Configuration")
        self.root.geometry("400x400")

        default_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "images")
        
        tk.Label(self.root, text="Input Folder:").pack(anchor='w', padx=10, pady=5)
        self.folder_entry = tk.Entry(self.root, width=50)
        self.folder_entry.insert(0, default_folder)
        self.folder_entry.pack(pady=5)
        tk.Button(self.root, text="Browse", command=self.browse_folder).pack()

        tk.Label(self.root, text="Slideshow Duration (seconds):").pack(anchor='w', padx=10, pady=5)
        self.duration_entry = tk.Entry(self.root)
        self.duration_entry.insert(0, "5")
        self.duration_entry.pack(pady=5)

        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        default_orientation = "landscape" if screen_width > screen_height else "portrait"

        self.orientation_var = tk.StringVar(value=default_orientation)
        tk.Label(self.root, text="Image Orientation:").pack(anchor='w', padx=10, pady=5)
        
        radio_frame = tk.Frame(self.root)
        radio_frame.pack(fill='x', padx=20)
        
        tk.Radiobutton(radio_frame, text="Both", variable=self.orientation_var, value="both").pack(anchor='w')
        tk.Radiobutton(radio_frame, text="Portrait", variable=self.orientation_var, value="portrait").pack(anchor='w')
        tk.Radiobutton(radio_frame, text="Landscape", variable=self.orientation_var, value="landscape").pack(anchor='w')

        self.display_mode_var = tk.StringVar(value="fullscreen")
        tk.Label(self.root, text="Display Mode:").pack(anchor='w', padx=10, pady=5)
        
        display_mode_frame = tk.Frame(self.root)
        display_mode_frame.pack(fill='x', padx=20)
        
        tk.Radiobutton(display_mode_frame, text="Fullscreen", variable=self.display_mode_var, value="fullscreen").pack(anchor='w')
        tk.Radiobutton(display_mode_frame, text="Windowed", variable=self.display_mode_var, value="windowed").pack(anchor='w')

        tk.Button(self.root, text="Start", command=self.start_slideshow).pack(side=tk.LEFT, padx=20, pady=20)
        tk.Button(self.root, text="Exit", command=self.root.quit).pack(side=tk.RIGHT, padx=20, pady=20)

    def browse_folder(self):
        folder_path = filedialog.askdirectory()
        if folder_path:
            self.folder_entry.delete(0, tk.END)
            self.folder_entry.insert(0, folder_path)

    def start_slideshow(self):
        folder = self.folder_entry.get()
        try:
            duration = float(self.duration_entry.get())
        except ValueError:
            messagebox.showerror("Error", "Invalid duration. Please enter a number.")
            return

        orientation = self.orientation_var.get()
        display_mode = self.display_mode_var.get()

        if not os.path.isdir(folder):
            messagebox.showerror("Error", "Invalid folder path.")
            return

        self.root.destroy()
        viewer = ImageViewer(folder, duration, orientation, display_mode)
        viewer.run()

    def run(self):
        self.root.mainloop()

class ImageHandler(FileSystemEventHandler):
    def __init__(self, add_image_function, remove_image_function):
        self.add_image_function = add_image_function
        self.remove_image_function = remove_image_function

    def on_created(self, event):
        if not event.is_directory and event.src_path.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp')):
            self.add_image_function(event.src_path)

    def on_deleted(self, event):
        if not event.is_directory and event.src_path.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp')):
            self.remove_image_function(event.src_path)

class ImageViewer:
    def __init__(self, folder_to_watch, interval=5, orientation="both", display_mode="fullscreen"):
        self.folder_to_watch = folder_to_watch
        self.interval = interval
        self.orientation = orientation
        self.display_mode = display_mode
        self.images = []
        self.current_image_index = 0
        self.slideshow_active = True
        self.transition_frames = 30

        self.transition_duration = 1000  # 1 second transition in milliseconds
        self.transition_step = 0
        self.current_after_id = None  # To keep track of the current after() call

        self.root = tk.Tk()
        if self.display_mode == "fullscreen":
            self.root.attributes('-fullscreen', True)
            self.root.config(cursor="none")
        else:
            self.root.geometry("800x600")
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

        self.root.focus_set()

    def scan_folder(self):
        for filename in os.listdir(self.folder_to_watch):
            if filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp')):
                self.add_image(os.path.join(self.folder_to_watch, filename))

    def add_image(self, image_path):
        if image_path not in self.images:
            if self.check_image_orientation(image_path):
                self.images.append(image_path)

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

    def display_image(self, direction=1):
        if not self.images:
            return

        try:
            current_index = self.current_image_index
            next_index = (current_index + direction) % len(self.images)
            
            current_image = Image.open(self.images[current_index]).convert('RGB')
            next_image = Image.open(self.images[next_index]).convert('RGB')

            screen_width = self.root.winfo_screenwidth()
            screen_height = self.root.winfo_screenheight()

            current_image = self.resize_image(current_image, screen_width, screen_height)
            next_image = self.resize_image(next_image, screen_width, screen_height)

            self.transition_step = 0
            self.current_image_index = next_index
            self.perform_transition(current_image, next_image)

        except Exception as e:
            print(f"Error displaying image: {e}")
            self.current_image_index = (self.current_image_index + direction) % len(self.images)
            self.root.after(100, lambda: self.display_image(direction))

    def perform_transition(self, current_image, next_image):
        alpha = self.transition_step / self.transition_frames
        blended_image = Image.blend(current_image, next_image, alpha)
        photo = ImageTk.PhotoImage(blended_image)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor=tk.NW, image=photo)
        self.canvas.image = photo

        self.transition_step += 1

        if self.transition_step <= self.transition_frames:
            self.current_after_id = self.root.after(
                int(self.transition_duration / self.transition_frames), 
                lambda: self.perform_transition(current_image, next_image)
            )
        elif self.slideshow_active:
            self.current_after_id = self.root.after(int(self.interval * 1000), self.display_image)

    def cancel_transition(self):
        if self.current_after_id:
            self.root.after_cancel(self.current_after_id)
            self.current_after_id = None

    def previous_image(self, event):
        # self.slideshow_active = False
        self.cancel_transition()
        if self.images:
            self.display_image(direction=-1)

    def next_image(self, event):
        # self.slideshow_active = False
        self.cancel_transition()
        if self.images:
            self.display_image(direction=1)

    def run(self):
        self.display_image()
        self.root.mainloop()

    def resize_image(self, image, screen_width, screen_height):
        img_width, img_height = image.size
        img_aspect = img_width / img_height
        screen_aspect = screen_width / screen_height

        if img_aspect > screen_aspect:
            new_height = int(screen_height)
            new_width = int(new_height * img_aspect)
        else:
            new_width = int(screen_width)
            new_height = int(new_width / img_aspect)

        resized_image = image.resize((new_width, new_height), Image.LANCZOS)

        left = (new_width - screen_width) / 2
        top = (new_height - screen_height) / 2
        right = left + screen_width
        bottom = top + screen_height

        return resized_image.crop((left, top, right, bottom))

    def quit_app(self, event=None):
        self.root.quit()

    def delete_image(self, event):
        if self.images:
            image_to_delete = self.images[self.current_image_index]
            try:
                os.remove(image_to_delete)
                self.remove_image(image_to_delete)
            except OSError as e:
                print(f"Error deleting file: {e}")

    def __del__(self):
        self.observer.stop()
        self.observer.join()

if __name__ == "__main__":
    config_gui = ConfigGUI()
    config_gui.run()