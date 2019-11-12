# custom-install
Experimental script to automate the process of a manual title install for Nintendo 3DS. Originally created late June 2019.

## Summary
1. Dump boot9.bin and movable.sed from a 3DS system.
2. Install the packages:
  * Windows: `py -3 -m pip install --user -r requirements.txt`
  * macOS/Linux: `python3 -m pip install --user -r requirements.txt`
3. Download the repo ([zip link](https://github.com/ihaveamac/custom-install/archive/master.zip) or `git clone`)
4. Run `custominstall.py` with boot9.bin, movable.sed, path to the SD root, and CIA files to install (see Usage section).
5. Download and use [custom-install-finalize](https://github.com/ihaveamac/custom-install/releases) on the 3DS system to finish the install.

## Setup
Linux users must build [wwylele/save3ds](https://github.com/wwylele/save3ds) and place `save3ds_fuse` in `bin/linux`. Just install [rust using rustup](https://www.rust-lang.org/tools/install), then compile with: `cargo build`. Your compiled binary is located in `target/debug/save3ds_fuse`, copy it to `bin/linux`.

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

## Building finalize
Finalize is **required** for newer games that use seeds. Without finalize, the game may not show up on your 3ds, while it being on your sd card.

In order to build finalize so you can put it in your `SD:/3ds/` directory (or whatever directory you prefer for homebrew software), you will need devkitARM, or preferrably, using devkitPro's pacman installer:

If you tell everyone you use Arch (btw), your current pacman package manager will work, you just need the dependencies, skip the step below and [see here.](https://devkitpro.org/wiki/devkitPro_pacman#Customising_Existing_Pacman_Install)

[Installation instructions for devkitPro Pacman](https://devkitpro.org/wiki/Getting_Started)
  * macOS/Linux: `sudo pacman -S 3ds-dev`

*You may need to add `dpk-` to the devkitPro pacman build, tab completion might help*

Now head to the directory `finalize/` where you see the Makefile, and run:

* macOS/Linux: `make`

## Usage
Use `-h` to view arguments.

Examples:
```
py -3 custominstall.py -b boot9.bin -m movable.sed --sd E:\ file.cia file2.cia
python3 custominstall.py -b boot9.bin -m movable.sed --sd /Volumes/GM9SD file.cia file2.cia
python3 custominstall.py -b boot9.bin -m movable.sed --sd /media/GM9SD file.cia file2.cia
```

## License/Credits
`pyctr/` is from [ninfs `795373d`](https://github.com/ihaveamac/ninfs/tree/795373db07be0cacd60215d8eccf16fe03535984/ninfs/pyctr).

[save3ds by wwylele](https://github.com/wwylele/save3ds) is used to interact with the Title Database (details in `bin/README`).

Thanks to @BpyH64 for [researching how to generate the cmacs](https://github.com/d0k3/GodMode9/issues/340#issuecomment-487916606).
