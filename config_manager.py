import json
import os

from utils import get_short_system_uuid

class ConfigManager:
    def __init__(self, config_file_path):
        self.default_config = self.populate_defaults()
        self.config_file_path = config_file_path
        self.config = self.load_config()  # Add a publicly accessible config dict
        
    def populate_defaults(self):
        """Populate the default configuration values."""
        default_config = {
            'frame_interval': 1,                                            #seconds 
            'transition_duration': 5,                                       #seconds
            'orientation': 'landscape',                                     #portrait, landscape, both
            'display_mode': 'fullscreen',                                   #windowed, fullscreen
            'web_interface_port': 7000,                                     #web server port
            'mqtt_broker': 'localhost',                                     #mqtt broker address
            'mqtt_port': 1883,                                              #mqtt broker port
            'device_name': f'digital-canvas-{get_short_system_uuid()}',     #device name
            'mqtt_topic': f'digital-canvas-{get_short_system_uuid()}',      #mqtt topic
            'theme': 'dark-theme',                                          #light-theme, dark-theme
            'rotation': 0,                                                  #0, 90, 180, 270
            "scale_mode": "fit",                                            #fill, fit
            "plex_port": 32400                                              #plex server port, default 32400 where to fetch art from
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
                # config[key] = value

    def update_parameter(self, key, value):
        """Update a parameter in the configuration and save it."""
        if value is not None:
            self.config[key] = value
            self.save_config()

# Example usage
# config_manager = ConfigManager('config.json')
# config = config_manager.load_config()
# config['new_device_name'] = 'My New Device'
# config_manager.save_config(config)
# config_manager.add_parameter('new_parameter', 'value')