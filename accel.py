from time import sleep
from BMI160_i2c import Driver

print('Trying to initialize the sensor...')
sensor = Driver(0x69) # change address if needed
print('Initialization done')

while True:
    data = sensor.getMotion6()
    # fetch all gyro and acclerometer values
    if abs(data[3]) > abs(data[4]):
            print('h')
    else:
            print('v')
    sleep(0.1)