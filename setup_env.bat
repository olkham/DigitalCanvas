@echo off
REM Create virtual environment and install project requirements

echo Creating virtual environment...
python -m venv venv

REM Create .gitignore in venv to exclude it from version control
echo * > venv\.gitignore

echo Activating virtual environment...
call venv\Scripts\activate.bat

call python.exe -m pip install --upgrade pip

echo Installing requirements...
pip install -r requirements.txt

echo.
echo Setup complete! Virtual environment created and requirements installed.
echo To activate the environment in the future, run: venv\Scripts\activate.bat
pause
