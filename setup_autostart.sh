#!/bin/bash

# Set variables
SERVICE_NAME="digital_canvas"
USER_NAME=$(whoami)
VENV_PATH="/home/$USER_NAME/canvas/bin/activate"
SCRIPT_PATH="/home/$USER_NAME/Projects/DigitalCanvas/run.py"
SERVICE_FILE="/etc/systemd/system/$SERVICE_NAME.service"

# Create the service file
sudo tee $SERVICE_FILE > /dev/null << EOL
[Unit]
Description=Digital Canvas Python App
After=network.target

[Service]
Environment="DISPLAY=:0"
ExecStart=/bin/bash -c 'source $VENV_PATH && python $SCRIPT_PATH'
User=$USER_NAME
WorkingDirectory=/home/$USER_NAME/Projects/DigitalCanvas

[Install]
WantedBy=multi-user.target
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