import sys
from cx_Freeze import setup, Executable

if sys.platform == 'win32':
    executables = [
        Executable('ci-gui.py', target_name='ci-gui-console'),
        Executable('ci-gui.py', target_name='ci-gui', base='Win32GUI'),
    ]
else:
    executables = [
        Executable('ci-gui.py', target_name='ci-gui'),
    ]

setup(
    name = "ci-gui",
    version = "2.1b4",
    description = "Installs a title directly to an SD card for the Nintendo 3DS",
    executables = executables
)
