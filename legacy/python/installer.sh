#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e

# Update package list and install python3-tk
sudo apt-get update
sudo apt-get install -y python3-tk
sudo apt-get install python3-sysv-ipc

# Check if the virtual environment already exists
if [ -d "canvas" ]; then
    read -p "A virtual environment already exists. Do you want to continue using the existing environment? (y/n): " use_existing_env
    if [[ "$use_existing_env" == "n" || "$use_existing_env" == "N" ]]; then
        echo "Aborting installation."
        exit 1
    fi
else
    # Create a virtual environment
    python3 -m venv canvas
fi

# Activate the virtual environment
source canvas/bin/activate

# Install the required packages
pip install --upgrade pip
pip install -r requirements.txt

echo "Installation complete. To activate the virtual environment, run 'source canvas/bin/activate'."

# Prompt the user to decide if they want to run setup_autostart.sh
read -p "Do you want to set up autostart service for this application? (y/n): " setup_autostart

if [[ "$setup_autostart" == "y" || "$setup_autostart" == "Y" ]]; then
	chmod +x setup_autostart.sh
	sudo ./setup_autostart.sh
	echo "Autostart setup complete."
else
	echo "Autostart setup skipped."
fi

