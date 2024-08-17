import os
import threading
from queue import Queue
import time
from flask import Flask, json, jsonify, render_template, request, send_from_directory, redirect, url_for
from utils import accel_to_orientation, create_thumbnail, create_thumbnails_for_existing_images, get_thumbnail, is_landscape, is_portrait, luminance_to_brightness, read_image_from_url, replace_webp_extension, save_remote_image, check_and_create, strtobool
from config_manager import ConfigManager
from slideshow_manager import SlideshowManager
import paho.mqtt.client as mqtt

import cv2
import numpy as np
import base64

from monitor_controller import MonitorController
from sensors2 import SensorReader

# import logging
# log = logging.getLogger('werkzeug')
# log.setLevel(logging.ERROR)

# todo
#1 add option for random image selection or sequential
#5 improve performance of the portraint/landscape icon on the gallery view
#7 build in the clock map
#8 add another tk element to the gallery view to show the current time



class API:
    """
    List of the endpoints for the API
    """
    home_url = f'/'
    display_now = f'/display_now'
    upload = f'/uploads/<filename>'
    thumbnails = f'/thumbnails/<filename>'
    update_device_name = f'/update_device_name'
    
    delete = f'/delete'
    select = f'/select'
    current_image_name = f'/current_image_name'
    current_image = f'/current_image'   #we can also use current_image_name and the /uploads/<filename> endpoint to get the image
    
    configure_mqtt = f'/configure/mqtt'
    configure_app = f'/configure/app'
    configure_display = f'/configure/display'
    configure_slideshow = f'/configure/slideshow'
    
    slideshow_next = f'/slideshow/next'
    slideshow_previous = f'/slideshow/previous'
    slideshow_delete = f'/slideshow/delete'
    slideshow_quit = f'/slideshow/quit'
    
    configure_plex = f'/configure/plex'
    plex_hook = f'/plex_hook'
    
    shutdown = f'/shutdown'


class CombinedApp:
    def __init__(self, config_manager: dict):
        self.config_manager = config_manager
        self.mqtt_client = None
        
        self.app = Flask(__name__)
        self.app.config['UPLOAD_FOLDER'] = 'images'
        self.app.config['THUMBNAIL_FOLDER'] = 'thumbnails'

        check_and_create(self.app.config['UPLOAD_FOLDER'])
        check_and_create(self.app.config['THUMBNAIL_FOLDER'])
        create_thumbnails_for_existing_images(self.app.config['UPLOAD_FOLDER'], self.app.config['THUMBNAIL_FOLDER'])

        self.slideshow_manager = SlideshowManager(os.path.join(os.path.dirname(os.path.abspath(__file__)), "images"),
                                                  config_manager=self.config_manager)
        
        self.image_selection_queue = Queue()
        self.slideshow_manager.set_image_selection_queue(self.image_selection_queue)
        self.slideshow_manager.image_change_callback = self.publish_current_image

        self.setup_flask_routes()
        self.setup_mqtt_client()
        
        self.monitor_controller = MonitorController()
        self.sensor_reader = SensorReader()

    def setup_mqtt_client(self):
        try:
            if self.mqtt_client is not None:
                self.mqtt_client.loop_stop()
                self.mqtt_client.disconnect()
                self.mqtt_client = None
            
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

        base_topic = msg.topic.replace(self.config_manager.config['mqtt_topic'], "")
        payload_str = msg.payload.decode('utf-8')

        if 'select' in base_topic:
            self.image_selection_queue.put(payload_str)

    def publish_mqtt_message(self, topic, payload):
        if not self.mqtt_connected:
            print("MQTT broker is not connected")
            return
        self.mqtt_client.publish(topic, payload)

    def publish_current_image(self, *args):
        current_image = self.slideshow_manager.get_current_image_name()
        if current_image:
            self.publish_mqtt_message(f"{self.config_manager.config['mqtt_topic']}/current_image", current_image)

    def setup_flask_routes(self):

        @self.app.route(API.home_url, methods=['GET', 'POST'])
        def index():
            if request.method == 'POST':
                if 'file' in request.files and request.files['file'].filename != '':
                    files = request.files.getlist('file')
                    for file in files:
                        filename = replace_webp_extension(file.filename)
                        file_path = os.path.join(self.app.config['UPLOAD_FOLDER'], filename)
                        file.save(file_path)
                        thumbnail_path = os.path.join(self.app.config['THUMBNAIL_FOLDER'], filename)
                        create_thumbnail(file_path, thumbnail_path)
                elif 'image_url' in request.form and request.form['image_url'] != '':
                    image_url = request.form['image_url']
                    filename = save_remote_image(image_url, self.app.config['UPLOAD_FOLDER'])
                    filename = replace_webp_extension(filename)
                    if filename:
                        file_path = os.path.join(self.app.config['UPLOAD_FOLDER'], filename)
                        thumbnail_path = os.path.join(self.app.config['THUMBNAIL_FOLDER'], filename)
                        create_thumbnail(file_path, thumbnail_path)
                return redirect(url_for('index'))

            # Get the list of files in the upload folder
            files = os.listdir(self.app.config['UPLOAD_FOLDER'])
            
            # Filter the files based on the media_orientation_filter setting
            if self.config_manager.config['media_orientation_filter'] == 'portrait':
                files = [f for f in files if is_portrait(os.path.join(self.app.config['UPLOAD_FOLDER'], f))]
            elif self.config_manager.config['media_orientation_filter'] == 'landscape':
                files = [f for f in files if is_landscape(os.path.join(self.app.config['UPLOAD_FOLDER'], f))]
                
            # render the page
            params = {
                'files': files,
                'device_name': self.config_manager.config['device_name'],
                'mqtt_broker': self.config_manager.config['mqtt_broker'],
                'mqtt_port': self.config_manager.config['mqtt_port'],
                'mqtt_topic': self.config_manager.config['mqtt_topic'],
                'mqtt_connected': self.mqtt_connected,
                'transition_duration': self.config_manager.config['transition_duration'],
                'frame_interval': self.config_manager.config['frame_interval'],
                'media_orientation_filter': self.config_manager.config['media_orientation_filter'],
                'display_mode': self.config_manager.config['display_mode'],
                'selected_theme': self.config_manager.config['theme'],
                'rotation': self.config_manager.config['rotation'],
                'scale_mode': self.config_manager.config['scale_mode'],
                'power_state': self.monitor_controller.get_power_mode(),
                'plex_port': self.config_manager.config['plex_port'],
                'allow_plex': self.config_manager.config['allow_plex'],
                'auto_brightness': self.config_manager.config['auto_brightness'],
                'auto_rotation': self.config_manager.config['auto_rotation'],
                'current_brightness': self.monitor_controller.get_luminance(),
                'slideshow_running': self.slideshow_manager.is_running(),
            }
            
            return render_template('index8.html', **params)

        @self.app.route(API.display_now, methods=['POST'])
        def display_now():
            '''
            This route is used to display an image immediately
            '''
            base64_image = None
            if 'file' in request.files and request.files['file'].filename != '':
                file = request.files['file']
                image = cv2.imdecode(np.frombuffer(file.read(), np.uint8), cv2.IMREAD_COLOR)
                base64_image = base64.b64encode(cv2.imencode('.jpg', image)[1]).decode()
            # if 'file' in request.files and request.files['file'].filename != '':
            #     file_data = request.files['file'].read()
            #     image = Image.open(io.BytesIO(file_data))
            #     buffered = io.BytesIO()
            #     image.save(buffered, format="JPEG")
            #     base64_image = base64.b64encode(buffered.getvalue()).decode('utf-8')
            elif 'image' in request.form:
                base64_image = request.form['image']
                
            #receive an image in base64 format
            if base64_image is not None:
                self.slideshow_manager.select_image_from_base64(base64_image)
                return '', 204
            else:
                return "No image data provided", 400

        @self.app.route(API.upload, methods=['GET'])
        def uploaded_file(filename):
            return send_from_directory(self.app.config['UPLOAD_FOLDER'], filename)

        @self.app.route(API.thumbnails, methods=['GET'])
        def uploaded_thumbnail(filename):
            return send_from_directory(self.app.config['THUMBNAIL_FOLDER'], filename)
        
        @self.app.route(API.update_device_name, methods=['POST'])
        def update_device_name():
            new_name = request.form['deviceName']
            # Update the device name in your data store
            self.config_manager.update_parameter('device_name', new_name)
            return jsonify(success=True)

        @self.app.route(API.delete, methods=['POST'])
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

        @self.app.route(API.select, methods=['POST'])
        def select_file():
            # Extract filename from POST data
            filename = request.form.get('filename')
            if not filename:
                return "Filename is required", 400  # Return a 400 Bad Request if filename is not provided

            file_path = os.path.join(self.app.config['UPLOAD_FOLDER'], filename)
            if os.path.exists(file_path):
                print(f"Selecting image {filename} at {time.time()}")
                self.image_selection_queue.put(filename)
            return '', 204
        
        @self.app.route(API.current_image_name, methods=['GET'])
        def current_image_name():
            current_image_name = self.slideshow_manager.get_current_image_name()
            return current_image_name
        
        @self.app.route(API.configure_mqtt, methods=['POST'])
        def configure_mqtt():
            mqtt_broker = request.form.get('mqtt_broker')
            mqtt_port = int(request.form.get('mqtt_port') or -1)
            mqtt_topic = request.form.get('mqtt_topic')
            self.config_manager.update_parameter('mqtt_broker', mqtt_broker)
            self.config_manager.update_parameter('mqtt_port', mqtt_port)
            self.config_manager.update_parameter('mqtt_topic', mqtt_topic)
            self.setup_mqtt_client()
            return redirect(url_for('index'))

        @self.app.route(API.configure_app, methods=['POST'])
        def configure_app():
            theme = request.form.get('theme')
            self.config_manager.update_parameter('theme', theme)
            return jsonify(success=True)

        @self.app.route(API.configure_display, methods=['GET', 'POST'])
        def configure_display():
            if request.method == 'POST':
                # Handle display configuration
                display_mode = request.form.get('display_mode')
                media_orientation_filter = request.form.get('media_orientation_filter')
                scale_mode = request.form.get('scale_mode')
                rotation = request.form.get('rotation')
                brightness = request.form.get('brightness')
                
                if brightness is not None:
                    brightness = int(brightness)
                    if brightness >= 0 and brightness <= 100:
                        self.slideshow_manager.auto_brightness = False
                        self.config_manager.update_parameter('auto_brightness', False)
                        brightness = int(brightness)
                        self.monitor_controller.set_luminance(brightness)
                    elif brightness == -1:
                        self.slideshow_manager.auto_brightness = True
                        self.config_manager.update_parameter('auto_brightness', True)

                
                if rotation is not None:
                    rotation = int(rotation)
                    if rotation < 0:
                        self.config_manager.update_parameter('auto_rotation', True)
                    else:
                        self.config_manager.update_parameter('auto_rotation', False)
                
                self.config_manager.update_parameter('media_orientation_filter', media_orientation_filter)
                self.config_manager.update_parameter('display_mode', display_mode)
                self.config_manager.update_parameter('rotation', rotation)
                self.config_manager.update_parameter('scale_mode', scale_mode)
                self.slideshow_manager.update_parameters(media_orientation_filter=media_orientation_filter, 
                                                        display_mode=display_mode, 
                                                        rotation=rotation,
                                                        scale_mode=scale_mode)

                # Handle screen control
                display_power_action = request.form.get('power')
                if display_power_action is not None:
                    if display_power_action == 'on':
                        self.monitor_controller.set_power_mode('on')
                        return jsonify(success=True)
                    elif display_power_action == 'off':
                        self.monitor_controller.set_power_mode('off')
                        return jsonify(success=True)
                
                # if the oreintation is changed, we need to refresh the page to update the gallery view
                if media_orientation_filter is not None:
                    return redirect(url_for('index'))

                return "", 204
            
            elif request.method == 'GET':
                state = self.monitor_controller.get_power_state()
                return state, 200

        @self.app.route(API.configure_slideshow, methods=['POST'])
        def configure_slideshow():
            transition_duration = request.form.get('transition_duration')
            if transition_duration is not None:
                transition_duration = int(transition_duration)
                
            frame_interval = request.form.get('frame_interval')
            if frame_interval is not None:
                frame_interval = int(frame_interval)
            
            self.config_manager.update_parameter('transition_duration', transition_duration)
            self.config_manager.update_parameter('frame_interval', frame_interval)
            self.slideshow_manager.update_parameters(transition_duration=transition_duration, frame_interval=frame_interval)
            slideshow_active = strtobool(request.form.get('slideshow_active'))
            if slideshow_active == True:
                self.slideshow_manager.resume_slideshow()
            elif slideshow_active == False:
                self.slideshow_manager.pause_slideshow()
            return redirect(url_for('index'))

        @self.app.route(API.slideshow_next, methods=['POST'])
        def slideshow_next():
            self.slideshow_manager.next_image()
            self.publish_current_image()
            return '', 204

        @self.app.route(API.slideshow_previous, methods=['POST'])
        def slideshow_previous():
            self.slideshow_manager.previous_image()
            self.publish_current_image()
            return '', 204

        @self.app.route(API.slideshow_delete, methods=['POST'])
        def slideshow_delete():
            self.slideshow_manager.delete_image()
            return redirect(url_for('index'))

        @self.app.route(API.slideshow_quit, methods=['POST'])
        def slideshow_quit():
            self.slideshow_manager.quit_slideshow()
            return redirect(url_for('index'))

        @self.app.route(API.configure_plex, methods=['POST'])
        def configure_plex():
            plex_port = int(request.form.get('plex_port') or -1)
            allow_plex = strtobool(request.form.get('allow_plex'))
            self.config_manager.update_parameter('plex_port', plex_port)
            self.config_manager.update_parameter('allow_plex', allow_plex)
            return redirect(url_for('index'))

        @self.app.route(API.plex_hook, methods=['POST'])
        def plex_hook():
            if self.config_manager['allow_plex']:
                payload = request.form['payload']
                payload = json.loads(payload)
                if payload['event'] == 'media.play' or payload['event'] == 'media.resume':
                    thumb_url = get_thumbnail(payload)
                    if thumb_url is not None:
                        image_url = f"http://{request.access_route[0]}:{self.config_manager.config['plex_port']}{thumb_url}.jpg"
                        try:
                            image = read_image_from_url(image_url)
                            self.slideshow_manager.pause_slideshow()
                            self.slideshow_manager.set_image(image, 1)
                        except:
                            print(f"Failed to fetch image from Plex server on port {self.config_manager.config['plex_port']}")
                            print("Disabling Plex server integration")
                            self.config_manager.update_parameter('allow_plex', False)
                            return '', 404

                elif payload['event'] == 'media.stop' or payload['event'] == 'media.pause':
                    self.slideshow_manager.resume_slideshow()
                return '', 204
            return '', 204

    def monitor_sensor(self):
        previous_media_orientation_filter = None
        previous_brightness = None

        while True:
            if self.slideshow_manager.auto_rotate:
                accel = self.sensor_reader.read_bmi160_accel()
                media_orientation_filter = accel_to_orientation(accel)
                if media_orientation_filter != previous_media_orientation_filter:
                    self.slideshow_manager.update_parameters(media_orientation_filter=media_orientation_filter)
                    previous_media_orientation_filter = media_orientation_filter

            if self.slideshow_manager.auto_brightness:
                luminance = self.sensor_reader.read_veml7700_light()
                brightness = luminance_to_brightness(luminance, max_value=2000)
                if brightness != previous_brightness:
                    self.monitor_controller.set_luminance(brightness)
                    previous_brightness = brightness
            
            time.sleep(1)

    def run_flask(self):
        self.app.run(host='0.0.0.0', port=self.config_manager.config['web_interface_port'], debug=False, use_reloader=False)

    def run_slideshow(self):
        self.slideshow_manager.start_slideshow()        
        
    def run(self):
        flask_thread = threading.Thread(target=self.run_flask)
        slideshow_thread = threading.Thread(target=self.run_slideshow)
        sensor_thread = threading.Thread(target=self.monitor_sensor)

        flask_thread.start()
        slideshow_thread.start()
        sensor_thread.start()

        flask_thread.join()
        slideshow_thread.join()
        sensor_thread.join()
        
    def shutdown(self):
        #todo: add a confirmation dialog
        self.monitor_controller.set_power_mode('off')
        self.mqtt_client.loop_stop()
        self.mqtt_client.disconnect()
        self.slideshow_manager.quit_slideshow()
        self.sensor_reader.stop()
        os.system("sudo shutdown -h now")
        
    def restart(self):
        #todo: add a confirmation dialog
        self.monitor_controller.set_power_mode('off')
        self.mqtt_client.loop_stop()
        self.mqtt_client.disconnect()
        self.slideshow_manager.quit_slideshow()
        self.sensor_reader.stop()
        os.system("sudo reboot")
        

if __name__ == '__main__':
    config_manager = ConfigManager('config.json')   
    app = CombinedApp(config_manager)
    app.run()
