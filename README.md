[![License](https://img.shields.io/badge/License-MIT-blue.svg)]() ![Releases](https://img.shields.io/github/downloads/ihaveamac/custom-install/total.svg)

# custom-install
Experimental script to automate the process of a manual title install for Nintendo 3DS. Originally created late June 2019.

## Summary
Note for Windows users: Enabling "Add Python 3.X to PATH" is **NOT** required! Python is installed with the `py` launcher by default.

1. [Dump boot9.bin and movable.sed](https://ihaveamac.github.io/dump.html) from a 3DS system.
2. Install the packages:
  * Windows: `py -3 -m pip install --user -r requirements.txt`
  * macOS/Linux: `python3 -m pip install --user -r requirements.txt`
3. Download the repo ([zip link](https://github.com/ihaveamac/custom-install/archive/master.zip) or `git clone`)
4. Run `custominstall.py` with boot9.bin, movable.sed, path to the SD root, and CIA files to install (see Usage section).
5. Download and use [custom-install-finalize](https://github.com/ihaveamac/custom-install/releases) on the 3DS system to finish the install.

## Setup
Linux users must build [wwylele/save3ds](https://github.com/wwylele/save3ds) and place `save3ds_fuse` in `bin/linux`. Install [rust using rustup](https://www.rust-lang.org/tools/install), then compile with: `cargo build`. The compiled binary is located in `target/debug/save3ds_fuse`, copy it to `bin/linux`.

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
* `-s` or `--seeddb` argument (if set)
* `SEEDDB_PATH` environment variable (if set)
* `%APPDATA%\3ds\seeddb.bin` (Windows-specific)
* `~/Library/Application Support/3ds/seeddb.bin` (macOS-specific)
* `~/.3ds/seeddb.bin`
* `~/3ds/seeddb.bin`

## custom-install-finalize
custom-install-finalize installs a ticket, plus a seed if required. This is required for the title to appear and function.

This can be built as most 3DS homebrew projects [with devkitARM](https://www.3dbrew.org/wiki/Setting_up_Development_Environment).

## Usage
Use `-h` to view arguments.

Examples:
```
py -3 custominstall.py -b boot9.bin -m movable.sed --sd E:\ file.cia file2.cia
python3 custominstall.py -b boot9.bin -m movable.sed --sd /Volumes/GM9SD file.cia file2.cia
python3 custominstall.py -b boot9.bin -m movable.sed --sd /media/GM9SD file.cia file2.cia
```

## GUI
GUI wrapper to easily manage your apps. (More will go here...)

![GUI](https://raw.githubusercontent.com/LyfeOnEdge/custom-install/master/docu/main.png)

### GUI Setup
- Ubuntu/Debian: `sudo apt install python3-tk`
- Manjaro/Arch: `sudo pacman -S tk`
- Mac: Sometimes the default tkinter libs that ship with mac don't work, you can get them on the python site - `https://www.python.org/downloads/mac-osx/`
- Windows: Install python - `Remember to install tcl/tk when doing a custom installation`

## License/Credits
[save3ds by wwylele](https://github.com/wwylele/save3ds) is used to interact with the Title Database (details in `bin/README`).

Thanks to @LyfeOnEdge from the [brewtools Discord](https://brewtools.dev) for designing the GUI. Special thanks to CrafterPika and archbox for testing.

Thanks to @nek0bit for redesigning `custominstall.py` to work as a module, and for implementing an earlier GUI.

Thanks to @BpyH64 for [researching how to generate the cmacs](https://github.com/d0k3/GodMode9/issues/340#issuecomment-487916606).
