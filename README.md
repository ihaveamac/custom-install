# custom-install
Experimental script to automate the process of a manual title install for Nintendo 3DS. Originally created late June 2019.

## Summary
1. Dump boot9.bin and movable.sed from a 3DS system.
2. Install pycryptodomex:
  * Windows: `py -3 -m pip install --user --upgrade pycryptodomex`
  * macOS/Linux: `python3 -m pip install --user --upgrade pycryptodomex`
2. Run `custom-install.py` with boot9.bin, movable.sed, path to the SD root, and CIA files to install (see Usage section).
3. Use custom-install-finalize on the 3DS system to finish the install.

## Setup
Linux uses must build [wwylele/save3ds](https://github.com/wwylele/save3ds) and place `save3ds_fuse` in `bin/linux`.

movable.sed is required and can be provided with `-m` or `--movable`.

boot9 is needed:
* `-b` or `--boot9` argument (if set)
* `BOOT9_PATH` environment variable (if set)
* `%APPDATA%\3ds\boot9.bin` (Windows-specific)
* `~/Library/Application Support/3ds/boot9.bin` (macOS-specific)
* `~/.3ds/boot9.bin`
* `~/3ds/boot9.bin`

A [SeedDB](https://github.com/ihaveamac/3DS-rom-tools/wiki/SeedDB-list) is needed for newer games (2015+) that use seeds.  
SeedDB is checked in order of:
* `--seeddb` argument (if set)
* `SEEDDB_PATH` environment variable (if set)
* `%APPDATA%\3ds\seeddb.bin` (Windows-specific)
* `~/Library/Application Support/3ds/seeddb.bin` (macOS-specific)
* `~/.3ds/seeddb.bin`
* `~/3ds/seeddb.bin`

## Usage
Use `-h` to view arguments.

Examples:
```
py -3 custom-install.py -b boot9.bin -m movable.sed --sd E:\ file.cia file2.cia
python3 custom-install.py -b boot9.bin -m movable.sed --sd /Volumes/GM9SD file.cia file2.cia
python3 custom-install.py -b boot9.bin -m movable.sed --sd /media/GM9SD file.cia file2.cia
```

## License/Credits
`pyctr/` is from [ninfs `d994c78`](https://github.com/ihaveamac/ninfs/tree/d994c78acf5ff3840df1ef5a6aabdc12ca98e806/ninfs/pyctr).

[save3ds by wwylele](https://github.com/wwylele/save3ds) is used to interact with the Title Database (details in `bin/README`).

Thanks to @BpyH64 for [researching how to generate the cmacs](https://github.com/d0k3/GodMode9/issues/340#issuecomment-487916606).
