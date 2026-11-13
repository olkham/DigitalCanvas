#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e

# Check if the virtual environment exists
if [ -d "canvas" ]; then
    # Prompt the user to confirm the removal of the virtual environment
    read -p "Are you sure you want to remove the virtual environment 'canvas'? (y/n): " remove_venv

    if [[ "$remove_venv" == "y" || "$remove_venv" == "Y" ]]; then
        # Remove the virtual environment
        rm -rf canvas
        echo "Virtual environment 'canvas' has been removed."
    else
        echo "Virtual environment removal aborted."
    fi
else
    echo "No virtual environment 'canvas' found."
fi

# Prompt the user to decide if they want to uninstall autostart
read -p "Do you want to disable the autostart service for this application? (y/n): " uninstall_autostart

if [[ "$uninstall_autostart" == "y" || "$uninstall_autostart" == "Y" ]]; then
    chmod +x uninstall_autostart.sh
    sudo ./uninstall_autostart.sh
    echo "Autostart setup has been uninstalled."
else
    echo "Autostart uninstallation skipped."
fi

echo "Uninstallation complete."