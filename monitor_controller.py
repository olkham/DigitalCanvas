from monitorcontrol import get_monitors, PowerMode

class MonitorController:

    def __init__(self):
        self.monitors = get_monitors()
        self.monitors_connected = False
        for monitor in self.monitors:
            with monitor:
                try:
                    print(monitor.get_power_mode())
                    self.monitors_connected = True
                except:
                    pass

    def set_power_mode(self, mode):
        
        if mode == 'off':
            mode = 'off_soft'
        
        if self.monitors_connected == False:
            return False
        for monitor in self.monitors:
            with monitor:
                monitor.set_power_mode(mode)
                return True

    def set_contrast(self, value):
        if self.monitors_connected == False:
            return False
        for monitor in self.monitors:
            with monitor:
                monitor.set_contrast(value)
                return True

    def set_luminance(self, value):
        if self.monitors_connected == False:
            return False
        for monitor in self.monitors:
            with monitor:
                monitor.set_luminance(value)
                return True

    def get_power_modes(self):
        if self.monitors_connected == False:
            return 'on' #assume the monitor is on if we can't get the power mode
        
        power_modes = []
        for monitor in self.monitors:
            with monitor:
                power_modes.append(monitor.get_power_mode())
        return power_modes


    def get_power_mode(self):
        if self.monitors_connected == False:
            return 'on' #assume the monitor is on if we can't get the power mode
        
        for monitor in self.monitors:
            with monitor:
                mode = monitor.get_power_mode()
                if mode.name != 'on':
                    return 'off'
                return mode.name

    def get_luminance(self):
        if self.monitors_connected == False:
            return -1
        for monitor in self.monitors:
            with monitor:
                return monitor.get_luminance()

    def get_contrast(self):
        if self.monitors_connected == False:
            return
        for monitor in self.monitors:
            with monitor:
                return monitor.get_contrast()

if __name__ == '__main__':
    monitor_controller = MonitorController()
    print(monitor_controller.get_power_mode())
    # monitor_controller.get_luminance()  
    # monitor_controller.get_contrast()