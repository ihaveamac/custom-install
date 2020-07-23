cxfreeze ci-gui.py --target-dir=dist-standalone Win32GUI
mkdir dist-standalone\bin
copy TaskbarLib.tlb dist-standalone
copy bin\win32\save3ds_fuse.exe dist-standalone\bin
