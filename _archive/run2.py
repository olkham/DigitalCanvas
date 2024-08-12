import os
import threading
from queue import Queue
from flask import Flask, jsonify, render_template, request, send_from_directory, render_template_string, redirect, url_for
from utils import create_thumbnail, create_thumbnails_for_existing_images, save_remote_image, check_and_create
from config_manager import ConfigManager
from slideshow_manager import SlideshowManager

import paho.mqtt.client as mqtt

from flask_socketio import SocketIO, emit



class CombinedApp:
    def __init__(self, config_manager: dict):
        self.config_manager = config_manager
        
        self.app = Flask(__name__)
        self.socketio = SocketIO(self.app)

        self.app.config['UPLOAD_FOLDER'] = 'images'
        self.app.config['THUMBNAIL_FOLDER'] = 'thumbnails'

        check_and_create(self.app.config['UPLOAD_FOLDER'])
        check_and_create(self.app.config['THUMBNAIL_FOLDER'])
        create_thumbnails_for_existing_images(self.app.config['UPLOAD_FOLDER'], self.app.config['THUMBNAIL_FOLDER'])

        self.image_selection_queue = Queue()
        self.slideshow_manager = SlideshowManager(os.path.join(os.path.dirname(os.path.abspath(__file__)), "images"),
                                                  frame_interval=self.config_manager.config['frame_interval'],
                                                  transition_duration=self.config_manager.config['transition_duration'],
                                                  orientation=self.config_manager.config['orientation'],
                                                  display_mode=self.config_manager.config['display_mode'])
        self.slideshow_manager.set_image_selection_queue(self.image_selection_queue)
        self.slideshow_manager.image_change_callback = self.send_current_image_update()
        
        self.setup_flask_routes()
        self.setup_mqtt_client()


    def setup_mqtt_client(self):
        try:
            self.mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
            self.mqtt_client.on_connect = self.on_mqtt_connect
            self.mqtt_client.on_message = self.on_mqtt_message
            self.mqtt_client.connect(self.config_manager.config['mqtt_broker'], int(self.config_manager.config['mqtt_port']), 60)
            self.mqtt_client.loop_start()
            
            # Add a flag to handle if the MQTT broker cannot be reached
            self.mqtt_connected = True
        except Exception as e:
            print("Failed to connect to MQTT broker:", str(e))
            self.mqtt_connected = False

    def on_mqtt_connect(self, client, userdata, flags, rc, properties):
        print("Connected with result code " + str(rc))
        if rc == 0:
            self.mqtt_connected = True
            self.mqtt_client.subscribe(f"{self.config_manager.config['mqtt_topic']}/#")
        else:
            self.mqtt_connected = False
            print("Failed to connect to MQTT broker")

    def on_mqtt_message(self, client, userdata, msg):
        
        if not self.mqtt_connected:
            print("MQTT broker is not connected")
            return
        
        print(msg.topic + " " + str(msg.payload))
        
        # Step 1: Extract the base topic
        base_topic = msg.topic.replace(self.config_manager.config['mqtt_topic'], "")
        
        # Step 2: Convert the MQTT message payload to a string
        payload_str = msg.payload.decode('utf-8')
        
        # Step 3: Call the corresponding Flask endpoint
        with self.app.test_client() as client:
            # Assuming the endpoint expects a POST request with the payload as data
            # Adjust this part based on your actual Flask endpoint expectations
            response = client.post(f'/{base_topic}', data={'filename': payload_str}, follow_redirects=True)


    def setup_flask_routes(self):
        
        
        @self.socketio.on('connect')
        def handle_connect():
            print('Client connected')

        @self.socketio.on('disconnect')
        def handle_disconnect():
            print('Client disconnected')

        def send_current_image_update(current_image):
            self.socketio.emit('update_current_image', {'current_image': current_image})

        
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
            return render_template('index7.html', files=files, device_name=self.config_manager.config['device_name'], 
                                    mqtt_broker=self.config_manager.config['mqtt_broker'], 
                                    mqtt_port=self.config_manager.config['mqtt_port'], 
                                    mqtt_topic=self.config_manager.config['mqtt_topic'], 
                                    mqtt_connected=self.mqtt_connected,
                                    transition_duration= self.config_manager.config['transition_duration'],
                                    frame_interval= self.config_manager.config['frame_interval'])


        @self.app.route('/uploads/<filename>', methods=['GET'])
        def uploaded_file(filename):
            return send_from_directory(self.app.config['UPLOAD_FOLDER'], filename)

        @self.app.route('/thumbnails/<filename>', methods=['GET'])
        def uploaded_thumbnail(filename):
            return send_from_directory(self.app.config['THUMBNAIL_FOLDER'], filename)
        
        @self.app.route('/update_device_name', methods=['POST'])
        def update_device_name():
            new_name = request.form['deviceName']
            # Update the device name in your data store
            self.config_manager.update_parameter('device_name', new_name)
            return jsonify(success=True)

        @self.app.route('/delete', methods=['POST'])
        def delete_file():
            filename = request.form.get('filename')
            if not filename:
                return "Filename is required", 400  # Return a 400 Bad Request if filename is not provided
            
            file_path = os.path.join(self.app.config['UPLOAD_FOLDER'], filename)
            thumbnail_path = os.path.join(self.app.config['THUMBNAIL_FOLDER'], filename)
            if os.path.exists(file_path):
                os.remove(file_path)
            if os.path.exists(thumbnail_path):
                os.remove(thumbnail_path)
            return redirect(url_for('index'))

        @self.app.route('/select', methods=['POST'])
        def select_file():
            # Extract filename from POST data
            filename = request.form.get('filename')
            if not filename:
                return "Filename is required", 400  # Return a 400 Bad Request if filename is not provided

            file_path = os.path.join(self.app.config['UPLOAD_FOLDER'], filename)
            if os.path.exists(file_path):
                self.image_selection_queue.put(filename)
            # return redirect(url_for('index'))
            return '', 204
        
        @self.app.route('/current_image', methods=['GET'])
        def current_image():
            current_image = self.slideshow_manager.get_current_image()
            return current_image
        
        
        @self.app.route('/configure_mqtt', methods=['POST'])
        def configure_mqtt():
            mqtt_broker = request.form.get('mqtt_broker')
            mqtt_port = request.form.get('mqtt_port')
            mqtt_topic = request.form.get('mqtt_topic')
            self.config_manager.update_parameter('mqtt_broker', mqtt_broker)
            self.config_manager.update_parameter('mqtt_port', mqtt_port)
            self.config_manager.update_parameter('mqtt_topic', mqtt_topic)
            self.setup_mqtt_client()
            return redirect(url_for('index'))
        
        @self.app.route('/configure_slideshow', methods=['POST'])
        def configure_slideshow():
            transition_duration = int(request.form.get('transition_duration'))
            frame_interval = int(request.form.get('frame_interval'))
            self.config_manager.update_parameter('transition_duration', transition_duration)
            self.config_manager.update_parameter('frame_interval', frame_interval)
            self.slideshow_manager.update_parameters(frame_interval, transition_duration)
            return redirect(url_for('index'))

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
        self.app.run(host='0.0.0.0', port=self.config_manager.config['web_interface_port'], debug=False, use_reloader=False)

    def run_slideshow(self):
        self.slideshow_manager.start_slideshow()
        
    def run_socketio(self):
        self.socketio.run(self.app, host='0.0.0.0', port=self.config_manager.config['web_interface_port'], debug=False, use_reloader=False)

    def run(self):
        # flask_thread = threading.Thread(target=self.run_flask)
        flask_thread = threading.Thread(target=self.run_socketio)
        slideshow_thread = threading.Thread(target=self.run_slideshow)

        flask_thread.start()
        slideshow_thread.start()

        flask_thread.join()
        slideshow_thread.join()


if __name__ == '__main__':
    config_manager = ConfigManager('config.json')   
    app = CombinedApp(config_manager)
    app.run()
