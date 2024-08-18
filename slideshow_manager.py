import json
import os
from image_viewer import ImageViewer
from config_manager import ConfigManager
import paho.mqtt.client as mqtt


class SlideshowManager:     
    def __init__(self, 
                 folder, 
                 config_manager):
        self.config_manager = config_manager
        self.folder = folder
        self.frame_interval = self.config_manager['frame_interval']
        self.transition_duration = self.config_manager['transition_duration']
        self.media_orientation_filter = self.config_manager['media_orientation_filter']
        self.display_mode = self.config_manager['display_mode']
        self.rotation = self.config_manager['rotation']
        self.scale_mode = self.config_manager['scale_mode']
        self.auto_rotate = self.config_manager['auto_rotation']
        self.auto_brightness = self.config_manager['auto_brightness']
        self.viewer = None
        self.image_selection_queue = None
        self.image_change_callback = None
        
        self.mqtt_client = None
        self.mqtt_connected = False
        self.setup_mqtt_client()
        self.image_change_callback = self.publish_current_image
        

    def update_parameters(self, 
                          frame_interval=None, 
                          transition_duration=None, 
                          media_orientation_filter=None,
                          display_mode=None,
                          rotation=None,
                          scale_mode=None):
        if frame_interval is not None and frame_interval >= 0 and frame_interval != self.frame_interval:
            self.frame_interval = frame_interval
        if transition_duration is not None and transition_duration >= 0 and transition_duration != self.transition_duration:
            self.transition_duration = transition_duration
        if media_orientation_filter is not None and ConfigManager.is_valid_value('media_orientation_filter', media_orientation_filter) and media_orientation_filter != self.media_orientation_filter:
            self.media_orientation_filter = media_orientation_filter
        if display_mode is not None and ConfigManager.is_valid_value('display_mode', display_mode) and display_mode != self.display_mode:
            self.display_mode = display_mode
        if rotation is not None and ConfigManager.is_valid_value('rotation', rotation) and rotation != self.rotation:
            self.rotation = rotation
        if scale_mode is not None and ConfigManager.is_valid_value('scale_mode', scale_mode) and scale_mode != self.scale_mode:
            self.scale_mode = scale_mode

        if self.viewer:
            self.viewer.update_parameters(frame_interval=self.frame_interval,
                                        transition_duration=self.transition_duration,
                                        media_orientation_filter=self.media_orientation_filter,
                                        display_mode=self.display_mode,
                                        rotation=self.rotation,
                                        scale_mode=self.scale_mode)

    def get_current_image_name(self):
        if self.viewer:
            return self.viewer.current_image_name
        return ''

    def set_image_selection_queue(self, queue):
        self.image_selection_queue = queue

    def check_for_image_selection(self):
        if self.image_selection_queue and not self.image_selection_queue.empty():
            filename = self.image_selection_queue.get()
            # print(f'Got image selection request: {filename} at {time.time()}')
            self.select_image(filename)
            # print(f'Selected image {filename} at {time.time()}')
        if self.viewer:
            self.viewer.root.after(100, self.check_for_image_selection)

    def start_slideshow(self):
        self.viewer = ImageViewer(self.folder, 
                                   self.frame_interval, 
                                   self.transition_duration, 
                                   self.media_orientation_filter, 
                                   self.display_mode,
                                   self.rotation,
                                   self.scale_mode)
        self.viewer.image_change_callback = self.image_change_callback
        self.publish_available_images()
        self.publish_current_config()
        
        self.viewer.root.after(100, self.check_for_image_selection)
        self.viewer.run()

    def select_image_from_base64(self, base64_image, transition_duration=0):
        if self.viewer:
            self.viewer.select_image_from_base64(base64_image, transition_duration)

    def set_image(self, image, transition_duration=0):
        if self.viewer:
            self.viewer.set_image(image, transition_duration)

    def select_image(self, name):
        if self.viewer:
            # print(f'Selecting image {name} at {time.time()}')
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
        if self.viewer:
            return self.viewer.slideshow_active
        return False
    
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

        # if 'brightness' in base_topic:
        #     brightness = int(payload_str)
        #     if brightness >= 0 and brightness <= 100:
        #         self.monitor_controller.set_luminance(brightness)
                
        # if 'power' in base_topic:
        #     if payload_str == 'on':
        #         self.monitor_controller.set_power_mode('on')
        #     elif payload_str == 'off':
        #         self.monitor_controller.set_power_mode('off')
                
        if 'display_mode' in base_topic:    
            self.update_parameters(display_mode=payload_str)
            
        if 'rotation' in base_topic:    
            self.update_parameters(rotation=int(payload_str))
            
        if 'scale_mode' in base_topic:  
            self.update_parameters(scale_mode=payload_str)
            
        if 'slideshow' in base_topic:    
            if payload_str == 'pause':
                self.pause_slideshow()
            elif payload_str == 'resume':
                self.resume_slideshow()
            elif payload_str == 'next':
                self.next_image()
            elif payload_str == 'previous':
                self.previous_image()
            elif payload_str == 'quit':
                self.quit_slideshow()
                
        if 'theme' in base_topic:
            self.config_manager.update_parameter('theme', payload_str)
            
        if 'plex' in base_topic:
            if payload_str == 'on':
                self.config_manager.update_parameter('allow_plex', True)
            elif payload_str == 'off':
                self.config_manager.update_parameter('allow_plex', False)
        
        if 'auto_brightness' in base_topic:   
            if payload_str == 'on':
                self.auto_brightness = True
                self.config_manager.update_parameter('auto_brightness', True)
            elif payload_str == 'off':
                self.auto_brightness = False
                self.config_manager.update_parameter('auto_brightness', False)
                
        if 'auto_rotation' in base_topic:   
            if payload_str == 'on':
                self.auto_rotate = True
                self.config_manager.update_parameter('auto_rotation', True)
            elif payload_str == 'off':
                self.auto_rotate = False
                self.config_manager.update_parameter('auto_rotation', False)
                
        if 'frame_interval' in base_topic:    
            self.update_parameters(frame_interval=int(payload_str))
            
        if 'transition_duration' in base_topic:    
            self.update_parameters(transition_duration=int(payload_str))
            
        if 'media_orientation_filter' in base_topic:    
            self.update_parameters(media_orientation_filter=payload_str)
            
    def publish_mqtt_message(self, topic, payload, retain=False):
        if not self.mqtt_connected:
            print("MQTT broker is not connected")
            return
        self.mqtt_client.publish(topic, payload, retain=retain)

    def publish_current_image(self, *args):
        current_image = self.get_current_image_name()
        if current_image:
            self.publish_mqtt_message(f"{self.config_manager.config['mqtt_topic']}/current_image", current_image)

    def publish_current_config(self, *args):
        self.publish_mqtt_message(f"{self.config_manager.config['mqtt_topic']}/config", json.dumps(self.config_manager.config))

    def publish_available_images(self, *args):
        files = self.viewer.images
        files = [os.path.basename(file) for file in files]
        self.publish_mqtt_message(f"{self.config_manager.config['mqtt_topic']}/available_images", json.dumps(files), retain=True)

    
    
    
    # def play_slideshow(self):
    #     if self.viewer:
    #         self.viewer.resume_slideshow()
            
    # def pause_slideshow(self):
        # if self.viewer:
            # self.viewer.slideshow_active = False