import smbus2
import time
import board
import busio
import adafruit_veml7700
from bmi160 import BMI160_I2C

class SensorReader:
    def __init__(self, i2c_bus=1):
        self.bus = smbus2.SMBus(i2c_bus)
        
        # BMI150 addresses and registers
        self.BMI150_ADDR = 0x69
        self.BMI150_REG_ACCEL_X = 0x12
        self.BMI150_REG_ACCEL_Y = 0x14
        self.BMI150_REG_ACCEL_Z = 0x16
        
        # Initialize I2C for VEML7700
        i2c = busio.I2C(board.SCL, board.SDA)
        self.veml7700 = adafruit_veml7700.VEML7700(i2c)
        
        # Initialize sensors
        self.init_bmi150()

    def init_bmi150(self):
        # Initialize BMI150 (if needed)
        pass

    def read_bmi150_accel(self):
        x = self.read_word_2c(self.BMI150_ADDR, self.BMI150_REG_ACCEL_X)
        y = self.read_word_2c(self.BMI150_ADDR, self.BMI150_REG_ACCEL_Y)
        z = self.read_word_2c(self.BMI150_ADDR, self.BMI150_REG_ACCEL_Z)
        return {'x': x, 'y': y, 'z': z}

    def read_veml7700_light(self):
        return self.veml7700.lux

    def read_word(self, addr, reg):
        high = self.bus.read_byte_data(addr, reg)
        low = self.bus.read_byte_data(addr, reg + 1)
        val = (high << 8) + low
        return val

    def read_word_2c(self, addr, reg):
        val = self.read_word(addr, reg)
        if val >= 0x8000:
            return -((65535 - val) + 1)
        else:
            return val

    def close(self):
        self.bus.close()

# Example usage
if __name__ == "__main__":
    sensor_reader = SensorReader()
    try:
        while True:
            accel = sensor_reader.read_bmi150_accel()
            light = sensor_reader.read_veml7700_light()
            print(f"Accelerometer: {accel}, Light: {light}")
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        sensor_reader.close()