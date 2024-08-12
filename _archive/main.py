import os
import time
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import tkinter as tk
from PIL import Image, ImageTk

class ImageHandler(FileSystemEventHandler):
    def __init__(self, add_image_function):
        self.add_image_function = add_image_function

    def on_created(self, event):
        if not event.is_directory and event.src_path.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp')):
            self.add_image_function(event.src_path)

class FullScreenImageViewer:
    def __init__(self, folder_to_watch, interval=5):
        self.folder_to_watch = folder_to_watch
        self.interval = interval  # Slideshow interval in seconds
        self.images = []
        self.current_image_index = 0
        self.slideshow_active = True

        self.root = tk.Tk()
        self.root.attributes('-fullscreen', True)
        self.root.config(cursor="none")  # Hide cursor
        self.label = tk.Label(self.root)
        self.label.pack(fill=tk.BOTH, expand=True)

        self.scan_folder()
        
        self.observer = Observer()
        self.observer.schedule(ImageHandler(self.add_image), self.folder_to_watch, recursive=False)
        self.observer.start()

        # Bind key events
        self.root.bind('<Escape>', self.quit_app)
        self.root.bind('q', self.quit_app)
        self.root.bind('<Left>', self.previous_image)
        self.root.bind('<Right>', self.next_image)
        self.root.bind('<Delete>', self.delete_image)

    def scan_folder(self):
        for filename in os.listdir(self.folder_to_watch):
            if filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp')):
                self.add_image(os.path.join(self.folder_to_watch, filename))

    def add_image(self, image_path):
        if image_path not in self.images:
            self.images.append(image_path)

    def display_image(self):
        if self.images:
            image_path = self.images[self.current_image_index]
            image = Image.open(image_path)
            screen_width = self.root.winfo_screenwidth()
            screen_height = self.root.winfo_screenheight()
            image = image.resize((screen_width, screen_height), Image.LANCZOS)
            photo = ImageTk.PhotoImage(image)
            self.label.config(image=photo)
            self.label.image = photo

            if self.slideshow_active:
                self.current_image_index = (self.current_image_index + 1) % len(self.images)
                self.root.after(int(self.interval * 1000), self.display_image)

    def run(self):
        self.display_image()
        self.root.mainloop()

    def quit_app(self, event):
        self.root.quit()

    def previous_image(self, event):
        self.slideshow_active = False
        if self.images:
            self.current_image_index = (self.current_image_index - 1) % len(self.images)
            self.display_image()

    def next_image(self, event):
        self.slideshow_active = False
        if self.images:
            self.current_image_index = (self.current_image_index + 1) % len(self.images)
            self.display_image()

    def delete_image(self, event):
        if self.images:
            image_to_delete = self.images[self.current_image_index]
            try:
                os.remove(image_to_delete)
                self.images.pop(self.current_image_index)
                if self.images:
                    self.current_image_index = self.current_image_index % len(self.images)
                    self.display_image()
                else:
                    self.label.config(image=None)
                    self.label.image = None
            except OSError as e:
                print(f"Error deleting file: {e}")

    def __del__(self):
        self.observer.stop()
        self.observer.join()

if __name__ == "__main__":
    folder_to_watch = "images"  # Replace with the path to the folder you want to watch
    interval = 5  # Slideshow interval in seconds
    viewer = FullScreenImageViewer(folder_to_watch, interval)
    viewer.run()