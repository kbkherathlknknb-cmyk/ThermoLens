# ThermoLens
**A lightweight, standalone Native Windows Desktop App for real-time CPU & GPU temperature monitoring.**

ThermoLens is designed from the ground up to be incredibly lightweight. By completely eliminating the web browser and local server, RAM usage has been drastically cut down from hundreds of megabytes to a minimal background footprint. It lives quietly in your system tray and displays beautiful glassmorphism-styled charts using native rendering.

![ThermoLens Icon](icon.ico)

## Features
- **Zero Web Browsers**: Renders entirely natively in Windows using `customtkinter` with premium dark-mode aesthetics.
- **System Tray Integration**: ThermoLens lives quietly in your taskbar's system tray (near the clock). It works silently in the background!
- **Native Live Canvas Charts**: Real-time temperature line charts are drawn using hyper-optimized 2D canvas lines instead of heavy Javascript libraries.
- **Silent Launch**: Runs perfectly hidden without keeping a command prompt open.
- **Low-Level Hardware Access**: Uses `PyLibreHardwareMonitor` to interface directly with motherboard sensors for maximum accuracy.

## Installation

### Option 1: Standalone Executable (Recommended)
Simply download the compiled `ThermoLens.exe` from the [Releases](#) tab, double-click it, grant it Administrator privileges (required to read hardware sensors), and you're good to go!

### Option 2: Running from Source
If you want to run or build the app from source:
1. Clone this repository.
2. Install the required Python packages:
   ```bash
   pip install -r requirements.txt
   ```
3. Run the application:
   ```bash
   pythonw app.py
   ```
   *(Alternatively, run `launch.bat`)*

## Building the Executable
To package the app into a standalone `.exe` yourself:
1. Ensure `pyinstaller` is installed.
2. Run the included build script:
   ```bash
   python build.py
   ```
3. The standalone executable will be generated in the `dist/` folder.

## Technologies Used
- `customtkinter` (GUI Framework)
- `pystray` (System Tray Management)
- `PyLibreHardwareMonitor` (Motherboard Sensor Driver)
- `psutil` (System Resource Polling)

## License
MIT License
