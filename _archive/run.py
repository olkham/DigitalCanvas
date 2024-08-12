import os
import time
import threading
from flask import Flask, request, send_from_directory, render_template_string, redirect, url_for
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import tkinter as tk
from tkinter import filedialog, messagebox
from PIL import Image, ImageTk
from utils import (create_thumbnail, 
                   create_thumbnails_for_existing_images, 
                   save_remote_image, 
                   check_and_create)

from dotenv import load_dotenv
from image_viewer import ImageViewer4
# Load environment variables from .env file
load_dotenv()


class SlideshowManager:
    def __init__(self, folder, interval=5, orientation="landscape", display_mode="fullscreen"):
        self.folder = folder
        self.interval = interval
        self.orientation = orientation
        self.display_mode = display_mode
        self.viewer = None

    def start_slideshow(self):
        self.viewer = ImageViewer4(self.folder, self.interval, self.orientation, self.display_mode)
        self.viewer.run()

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


class CombinedApp:
    def __init__(self, interval=5, orientation='landscape', display_mode='windowed',
                 mqtt_broker='localhost', mqtt_port=1883, mqtt_topic='digital_canvas', device_name='device1'):
        
        self.app = Flask(__name__)

        self.app.config['UPLOAD_FOLDER'] = 'images'
        self.app.config['THUMBNAIL_FOLDER'] = 'thumbnails'

        check_and_create(self.app.config['UPLOAD_FOLDER'])
        check_and_create(self.app.config['THUMBNAIL_FOLDER'])
        create_thumbnails_for_existing_images(self.app.config['UPLOAD_FOLDER'], self.app.config['THUMBNAIL_FOLDER'])

        self.setup_flask_routes()
        self.slideshow_manager = SlideshowManager(os.path.join(os.path.dirname(os.path.abspath(__file__)), "images"),
                                                  interval=interval,
                                                  orientation=orientation,
                                                  display_mode=display_mode)

    def setup_flask_routes(self):
        @self.app.route('/', methods=['GET', 'POST'])
        def index():
            if request.method == 'POST':
                if 'file' in request.files and request.files['file'].filename != '':
                    file = request.files['file']
                    file_path = os.path.join(self.app.config['UPLOAD_FOLDER'], file.filename)
                    file.save(file_path)
                    thumbnail_path = os.path.join(self.app.config['THUMBNAIL_FOLDER'], file.filename)
                    create_thumbnail(file_path, thumbnail_path)
                elif 'image_url' in request.form and request.form['image_url'] != '':
                    image_url = request.form['image_url']
                    filename = save_remote_image(image_url, self.app.config['UPLOAD_FOLDER'])
                    if filename:
                        file_path = os.path.join(self.app.config['UPLOAD_FOLDER'], filename)
                        thumbnail_path = os.path.join(self.app.config['THUMBNAIL_FOLDER'], filename)
                        create_thumbnail(file_path, thumbnail_path)
                return redirect(url_for('index'))

            files = os.listdir(self.app.config['UPLOAD_FOLDER'])
            return render_template_string('''
            <!DOCTYPE html>
            <html lang="en">
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>Image Gallery & Slideshow</title>
                <style>
                    body {
                        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                        background-color: #1e1e1e;
                        color: #e0e0e0;
                        line-height: 1.6;
                        padding: 20px;
                        margin: 0;
                    }
                    .container {
                        max-width: 1200px;
                        margin: 0 auto;
                    }
                    h1, h2 {
                        color: #bb86fc;
                    }
                    form {
                        margin-bottom: 20px;
                    }
                    .form-container {
                        display: flex;
                        justify-content: space-around;
                    }
                    .form-container form {
                        border: 1px solid #ccc;
                        padding: 16px;
                        border-radius: 8px;
                        box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
                        max-width: 45%;
                    }
                    input[type="file"], input[type="text"], input[type="submit"], button {
                        background-color: #2e2e2e;
                        border: 1px solid #bb86fc;
                        color: #e0e0e0;
                        padding: 10px;
                        margin: 5px 0;
                        border-radius: 5px;
                    }
                    input[type="submit"], button {
                        background-color: #bb86fc;
                        color: #1e1e1e;
                        cursor: pointer;
                        transition: background-color 0.3s;
                    }
                    input[type="submit"]:hover, button:hover {
                        background-color: #a370f7;
                    }
                    .gallery {
                        display: grid;
                        grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
                        gap: 20px;
                    }
                    .gallery-item {
                        background-color: #2e2e2e;
                        border-radius: 10px;
                        overflow: hidden;
                        transition: transform 0.3s;
                        display: flex;
                        flex-direction: column;
                        height: 100%;
                    }
                    .gallery-item:hover {
                        transform: scale(1.05);
                    }
                    .gallery-item img {
                        width: 100%;
                        height: 200px;
                        object-fit: cover;
                    }
                    .gallery-item .info {
                        padding: 10px;
                        display: flex;
                        flex-direction: column;
                        flex-grow: 1;
                    }
                    .gallery-item .filename {
                        margin-bottom: auto;
                    }
                    .gallery-item .actions {
                        display: flex;
                        gap: 5px;
                        margin-top: 10px;
                    }
                    .gallery-item .actions form {
                        margin: 0;
                        flex-grow: 1;
                    }
                    .gallery-item .actions button {
                        padding: 5px 10px;
                        font-size: 0.9em;
                        width: 100%;
                        vertical-align: bottom;
                    }
                    .controls {
                        display: flex;
                        gap: 10px;
                        margin-top: 20px;
                    }
                    .controls form {
                        margin: 0;
                    }
                </style>
            </head>
            <body>
                <div class="container">
                    <h1>Digital Canvas</h1>
                    
                    <div class="form-container">
                        <form method="POST" action="/" enctype="multipart/form-data">
                            <h2>Upload an image</h2>
                            <input type="file" name="file">
                            <input type="submit" value="Upload File">
                        </form>
                        
                        <form method="POST" action="/">
                            <h2>Or provide an image URL</h2>
                            <input type="text" name="image_url" placeholder="Enter image URL">
                            <input type="submit" value="Upload from URL">
                        </form>
                    </div>
                                          
                    <h2>Slideshow Controls</h2>
                    <div class="controls">
                        <form method="POST" action="/slideshow/previous">
                            <button type="submit">Previous</button>
                        </form>
                        <form method="POST" action="/slideshow/next">
                            <button type="submit">Next</button>
                        </form>
                        <form method="POST" action="/slideshow/delete">
                            <button type="submit">Delete Current</button>
                        </form>
                        <form method="POST" action="/slideshow/quit">
                            <button type="submit">Quit Slideshow</button>
                        </form>
                    </div>
                                          
                    <h2>Gallery</h2>
                    <div class="gallery">
                        {% for file in files %}
                        <div class="gallery-item">
                            <img src="{{ url_for('uploaded_thumbnail', filename=file) }}" alt="Thumbnail">
                            <div class="info">
                                <a href="{{ url_for('uploaded_file', filename=file) }}">{{ file }}</a>
                                <div class="actions">
                                    <form method="POST" action="{{ url_for('select_file', filename=file) }}">
                                        <button type="submit">Select</button>
                                    </form>
                                    <form method="POST" action="{{ url_for('delete_file', filename=file) }}">
                                        <button type="submit">Delete</button>
                                    </form>
                                </div>
                            </div>
                        </div>
                        {% endfor %}
                    </div>
                </div>
            </body>
            </html>
            ''', files=files)

        @self.app.route('/uploads/<filename>')
        def uploaded_file(filename):
            return send_from_directory(self.app.config['UPLOAD_FOLDER'], filename)

        @self.app.route('/thumbnails/<filename>')
        def uploaded_thumbnail(filename):
            return send_from_directory(self.app.config['THUMBNAIL_FOLDER'], filename)

        @self.app.route('/delete/<filename>', methods=['POST'])
        def delete_file(filename):
            file_path = os.path.join(self.app.config['UPLOAD_FOLDER'], filename)
            thumbnail_path = os.path.join(self.app.config['THUMBNAIL_FOLDER'], filename)
            if os.path.exists(file_path):
                os.remove(file_path)
            if os.path.exists(thumbnail_path):
                os.remove(thumbnail_path)
            return redirect(url_for('index'))

        @self.app.route('/select/<filename>', methods=['POST'])
        def select_file(filename):
            file_path = os.path.join(self.app.config['UPLOAD_FOLDER'], filename)
            if os.path.exists(file_path):
                self.slideshow_manager.select_image(filename)
            # return redirect(url_for('index'))
            return '', 204

        @self.app.route('/slideshow/next', methods=['POST'])
        def next_image():
            self.slideshow_manager.next_image()
            # return redirect(url_for('index'))
            return '', 204
        
        @self.app.route('/slideshow/previous', methods=['POST'])
        def previous_image():
            self.slideshow_manager.previous_image()
            # return redirect(url_for('index'))
            return '', 204

        @self.app.route('/slideshow/delete', methods=['POST'])
        def delete_image():
            self.slideshow_manager.delete_image()
            return redirect(url_for('index'))

        @self.app.route('/slideshow/quit', methods=['POST'])
        def quit_slideshow():
            self.slideshow_manager.quit_slideshow()
            return redirect(url_for('index'))

    def run_flask(self):
        self.app.run(host='0.0.0.0', port=7000, debug=False, use_reloader=False)

    def run_slideshow(self):
        self.slideshow_manager.start_slideshow()

    def run(self):
        flask_thread = threading.Thread(target=self.run_flask)
        slideshow_thread = threading.Thread(target=self.run_slideshow)

        flask_thread.start()
        slideshow_thread.start()

        flask_thread.join()
        slideshow_thread.join()


if __name__ == '__main__':

    # Access the variables
    interval = int(os.getenv('INTERVAL'))
    orientation = os.getenv('ORIENTATION')
    display_mode = os.getenv('DISPLAYMODE')
    


    app = CombinedApp(interval=interval,
                      orientation=orientation,
                      display_mode=display_mode)
    app.run()
