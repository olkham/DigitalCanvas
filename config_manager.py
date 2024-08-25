import json
import os
import ipaddress
from utils import get_short_system_uuid
import re


# Valid values for the configuration parameters
valid_media_orientation_filters = ['portrait', 'landscape', 'both']
valid_display_modes = ['windowed', 'fullscreen']
valid_themes = ['light-theme', 'dark-theme', 'darcula-theme', 'spring-blossom-theme', 'winter-wonderland-theme', 'autumn-leaves-theme', 'autumn-leaves-theme', 'ocean-breeze-theme', 'warm-sunset-theme']
valid_scale_modes = ['fill', 'fit']
valid_playback_mode = ['sequential', 'random']
valid_auto_brightness = [True, False]
valid_auto_rotation = [True, False]
valid_rotation = [0, 90, 180, 270]
valid_allow_plex = [True, False]
valid_pause_when_plex_playing = [True, False]


    # "image_folder": "images",
    # "thumbnail_folder": "thumbnails",
    # "frame_interval": 20,
    # "transition_duration": 3,
    # "media_orientation_filter": "both",
    # "display_mode": "windowed",
    # "web_interface_port": 7000,
    # "mqtt_broker": "192.168.1.138",
    # "mqtt_port": 1883,
    # "mqtt_topic": "1/office/canvas-big",
    # "device_name": "office-canvas",
    # "theme": "dark-theme",
    # "rotation": 0,
    # "scale_mode": "fit",
    # "plex_port": 32400,
    # "light_sensor_max_reading": 1024,
    # "light_sensor_min_reading": 0

# Valid values for the configuration parameters
valid_values = {
    'media_orientation_filter': valid_media_orientation_filters,
    'display_mode': valid_display_modes,
    'theme': valid_themes,
    'scale_mode': valid_scale_modes,
    'auto_brightness': valid_auto_brightness,
    'auto_rotation': valid_auto_rotation,
    'rotation': valid_rotation,
    'allow_plex': valid_allow_plex,
    'playback_mode': valid_playback_mode,
    'pause_when_plex_playing': valid_pause_when_plex_playing
}


class ConfigManager:
    """Class to manage the configuration of the digital canvas."""
    @staticmethod
    def is_valid_value(key, value):
        """Check if the value is valid for the given key."""
        if key in valid_values:
            return value in valid_values[key]
        if key == 'mqtt_port' or key == 'plex_port' or key == 'web_interface_port':
            return isinstance(value, int) and 0 <= value <= 65535
        if key == 'frame_interval':
            return isinstance(value, int) and value > 0
        if key == 'transition_duration':
            return isinstance(value, int) and value >= 0
        if key == 'device_name':
            return isinstance(value, str) and len(value) > 0
        if key == 'mqtt_topic':
            return isinstance(value, str) and len(value) > 0        
        if key == 'mqtt_broker':
            try:
                ipaddress.ip_address(value)
                return True
            except ValueError:
                return False
        if key == 'light_sensor_max_reading' or key == 'light_sensor_min_reading':
            return isinstance(value, int)
        if key == 'time_on' or key == 'time_off':
            return isinstance(value, str) and bool(re.match(r'^\d{2}:\d{2}$', value))

        return False
    
    def __init__(self, config_file_path):
        self.default_config = self.populate_defaults()      # Populate the default configuration values
        self.config_file_path = config_file_path            # Path to the configuration file
        self.config = self.load_config()                    # Load the configuration from the JSON file
        
    def __str__(self) -> str:
        return str(self.config)
        
    def populate_defaults(self):
        """Populate the default configuration values."""
        default_config = {
            'image_folder': 'images',                                      #folder containing images
            'thumbnail_folder': 'thumbnails',                              #folder containing thumbnails
            'frame_interval': 1,                                            #seconds 
            'transition_duration': 5,                                       #seconds
            'media_orientation_filter': 'landscape',                        #portrait, landscape, both
            'playback_mode': 'sequential',                                  #sequential, random
            'display_mode': 'fullscreen',                                   #windowed, fullscreen
            'web_interface_port': 7000,                                     #web server port
            'mqtt_broker': 'localhost',                                     #mqtt broker address
            'mqtt_port': 1883,                                              #mqtt broker port
            'device_name': f'digital-canvas-{get_short_system_uuid()}',     #device name
            'mqtt_topic': f'digital-canvas-{get_short_system_uuid()}',      #mqtt topic
            'theme': 'dark-theme',                                          #light-theme, dark-theme
            'rotation': 0,                                                  #0, 90, 180, 270
            "scale_mode": "fit",                                            #fill, fit
            "plex_port": 32400,                                             #plex server port, default 32400 where to fetch art from
            "allow_plex": True,                                             #allow plex server to fetch art
            "pause_when_plex_playing": True,                                #pause slideshow when plex is playing
            "auto_brightness": True,                                        #auto brightness adjustment
            "auto_rotation": True,                                          #auto rotation
            "light_sensor_max_reading": 1000,                               #maximum reading from light sensor
            "light_sensor_min_reading": 0,                                  #minimum reading from light sensor
            "time_on": "06:00",                                             #time to turn on
            "time_off": "22:00"                                             #time to turn off
        }
        return default_config

    def load_config(self):
        """Load the configuration from the JSON file."""
        if os.path.exists(self.config_file_path):
            with open(self.config_file_path, 'r') as file:
                self.config = json.load(file)
                self.add_missing_defaults()
                return self.config
        else:
            self.set_defaults()
            return self.load_config()

    def save_config(self):
        """Save the configuration to JSON file."""
        with open(self.config_file_path, 'w') as file:
            json.dump(self.config, file, indent=4)

    def add_parameter(self, key, value):
        """Dynamically add a parameter to the configuration."""
        self.config[key] = value
        self.save_config()

    def set_defaults(self):
        """Set default configuration values if the config file does not exist."""
        self.config = self.default_config
        self.save_config()

    def add_missing_defaults(self):
        """Add missing default values to the configuration."""
        # default_config = config
        for key, value in self.default_config.items():
            if key not in self.config:
                self.update_parameter(key, value)

    def update_parameter(self, key, value):
        """Update a parameter in the configuration and save it."""
        if value is not None and self.is_valid_value(key, value):
            self.config[key] = value
            self.save_config()

    def __getitem__(self, key):
        """Get the value of a configuration parameter."""
        return self.config.get(key, None)

# Example usage
# config_manager = ConfigManager('config.json')
# config = config_manager.load_config()
# config['new_device_name'] = 'My New Device'
# config_manager.save_config(config)
# config_manager.add_parameter('new_parameter', 'value')