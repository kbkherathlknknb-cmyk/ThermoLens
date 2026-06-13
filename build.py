import PyInstaller.__main__

PyInstaller.__main__.run([
    'app.py',
    '--name=ThermoLens',
    '--noconsole',
    '--icon=icon.ico',
    '--add-data=icon.ico;.',
    '--collect-all=customtkinter',
    '--collect-all=PyLibreHardwareMonitor',
    '--collect-all=PyLibreHardwareMonitorLib',
    '--uac-admin',
    '--clean',
    '--onefile',
    '-y'
])
