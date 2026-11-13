#!/bin/bash
# Set variables
SERVICE_NAME="digital_canvas"
VENV_PATH="/home/pi/canvas/bin/activate"
SCRIPT_PATH="/home/pi/Projects/DigitalCanvas/run.py"
SERVICE_FILE="/etc/systemd/system/$SERVICE_NAME.service"

# Create the service file
sudo tee $SERVICE_FILE > /dev/null << EOL
[Unit]
Description=Digital Canvas Python App
After=network.target
After=graphical.target
Wants=graphical.target

[Service]
Environment="DISPLAY=:0"
Environment="XAUTHORITY=/home/pi/.Xauthority"
ExecStartPre=/bin/bash -c 'until [ -S /tmp/.X11-unix/X0 ]; do sleep 1; done'
ExecStart=/bin/bash -c 'export DISPLAY=:0; source $VENV_PATH && python $SCRIPT_PATH'
Restart=always
RestartSec=5
User=pi
Group=pi
WorkingDirectory=/home/pi/Projects/DigitalCanvas

[Install]
WantedBy=graphical.target
EOL

# Set correct permissions for the service file
sudo chmod 644 $SERVICE_FILE

# Reload systemd to recognize the new service
sudo systemctl daemon-reload

# Enable the service to start on boot
sudo systemctl enable $SERVICE_NAME.service

# Start the service
sudo systemctl start $SERVICE_NAME.service

# Check the status of the service
sudo systemctl status $SERVICE_NAME.service

echo "Setup complete. Your Python app should now start automatically on boot."
echo "You can check the status of your service with: sudo systemctl status $SERVICE_NAME.service"
echo "Service logs can be viewed with: sudo journalctl -u $SERVICE_NAME.service -f"