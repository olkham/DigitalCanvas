#write an install script to install this project
#create a python venv
#activate the venv
#install the required packages

#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e

# Update package list and install python3-tk
sudo apt-get update
sudo apt-get install -y python3-tk
sudo apt-get install python3-sysv-ipc

# Create a virtual environment
python3 -m venv canvas

# Activate the virtual environment
source canvas/bin/activate

# Install the required packages
pip install --upgrade pip
pip install -r requirements.txt

echo "Installation complete. To activate the virtual environment, run 'source venv/bin/activate'."

