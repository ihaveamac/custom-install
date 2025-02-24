#!/usr/bin/env python3

# This file is a part of custom-install.py.
#
# custom-install is copyright (c) 2019-2020 Ian Burgwin
# This file is licensed under The MIT License (MIT).
# You can find the full license text in LICENSE.md in the root of this project.

import sys
from os import environ, scandir
from os.path import abspath, basename, dirname, join, isfile
from threading import Thread, Lock
from datetime import datetime

from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                           QLabel, QLineEdit, QPushButton, QFileDialog, QTreeWidget, 
                           QTreeWidgetItem, QProgressBar, QCheckBox, QMessageBox,
                           QTextEdit, QSplitter)
from PyQt6.QtCore import Qt, pyqtSignal, QObject
from PyQt6.QtGui import QPixmap, QIcon
from io import BytesIO

from pyctr.crypto import MissingSeedError, CryptoEngine, load_seeddb
from pyctr.crypto.engine import b9_paths
from pyctr.util import config_dirs
from pyctr.type.cdn import CDNError, CDNReader
from pyctr.type.cia import CIAError, CIAReader
from pyctr.type.tmd import TitleMetadataError

from custominstall import CustomInstall, CI_VERSION, load_cifinish, InvalidCIFinishError, InstallStatus

file_parent = dirname(abspath(__file__))

# automatically load boot9 if it's in the current directory
b9_paths.insert(0, join(file_parent, 'boot9.bin'))
b9_paths.insert(0, join(file_parent, 'boot9_prot.bin'))

seeddb_paths = [join(x, 'seeddb.bin') for x in config_dirs]
try:
    seeddb_paths.insert(0, environ['SEEDDB_PATH'])
except KeyError:
    pass
# automatically load seeddb if it's in the current directory
seeddb_paths.insert(0, join(file_parent, 'seeddb.bin'))

def find_first_file(paths):
    for p in paths:
        if isfile(p):
            return p

# find boot9, seeddb, and movable.sed to auto-select in the gui
default_b9_path = find_first_file(b9_paths)
default_seeddb_path = find_first_file(seeddb_paths)
default_movable_sed_path = find_first_file([join(file_parent, 'movable.sed')])

if default_seeddb_path:
    load_seeddb(default_seeddb_path)

statuses = {
    InstallStatus.Waiting: 'Waiting',
    InstallStatus.Starting: 'Starting',
    InstallStatus.Writing: 'Writing',
    InstallStatus.Finishing: 'Finishing',
    InstallStatus.Done: 'Done',
    InstallStatus.Failed: 'Failed',
}

class InstallSignals(QObject):
    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(float, int, int)
    error_signal = pyqtSignal(Exception)
    cia_start_signal = pyqtSignal(int)
    status_signal = pyqtSignal(str, InstallStatus)

class CustomInstallGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f'custom-install {CI_VERSION}')
        self.resize(800, 600)

        # Setup main widget and layout
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QVBoxLayout(self.central_widget)

        # Initialize variables
        self.readers = {}
        self.lock = Lock()
        self.b9_loaded = False
        self.signals = InstallSignals()

        # Setup UI components
        self.setup_file_pickers()
        self.setup_title_buttons()
        self.setup_title_list()
        self.setup_progress()
        self.setup_controls()

        # Setup signals
        self.signals.log_signal.connect(self.on_log)
        self.signals.progress_signal.connect(self.on_progress)
        self.signals.error_signal.connect(self.on_error)
        self.signals.cia_start_signal.connect(self.on_cia_start)
        self.signals.status_signal.connect(self.on_status_update)

        # Initial state
        self.log(f'custom-install {CI_VERSION} - https://github.com/ihaveamac/custom-install')
        self.log('Ready.')

    def setup_file_pickers(self):
        # SD Root picker
        sd_layout = QHBoxLayout()
        self.sd_label = QLabel('SD root:')
        self.sd_path = QLineEdit()
        self.sd_button = QPushButton('...')
        self.sd_button.clicked.connect(self.select_sd_root)
        sd_layout.addWidget(self.sd_label)
        sd_layout.addWidget(self.sd_path)
        sd_layout.addWidget(self.sd_button)
        self.layout.addLayout(sd_layout)

        # Boot9 picker
        boot9_layout = QHBoxLayout()
        self.boot9_label = QLabel('boot9:')
        self.boot9_path = QLineEdit()
        if default_b9_path:
            self.boot9_path.setText(default_b9_path)
        self.boot9_button = QPushButton('...')
        self.boot9_button.clicked.connect(lambda: self.select_file('boot9', '*.bin'))
        boot9_layout.addWidget(self.boot9_label)
        boot9_layout.addWidget(self.boot9_path)
        boot9_layout.addWidget(self.boot9_button)
        self.layout.addLayout(boot9_layout)

        # Seeddb picker
        seeddb_layout = QHBoxLayout()
        self.seeddb_label = QLabel('seeddb:')
        self.seeddb_path = QLineEdit()
        if default_seeddb_path:
            self.seeddb_path.setText(default_seeddb_path)
        self.seeddb_button = QPushButton('...')
        self.seeddb_button.clicked.connect(lambda: self.select_file('seeddb', '*.bin'))
        seeddb_layout.addWidget(self.seeddb_label)
        seeddb_layout.addWidget(self.seeddb_path)
        seeddb_layout.addWidget(self.seeddb_button)
        self.layout.addLayout(seeddb_layout)

        # Movable.sed picker
        movable_layout = QHBoxLayout()
        self.movable_label = QLabel('movable.sed:')
        self.movable_path = QLineEdit()
        if default_movable_sed_path:
            self.movable_path.setText(default_movable_sed_path)
        self.movable_button = QPushButton('...')
        self.movable_button.clicked.connect(lambda: self.select_file('movable.sed', '*.sed'))
        movable_layout.addWidget(self.movable_label)
        movable_layout.addWidget(self.movable_path)
        movable_layout.addWidget(self.movable_button)
        self.layout.addLayout(movable_layout)

    def setup_title_buttons(self):
        button_layout = QHBoxLayout()
        
        self.add_cia_button = QPushButton('Add CIAs')
        self.add_cia_button.clicked.connect(self.add_cias)
        button_layout.addWidget(self.add_cia_button)

        self.add_cdn_button = QPushButton('Add CDN title folder')
        self.add_cdn_button.clicked.connect(self.add_cdn)
        button_layout.addWidget(self.add_cdn_button)

        self.add_folder_button = QPushButton('Add folder')
        self.add_folder_button.clicked.connect(self.add_folder)
        button_layout.addWidget(self.add_folder_button)

        self.remove_button = QPushButton('Remove selected')
        self.remove_button.clicked.connect(self.remove_selected)
        button_layout.addWidget(self.remove_button)

        self.layout.addLayout(button_layout)

    def setup_title_list(self):
        # Create a splitter for the tree view and log window
        self.splitter = QSplitter()
        self.splitter.setOrientation(Qt.Orientation.Vertical)
        self.layout.addWidget(self.splitter)

        # Title list
        self.title_list = QTreeWidget()
        self.title_list.setHeaderLabels(['Cover Art', 'File path', 'Title ID', 'Title name', 'Status'])
        self.title_list.setColumnWidth(0, 100)
        self.title_list.setColumnWidth(1, 200)
        self.title_list.setColumnWidth(2, 70)
        self.title_list.setColumnWidth(3, 150)
        self.title_list.setColumnWidth(4, 70)
        self.splitter.addWidget(self.title_list)

        # Log window
        self.log_window = QTextEdit()
        self.log_window.setReadOnly(True)
        self.log_window.setMinimumHeight(100)
        self.splitter.addWidget(self.log_window)

    def setup_progress(self):
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximum(100)
        self.layout.addWidget(self.progress_bar)

    def setup_controls(self):
        control_layout = QHBoxLayout()

        self.skip_contents = QCheckBox('Skip contents (only add to title database)')
        control_layout.addWidget(self.skip_contents)

        self.overwrite_saves = QCheckBox('Overwrite existing saves')
        control_layout.addWidget(self.overwrite_saves)

        self.start_button = QPushButton('Start install')
        self.start_button.clicked.connect(self.start_install)
        control_layout.addWidget(self.start_button)

        self.layout.addLayout(control_layout)

        self.status_label = QLabel('Waiting...')
        self.layout.addWidget(self.status_label)

    def select_sd_root(self):
        directory = QFileDialog.getExistingDirectory(self, "Select SD root")
        if directory:
            cifinish_path = join(directory, 'cifinish.bin')
            try:
                load_cifinish(cifinish_path)
            except InvalidCIFinishError:
                QMessageBox.critical(self, 'Error', 
                    f'{cifinish_path} was corrupt!\n\n'
                    f'This could mean an issue with the SD card or the filesystem. Please check it for errors.\n'
                    f'It is also possible, though less likely, to be an issue with custom-install.\n\n'
                    f'Stopping now to prevent possible issues. If you want to try again, delete cifinish.bin from the SD card and re-run custom-install.')
                return

            self.sd_path.setText(directory)
            
            # Auto-detect files
            for filename in ['boot9.bin', 'seeddb.bin', 'movable.sed']:
                path = self.auto_detect_file(directory, filename)
                if filename == 'boot9.bin':
                    self.check_b9_loaded()
                if filename == 'seeddb.bin' and path:
                    load_seeddb(path)

    def auto_detect_file(self, sd_root: str, filename: str) -> str:
        paths = [join(sd_root, 'gm9', 'out', filename), join(sd_root, filename)]
        found_path = find_first_file(paths)
        if found_path:
            self.log(f'Found {filename} on SD card at {found_path}')
            if filename == 'boot9.bin':
                self.boot9_path.setText(found_path)
            elif filename == 'seeddb.bin':
                self.seeddb_path.setText(found_path)
            elif filename == 'movable.sed':
                self.movable_path.setText(found_path)
            return found_path
        return None

    def select_file(self, file_type: str, file_filter: str):
        file_name, _ = QFileDialog.getOpenFileName(self, f"Select {file_type}", "", f"{file_type} ({file_filter})")
        if file_name:
            if file_type == 'boot9':
                self.boot9_path.setText(file_name)
                self.check_b9_loaded()
            elif file_type == 'seeddb':
                self.seeddb_path.setText(file_name)
                load_seeddb(file_name)
            elif file_type == 'movable.sed':
                self.movable_path.setText(file_name)

    def add_cias(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Select CIA files", "", "CIA files (*.cia)")
        failed = {}
        for f in files:
            success, reason = self.add_cia(f)
            if not success:
                failed[f] = reason
        
        if failed:
            error_text = "Failed to add the following files:\n\n"
            for path, reason in failed.items():
                error_text += f"{basename(path)}: {reason}\n"
            QMessageBox.warning(self, "Failed to add titles", error_text)

    def add_cdn(self):
        directory = QFileDialog.getExistingDirectory(self, "Select CDN title folder")
        if directory:
            if isfile(join(directory, 'tmd')):
                success, reason = self.add_cia(directory)
                if not success:
                    QMessageBox.critical(self, "Error", f"Couldn't add {basename(directory)}: {reason}")
            else:
                QMessageBox.critical(self, "Error", f"tmd file not found in the CDN directory:\n{directory}")

    def add_folder(self):
        directory = QFileDialog.getExistingDirectory(self, "Select folder containing CIA files")
        if directory:
            failed = {}
            for f in scandir(directory):
                if f.name.lower().endswith('.cia'):
                    success, reason = self.add_cia(f.path)
                    if not success:
                        failed[f.path] = reason
            
            if failed:
                error_text = "Failed to add the following files:\n\n"
                for path, reason in failed.items():
                    error_text += f"{basename(path)}: {reason}\n"
                QMessageBox.warning(self, "Failed to add titles", error_text)

    def remove_selected(self):
        for item in self.title_list.selectedItems():
            self.title_list.takeTopLevelItem(self.title_list.indexOfTopLevelItem(item))
            path = item.text(1)
            if path in self.readers:
                del self.readers[path]

    def add_cia(self, path: str) -> tuple[bool, str]:
        try:
            with self.lock:
                if path in self.readers:
                    return False, 'Title already added'
                
                if path.endswith('.cia'):
                    reader = CIAReader(path)
                else:
                    reader = CDNReader(path)
                
                self.readers[path] = reader
                
                # Get title name
                try:
                    title_name = reader.contents[0].exefs.icon.get_app_title().short_desc
                except:
                    title_name = '(No title)'

                # Get icon
                try:
                    icon = reader.contents[0].exefs.icon.get_large_icon()
                    icon_data = BytesIO()
                    icon.save(icon_data, format='PNG')
                    pixmap = QPixmap()
                    pixmap.loadFromData(icon_data.getvalue())
                except:
                    pixmap = QPixmap()  # Empty pixmap if no icon

                # Get cover art
                try:
                    cover_art = reader.contents[0].exefs.icon.get_cover_art()
                    cover_art_data = BytesIO()
                    cover_art.save(cover_art_data, format='PNG')
                    cover_art_pixmap = QPixmap()
                    cover_art_pixmap.loadFromData(cover_art_data.getvalue())
                except:
                    cover_art_pixmap = QPixmap()  # Empty pixmap if no cover art

                item = QTreeWidgetItem([
                    '',
                    path,
                    str(reader.tmd.title_id).upper(),
                    title_name,
                    'Waiting'
                ])
                
                # Set icon if available
                if not pixmap.isNull():
                    item.setIcon(0, QIcon(pixmap))
                
                # Set cover art if available
                if not cover_art_pixmap.isNull():
                    item.setIcon(0, QIcon(cover_art_pixmap))
                
                self.title_list.addTopLevelItem(item)
                return True, ''
                
        except CIAError as e:
            return False, f'Failed to read CIA: {e}'
        except CDNError as e:
            return False, f'Failed to read CDN: {e}'
        except TitleMetadataError as e:
            return False, f'Failed to read TMD: {e}'
        except Exception as e:
            return False, str(e)

    def check_b9_loaded(self):
        self.b9_loaded = False
        try:
            crypto = CryptoEngine(boot9=self.boot9_path.text() if self.boot9_path.text() else None)
            self.b9_loaded = True
        except MissingSeedError:
            pass
        except Exception as e:
            self.log(f'Failed to load boot9: {e}')

        self.update_button_states()

    def update_button_states(self):
        enabled = self.b9_loaded
        self.add_cia_button.setEnabled(enabled)
        self.add_cdn_button.setEnabled(enabled)
        self.add_folder_button.setEnabled(enabled)
        self.remove_button.setEnabled(enabled)
        self.start_button.setEnabled(enabled)

    def log(self, message: str):
        timestamp = datetime.now().strftime('%H:%M:%S')
        log_msg = f"{timestamp} - {message}"
        self.signals.log_signal.emit(log_msg)

    def on_log(self, message: str):
        self.log_window.append(message)
        # Make sure the latest log is visible
        self.log_window.verticalScrollBar().setValue(
            self.log_window.verticalScrollBar().maximum()
        )

    def on_progress(self, total_percent: float, total_read: int, size: int):
        self.progress_bar.setValue(int(total_percent))

    def on_error(self, exc: Exception):
        self.log(f'Error: {exc}')
        self.signals.log_signal.emit(f"Error: {str(exc)}")

    def on_cia_start(self, idx: int):
        self.log(f'Starting CIA installation {idx}')

    def on_status_update(self, path: str, status: InstallStatus):
        status_text = status.name if isinstance(status, InstallStatus) else str(status)
        self.log(f'Status update for {path}: {status_text}')
        # Find and update the item in the tree widget
        items = self.title_list.findItems(path, Qt.MatchFlag.MatchExactly, 1)
        if items:
            items[0].setText(4, status_text)

    def start_install(self):
        if not self.readers:
            self.signals.log_signal.emit("No titles added")
            return

        # Disable install button
        self.start_button.setEnabled(False)
        self.log("Starting installation...")
        self.install_thread = Thread(target=self.install)
        self.install_thread.start()

    def install(self):
        try:
            self.log("Preparing for installation...")
            # Get the SD root path
            sd_path = self.sd_path.text()
            if not sd_path:
                raise Exception("SD root path not set")

            # Get the movable.sed path
            movable_path = self.movable_path.text()
            if not movable_path:
                raise Exception("movable.sed path not set")

            # Create CustomInstall instance
            custom_install = CustomInstall(
                boot9=self.boot9_path.text() if self.boot9_path.text() else None,
                seeddb=self.seeddb_path.text() if self.seeddb_path.text() else None,
                movable=movable_path,
                sd=sd_path,
                skip_contents=self.skip_contents.isChecked(),
                overwrite_saves=self.overwrite_saves.isChecked()
            )

            # Set up event handlers
            custom_install.event.on_log_msg += lambda msg, **kwargs: self.signals.log_signal.emit(str(msg))
            custom_install.event.update_percentage += lambda total_percent, total_read, size: self.signals.progress_signal.emit(total_percent, total_read, size)
            custom_install.event.on_error += lambda exc: self.signals.error_signal.emit(exc)
            custom_install.event.on_cia_start += lambda idx: self.signals.cia_start_signal.emit(idx)

            # Prepare readers in the order they appear in the tree
            root = self.title_list.invisibleRootItem()
            total_items = root.childCount()
            
            self.log(f"Found {total_items} titles to install")
            
            # Create list of readers in the order they appear in the tree
            for i in range(total_items):
                item = root.child(i)
                path = item.text(1)
                if path in self.readers:
                    custom_install.readers.append((self.readers[path], path))
                    self.log(f"Prepared {path} for installation")

            # Check for id0
            if not custom_install.check_for_id0():
                raise Exception(
                    f'id0 {custom_install.crypto.id0.hex()} was not found inside "Nintendo 3DS" on the SD card.\n'
                    f'\n'
                    f'Before using custom-install, you should use this SD card on the appropriate console.\n'
                    f'\n'
                    f'Otherwise, make sure the correct movable.sed is being used.'
                )

            # Start the installation
            self.log("Beginning title installation...")
            custom_install.start()
            
            # Clear the list after successful installation
            self.title_list.clear()
            self.readers.clear()
            
            self.signals.log_signal.emit("Installation completed successfully!")
            self.signals.status_signal.emit("Success", InstallStatus.Done)
            
        except Exception as e:
            self.signals.log_signal.emit(f"Installation failed: {str(e)}")
            self.signals.error_signal.emit(e)
        finally:
            # Re-enable install button
            self.start_button.setEnabled(True)

def main():
    app = QApplication(sys.argv)
    window = CustomInstallGUI()
    window.show()
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
