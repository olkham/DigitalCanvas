import time
import platform
import importlib

def import_module(module_name):
    try:
        return importlib.import_module(module_name)
    except (ImportError, NotImplementedError) as e:
        print(f"Error importing {module_name}: {e}")
        return None

# Check if running on Windows
is_windows = platform.system() == "Windows"

# Import sensor libraries conditionally
if not is_windows:
    board = import_module('board')
    busio = import_module('busio')
    try:
        adafruit_veml7700 = import_module('adafruit_veml7700')
    except Exception as e:
        print(f"Failed to import adafruit_veml7700: {e}")
        adafruit_veml7700 = None
else:
    board = None
    busio = None
    adafruit_veml7700 = None
    print("Running on Windows. Sensor libraries not available. Will use simulation mode.")

try:
    from BMI160_i2c import Driver
except (NotImplementedError, ModuleNotFoundError) as e:
    if isinstance(e, ModuleNotFoundError) and e.name == 'fcntl':
        print("BMI160_i2c library is not compatible with Windows.")
    Driver = None

class SensorReader:
    def __init__(self):
        self.veml7700 = None
        self.bmi160 = None
        self.simulation_mode_veml7700 = False
        self.simulation_mode_bmi160 = False
        self.simulated_accel = {'ax': 0, 'ay': 0, 'az': 0}
        self.simulated_light = 0

        # Initialize VEML7700
        if not is_windows and adafruit_veml7700:
            self.veml7700 = self.init_veml7700()
        if self.veml7700 is None:
            self.simulation_mode_veml7700 = True
            print("VEML7700 initialization failed or not available. Using simulation mode.")

        # Initialize BMI160
        if not is_windows and Driver:
            try:
                self.bmi160 = Driver(0x69)  # Change address if needed
                print("BMI160 sensor initialized successfully.")
            except Exception as e:
                print(f"Failed to initialize BMI160 sensor: {e}")
                self.simulation_mode_bmi160 = True
        else:
            self.simulation_mode_bmi160 = True
            print("BMI160 initialization failed or not available. Using simulation mode.")

    def init_veml7700(self):
        try:
            if board and busio and adafruit_veml7700:
                i2c = busio.I2C(board.SCL, board.SDA)
                veml7700 = adafruit_veml7700.VEML7700(i2c)
                print("VEML7700 sensor initialized successfully.")
                return veml7700
            else:
                raise NotImplementedError("VEML7700 dependencies not available.")
        except Exception as e:
            print(f"An error occurred while initializing VEML7700: {e}")
        return None

    def read_bmi160_accel(self):
        if self.simulation_mode_bmi160:
            return self.simulated_accel
        if self.bmi160:
            try:
                data = self.bmi160.getMotion6()
                return {
                    'ax': data[3],
                    'ay': data[4],
                    'az': data[5]
                }
            except Exception as e:
                print(f"Failed to read from BMI160 sensor: {e}")
                return None
        else:
            print("BMI160 sensor is not initialized.")
            return None

    def read_veml7700_light(self):
        if self.simulation_mode_veml7700:
            return self.simulated_light
        if self.veml7700:
            try:
                return self.veml7700.lux
            except Exception as e:
                print(f"Failed to read from VEML7700 sensor: {e}")
                return None
        else:
            print("VEML7700 sensor is not initialized.")
            return None

    def set_simulated_accel(self, ax, ay, az):
        self.simulated_accel = {'ax': ax, 'ay': ay, 'az': az}

    def set_simulated_light(self, lux):
        self.simulated_light = lux

    def close(self):
        # No explicit close method needed for these libraries
        pass
    
    def stop(self):
        self.close()

# Example usage
if __name__ == "__main__":
    sensor_reader = SensorReader()
    if sensor_reader.simulation_mode_veml7700:
        sensor_reader.set_simulated_light(100.0)
    if sensor_reader.simulation_mode_bmi160:
        sensor_reader.set_simulated_accel(1.0, 2.0, 3.0)
    try:
        while True:
            accel = sensor_reader.read_bmi160_accel()
            light = sensor_reader.read_veml7700_light()
            print(f"Accelerometer: {accel}, Light: {light}")
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        sensor_reader.close()