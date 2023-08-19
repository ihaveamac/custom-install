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
    description = "Nintendo 3DS Title Custom Installer",
    executables = executables
)
