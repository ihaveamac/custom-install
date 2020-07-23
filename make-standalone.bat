mkdir build
cxfreeze ci-gui.py --target-dir=build\custom-install-standalone --base-name=Win32GUI
mkdir build\custom-install-standalone\bin
copy TaskbarLib.tlb build\custom-install-standalone
copy bin\win32\save3ds_fuse.exe build\custom-install-standalone\bin
copy bin\README build\custom-install-standalone\bin
python -m zipfile -c dist\custom-install-standalone.zip build\custom-install-standalone
