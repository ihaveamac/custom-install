rmdir build
mkdir build
::mkdir dist
python setup-cxfreeze.py build_exe --build-exe=build\custom-install-standalone
mkdir build\custom-install-standalone\bin
copy TaskbarLib.tlb build\custom-install-standalone
copy bin\win32\save3ds_fuse.exe build\custom-install-standalone\bin
copy bin\README build\custom-install-standalone\bin
copy custom-install-finalize.3dsx build\custom-install-standalone
copy title.db.gz build\custom-install-standalone
copy extras\windows-quickstart.txt build\custom-install-standalone
copy extras\run_with_cmd.bat build\custom-install-standalone
copy LICENSE.md build\custom-install-standalone
::python -m zipfile -c dist\custom-install-standalone.zip build\custom-install-standalone
start extras\killconfirmation01.wav