import base64
import datetime
import os
import threading
import time

import cv2
import numpy as np
from flask import (
    Flask,
    json,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for
)

from config_manager import ConfigManager
from monitor_controller import MonitorController
from sensors import SensorReader
from slideshow_manager import SlideshowManager
from utils import (
    accel_to_orientation,
    accel_to_rotation,
    check_for_duplicate_files,
    create_thumbnail,
    create_thumbnails_for_existing_images,
    get_mean_value,
    get_mean_values,
    get_thumbnail,
    get_title,
    is_raspberry_pi,
    lerp,
    luminance_to_brightness,
    max_usful_size,
    read_image_from_url,
    replace_webp_extension,
    save_remote_image,
    strtobool
)

# from media_manager import MediaManager
# import logging
# log = logging.getLogger('werkzeug')
# log.setLevel(logging.ERROR)

# todo
#6 add accelerometer range calibration
#7 implment the reboot and shutdown functions



class API:
    """
    List of the endpoints for the API
    """
    home_url = f'/'
    favicon = f'/favicon.ico'
    display_now = f'/display_now'
    upload = f'/upload'
    uploads = f'/uploads/<filename>'
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
    
    power_control = f'/power_control'


class CombinedApp:
    def __init__(self, config_manager: dict):
        self.config_manager: ConfigManager = config_manager
        
        self.app = Flask(__name__)
        self.app.config['UPLOAD_FOLDER'] = 'images'
        self.app.config['THUMBNAIL_FOLDER'] = 'thumbnails'

        create_thumbnails_for_existing_images(self.app.config['UPLOAD_FOLDER'], self.app.config['THUMBNAIL_FOLDER'])
        self.setup_flask_routes()

        self.slideshow_manager = SlideshowManager(os.path.join(os.path.dirname(os.path.abspath(__file__)), self.app.config['UPLOAD_FOLDER']),
                                                  config_manager=self.config_manager)
        
        self.monitor_controller = MonitorController()
        self.sensor_reader = SensorReader()

        self.on_trigger = False

    def setup_flask_routes(self):
        
        @self.app.route(API.favicon, methods=['GET'])
        def favicon():
            return send_from_directory(os.path.join(self.app.root_path, 'static'),
                                       'favicon.ico', mimetype='image/vnd.microsoft.icon')
        
        @self.app.route(API.home_url, methods=['GET', 'POST'])
        def index():

            if self.slideshow_manager.viewer is None:
                return render_template('loading.html')

            files = self.slideshow_manager.viewer.media_manager.get_media_files(self.config_manager.config['media_orientation_filter'])

            # render the page
            params = {
                'files': files,
                'config_manager': self.config_manager,
                'mqtt_broker': self.config_manager.config['mqtt_broker'],
                'mqtt_port': self.config_manager.config['mqtt_port'],
                'mqtt_topic': self.config_manager.config['mqtt_topic'],
                'mqtt_connected': self.slideshow_manager.mqtt_connected,
                'transition_duration': self.config_manager.config['transition_duration'],
                'frame_interval': self.config_manager.config['frame_interval'],
                'media_orientation_filter': self.config_manager.config['media_orientation_filter'],
                'display_mode': self.config_manager.config['display_mode'],
                'selected_theme': self.config_manager.config['theme'],
                'rotation': self.config_manager.config['rotation'],
                'scale_mode': self.config_manager.config['scale_mode'],
                'monitor_power_state': self.monitor_controller.get_power_mode(),
                'plex_port': self.config_manager.config['plex_port'],
                'allow_plex': self.config_manager.config['allow_plex'],
                'pause_when_plex_playing': self.config_manager.config['pause_when_plex_playing'],
                'auto_brightness': self.config_manager.config['auto_brightness'],
                'auto_rotation': self.config_manager.config['auto_rotation'],
                'current_brightness': self.monitor_controller.get_luminance(),
                'slideshow_running': self.slideshow_manager.viewer.slideshow_active,
                'time_on': self.config_manager.config['time_on'],
                'time_off': self.config_manager.config['time_off'],
            }
            
            return render_template('index.html', **params)

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
            elif 'image' in request.form:
                base64_image = request.form['image']
            else:
                base64_image = request.data.decode('utf-8')
            
            #receive an image in base64 format
            if base64_image is not None:
                self.slideshow_manager.viewer.set_image_from_base64(base64_image)
                return '', 204
            else:
                return "No image data provided", 400

        @self.app.route(API.uploads, methods=['GET'])
        def uploaded_file(filename):
            return send_from_directory(self.app.config['UPLOAD_FOLDER'], filename)

        @self.app.route(API.upload, methods=['POST'])
        def upload_file():
            if request.method == 'POST':
                list_was_empty = len(self.slideshow_manager.viewer.media_manager.all_media_files) == 0
                if 'file' in request.files and request.files['file'].filename != '':
                    files = request.files.getlist('file')
                    for file in files:
                        filename = replace_webp_extension(file.filename)
                        filename = check_for_duplicate_files(self.app.config['UPLOAD_FOLDER'], filename)
                        file_path = os.path.join(self.app.config['UPLOAD_FOLDER'], filename)
                        file.save(file_path)
                        max_usful_size(file_path, max_size=max(self.slideshow_manager.viewer.screen_width, self.slideshow_manager.viewer.screen_height))
                        thumbnail_path = os.path.join(self.app.config['THUMBNAIL_FOLDER'], filename)
                        create_thumbnail(file_path, thumbnail_path)
                        self.slideshow_manager.viewer.media_manager.add_media_file(os.path.join(self.app.config['UPLOAD_FOLDER'], filename))

                elif 'image_url' in request.form and request.form['image_url'] != '':
                    image_url = request.form['image_url']
                    filename = save_remote_image(image_url, self.app.config['UPLOAD_FOLDER'])         #duplicate files are checked for in this function
                    filename = replace_webp_extension(filename)
                    if filename:
                        file_path = os.path.join(self.app.config['UPLOAD_FOLDER'], filename)
                        max_usful_size(file_path, max_size=max(self.slideshow_manager.viewer.screen_width, self.slideshow_manager.viewer.screen_height))
                        thumbnail_path = os.path.join(self.app.config['THUMBNAIL_FOLDER'], filename)
                        create_thumbnail(file_path, thumbnail_path)
                        self.slideshow_manager.viewer.media_manager.add_media_file(os.path.join(self.app.config['UPLOAD_FOLDER'], filename))

                self.slideshow_manager.viewer.media_manager.filter_media_by_orientation(self.config_manager.config['media_orientation_filter'])

                # if the list was empty, select the first image we've just uploaded
                if list_was_empty and len(self.slideshow_manager.viewer.media_manager.all_media_files) > 0:
                    self.slideshow_manager.viewer.select_image(self.slideshow_manager.viewer.media_manager.all_media_files[0].filename)

                return redirect(url_for('index'))

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
            
            #remove the image from the slideshow files list
            self.slideshow_manager.viewer.media_manager.remove_media_file(file_path)

            if len(self.slideshow_manager.viewer.media_manager.all_media_files) == 0:
                self.slideshow_manager.viewer.set_image_from_path('static/background.png')

            return redirect(url_for('index'))

        @self.app.route(API.select, methods=['POST'])
        def select_file():
            # Extract filename from POST data
            filename = request.form.get('filename')
            if not filename:
                return "Filename is required", 400  # Return a 400 Bad Request if filename is not provided

            file_path = os.path.join(self.app.config['UPLOAD_FOLDER'], filename)
            if os.path.exists(file_path):
                self.slideshow_manager.viewer.select_image(filename)
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
            self.slideshow_manager.setup_mqtt_client()
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
                time_on = request.form.get('time_on')
                time_off = request.form.get('time_off')
                
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
                self.config_manager.update_parameter('time_on', time_on)
                self.config_manager.update_parameter('time_off', time_off)
                self.slideshow_manager.viewer.update_parameters(media_orientation_filter=media_orientation_filter, 
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
                    self.slideshow_manager.viewer.media_manager.orientation_filter = media_orientation_filter
                    return redirect(url_for('index'))

                return "", 204
            
            elif request.method == 'GET':
                #return the current display configuration
                # e.g. display_mode, media_orientation_filter, scale_mode, rotation, brightness, power
                return jsonify({
                    'display_mode': self.config_manager.config['display_mode'],
                    'media_orientation_filter': self.config_manager.config['media_orientation_filter'],
                    'scale_mode': self.config_manager.config['scale_mode'],
                    'rotation': self.config_manager.config['rotation'],
                    'brightness': self.monitor_controller.get_luminance(),
                    'power': self.monitor_controller.get_power_mode(),
                }), 200
                
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
            self.slideshow_manager.viewer.update_parameters(transition_duration=transition_duration, frame_interval=frame_interval)
            slideshow_active = strtobool(request.form.get('slideshow_active'))
            if slideshow_active == True:
                self.slideshow_manager.viewer.play_slideshow()
            elif slideshow_active == False:
                self.slideshow_manager.viewer.pause_slideshow()
            return redirect(url_for('index'))

        @self.app.route(API.slideshow_next, methods=['POST'])
        def slideshow_next():
            self.slideshow_manager.viewer.show_next_image()
            # self.slideshow_manager.publish_current_image()
            return '', 204

        @self.app.route(API.slideshow_previous, methods=['POST'])
        def slideshow_previous():
            self.slideshow_manager.viewer.show_previous_image()
            # self.slideshow_manager.publish_current_image()
            return '', 204

        @self.app.route(API.slideshow_delete, methods=['POST'])
        def slideshow_delete():
            self.slideshow_manager.viewer.delete_image()
            return redirect(url_for('index'))

        @self.app.route(API.slideshow_quit, methods=['POST'])
        def slideshow_quit():
            self.slideshow_manager.viewer.quit_slideshow()
            return redirect(url_for('index'))

        @self.app.route(API.configure_plex, methods=['POST'])
        def configure_plex():
            plex_port = int(request.form.get('plex_port') or -1)
            allow_plex = strtobool(request.form.get('allow_plex'))
            pause_when_plex_playing = strtobool(request.form.get('pause_when_plex_playing'))
            
            if pause_when_plex_playing:
                self.slideshow_manager.viewer.pause_slideshow()
            else:
                self.slideshow_manager.viewer.play_slideshow()
            
            self.config_manager.update_parameter('plex_port', plex_port)
            self.config_manager.update_parameter('allow_plex', allow_plex)
            self.config_manager.update_parameter('pause_when_plex_playing', pause_when_plex_playing)
            
            return redirect(url_for('index'))

        @self.app.route(API.plex_hook, methods=['POST'])
        def plex_hook():
            if self.config_manager['allow_plex']:
            # if True:
                payload_str = request.form.get('payload')
                
                if payload_str is None:
                    payload_str = request.data.decode('utf-8')
                    payload = json.loads(json.loads(payload_str)['payload'])
                else:
                    payload = json.loads(payload_str)

                if payload['event'] == 'media.play' or payload['event'] == 'media.resume':
                    thumb_url = get_thumbnail(payload)
                    media_title = get_title(payload)
                    print(media_title)
                    if thumb_url is not None:
                        image_url = f"http://{request.access_route[0]}:{self.config_manager.config['plex_port']}{thumb_url}.jpg"
                        try:
                            print(image_url)
                            image = read_image_from_url(image_url)
                            if self.config_manager.config['pause_when_plex_playing']:
                                self.slideshow_manager.viewer.pause_slideshow()
                            self.slideshow_manager.viewer.set_image(image, media_title)
                        except:
                            print(f"Failed to fetch image from Plex server on port {self.config_manager.config['plex_port']}")
                            # print("Disabling Plex server integration")
                            # self.config_manager.update_parameter('allow_plex', False)
                            return jsonify(success=False), 500

                elif payload['event'] == 'media.stop' or payload['event'] == 'media.pause':
                    if self.slideshow_manager.viewer is not None:
                        self.slideshow_manager.viewer.play_slideshow()
                return jsonify(success=True), 200
            return jsonify(success=False), 403

        @self.app.route(API.power_control, methods=['POST'])
        def power_control():
            action = request.form.get('action')
            if action == 'shutdown':
                self.shutdown()
            elif action == 'restart':
                self.restart()
            return '', 204

    def monitor_sensor(self):
        previous_media_orientation_filter = None
        previous_brightness = None
        previous_rotation = self.config_manager['rotation']
        
        smoothing_window = 10
        smooth_accel = [None]*smoothing_window
        smooth_luminance = [None]*smoothing_window
        smooth_index = 0
        
        while self.slideshow_manager.viewer is None:
            time.sleep(1)
        
        while True:
            
            if self.config_manager.config['auto_rotation']:
                accel = self.sensor_reader.read_bmi160_accel()
                smooth_accel[smooth_index] = accel
                smoothed_accel = get_mean_values(smooth_accel)
                
                angle = accel_to_rotation(smoothed_accel)
                # print(f"Current angle: {angle}")
                if angle != previous_rotation:
                    self.slideshow_manager.viewer.update_parameters(rotation=angle)
                    previous_rotation = angle

                # media_orientation_filter = accel_to_orientation(smoothed_accel)
                # print(f"Current orientation: {media_orientation_filter} from accel: {smoothed_accel}")
                # if media_orientation_filter != previous_media_orientation_filter:
                    # self.slideshow_manager.viewer.update_parameters(media_orientation_filter=media_orientation_filter)
                    # previous_media_orientation_filter = media_orientation_filter

            if self.config_manager.config['auto_brightness']:
                luminance = self.sensor_reader.read_veml7700_light()
                smooth_luminance[smooth_index] = luminance
                smoothed_luminance = get_mean_value(smooth_luminance)
                brightness = int(lerp(smoothed_luminance, self.config_manager['light_sensor_min_reading'], self.config_manager['light_sensor_max_reading'], 0, 100))
                # brightness = luminance_to_brightness(smoothed_luminance, min_value=self.config_manager['light_sensor_min_reading'], max_value=self.config_manager['light_sensor_max_reading'])
                # print(f"Current brightness: {brightness} from luminance: {luminance}")
                if brightness != previous_brightness:
                    self.monitor_controller.set_luminance(brightness)
                    previous_brightness = brightness
            
            smooth_index = (smooth_index + 1) % smoothing_window
            
            # if self.config_manager.config['time_on'] is not None and self.config_manager.config['time_off'] is not None:
            if self.config_manager.config['time_on'] != self.config_manager.config['time_off']:
                    current_time = datetime.datetime.now().time()
                    time_on = datetime.datetime.strptime(self.config_manager.config['time_on'], "%H:%M").time()
                    time_off = datetime.datetime.strptime(self.config_manager.config['time_off'], "%H:%M").time()

                    if time_on <= current_time < time_off:
                        if not self.on_trigger:
                            self.on_trigger = True
                            self.monitor_controller.set_power_mode('on')
                            print(f"Turning on the display at {current_time}")
                    else:
                        if self.on_trigger:
                            self.on_trigger = False
                            self.monitor_controller.set_power_mode('off')
                            print(f"Turning off the display at {current_time}")
            
            time.sleep(0.1)

    def run_flask(self):
        self.app.run(host='0.0.0.0', port=self.config_manager.config['web_interface_port'], debug=False, use_reloader=False)

    def run(self):
        flask_thread = threading.Thread(target=self.run_flask)
        slideshow_thread = threading.Thread(target=self.slideshow_manager.start_slideshow)
        sensor_thread = threading.Thread(target=self.monitor_sensor)

        flask_thread.start()
        slideshow_thread.start()
        sensor_thread.start()

        flask_thread.join()
        slideshow_thread.join()
        sensor_thread.join()

    def shutdown(self):
        if is_raspberry_pi():
            os.system("sudo shutdown -h now")

    def restart(self):
        if is_raspberry_pi():
            os.system("sudo reboot")


def main():
    config_manager = ConfigManager('config.json')   
    app = CombinedApp(config_manager)
    app.run()


if __name__ == '__main__':
    main()

