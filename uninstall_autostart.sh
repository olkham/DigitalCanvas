#!/bin/bash

# Set variables
SERVICE_NAME="digital_canvas"
SERVICE_FILE="/etc/systemd/system/$SERVICE_NAME.service"

# Stop the service if it's running
sudo systemctl stop $SERVICE_NAME.service

# Disable the service
sudo systemctl disable $SERVICE_NAME.service

# Remove the service file
sudo rm $SERVICE_FILE

# Reload systemd to recognize the changes
sudo systemctl daemon-reload

# Reset any failed status
sudo systemctl reset-failed

echo "Uninstall complete. The $SERVICE_NAME service has been removed."
echo "You may need to reboot your Raspberry Pi to ensure all changes take effect."