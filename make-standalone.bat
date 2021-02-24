mkdir build
mkdir dist
cxfreeze ci-gui.py --target-dir=build\custom-install-standalone --base-name=Win32GUI
mkdir build\custom-install-standalone\bin
copy TaskbarLib.tlb build\custom-install-standalone
copy bin\win32\save3ds_fuse.exe build\custom-install-standalone\bin
copy bin\README build\custom-install-standalone\bin
copy custom-install-finalize.3dsx build\custom-install-standalone
copy title.db.gz build\custom-install-standalone
copy extras\windows-quickstart.txt build\custom-install-standalone
copy LICENSE.md build\custom-install-standalone
python -m zipfile -c dist\custom-install-standalone.zip build\custom-install-standalone
