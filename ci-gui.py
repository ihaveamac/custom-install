# This file is a part of custom-install.py.
#
# custom-install is copyright (c) 2019-2020 Ian Burgwin
# This file is licensed under The MIT License (MIT).
# You can find the full license text in LICENSE.md in the root of this project.

from os import environ, scandir
from os.path import abspath, join, isfile, dirname
from sys import exc_info, platform
from threading import Thread, Lock
from time import strftime
from traceback import format_exception
import tkinter as tk
import tkinter.ttk as ttk
import tkinter.filedialog as fd
import tkinter.messagebox as mb
from typing import TYPE_CHECKING

from pyctr.crypto.engine import b9_paths
from pyctr.util import config_dirs

from custominstall import CustomInstall

if TYPE_CHECKING:
    from typing import List

is_windows = platform == 'win32'
taskbar = None
if is_windows:
    try:
        import comtypes.client as cc

        tbl = cc.GetModule('TaskbarLib.tlb')

        taskbar = cc.CreateObject('{56FDF344-FD6D-11D0-958A-006097C9A090}', interface=tbl.ITaskbarList3)
        taskbar.HrInit()
    except ModuleNotFoundError:
        pass

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


class ConsoleFrame(ttk.Frame):
    def __init__(self, parent: tk.BaseWidget = None, starting_lines: 'List[str]' = None):
        super().__init__(parent)
        self.parent = parent

        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        scrollbar = ttk.Scrollbar(self, orient=tk.VERTICAL)
        scrollbar.grid(row=0, column=1, sticky=tk.NSEW)

        self.text = tk.Text(self, highlightthickness=0, wrap='word', yscrollcommand=scrollbar.set)
        self.text.grid(row=0, column=0, sticky=tk.NSEW)

        scrollbar.config(command=self.text.yview)

        if starting_lines:
            for l in starting_lines:
                self.text.insert(tk.END, l + '\n')

        self.text.see(tk.END)
        self.text.configure(state=tk.DISABLED)

    def log(self, *message, end='\n', sep=' '):
        self.text.configure(state=tk.NORMAL)
        self.text.insert(tk.END, sep.join(message) + end)
        self.text.see(tk.END)
        self.text.configure(state=tk.DISABLED)


class CustomInstallGUI(ttk.Frame):
    console = None

    def __init__(self, parent: tk.Tk = None):
        super().__init__(parent)
        self.parent = parent

        self.lock = Lock()

        self.log_messages = []

        self.hwnd = None  # will be set later

        self.rowconfigure(2, weight=1)
        self.columnconfigure(0, weight=1)

        if taskbar:
            # this is so progress can be shown in the taskbar
            def setup_tab():
                self.hwnd = int(parent.wm_frame(), 16)
                taskbar.ActivateTab(self.hwnd)

            self.after(100, setup_tab)

        # ---------------------------------------------------------------- #
        # create file pickers for base files
        file_pickers = ttk.Frame(self)
        file_pickers.grid(row=0, column=0, sticky=tk.EW)
        file_pickers.columnconfigure(1, weight=1)

        self.file_picker_textboxes = {}

        def sd_callback():
            f = fd.askdirectory(parent=parent, title='Select SD root (the directory or drive that contains '
                                                     '"Nintendo 3DS")', initialdir=file_parent, mustexist=True)
            if f:
                sd_selected.delete('1.0', tk.END)
                sd_selected.insert(tk.END, f)

                sd_msed_path = find_first_file([join(f, 'gm9', 'out', 'movable.sed'), join(f, 'movable.sed')])
                if sd_msed_path:
                    self.log('Found movable.sed on SD card at ' + sd_msed_path)
                    box = self.file_picker_textboxes['movable.sed']
                    box.delete('1.0', tk.END)
                    box.insert(tk.END, sd_msed_path)

        sd_type_label = ttk.Label(file_pickers, text='SD root')
        sd_type_label.grid(row=0, column=0)

        sd_selected = tk.Text(file_pickers, wrap='none', height=1)
        sd_selected.grid(row=0, column=1, sticky=tk.EW)

        sd_button = ttk.Button(file_pickers, text='...', command=sd_callback)
        sd_button.grid(row=0, column=2)

        self.file_picker_textboxes['sd'] = sd_selected

        # This feels so wrong.
        def create_required_file_picker(type_name, types, default, row):
            def internal_callback():
                f = fd.askopenfilename(parent=parent, title='Select ' + type_name, filetypes=types,
                                       initialdir=file_parent)
                if f:
                    selected.delete('1.0', tk.END)
                    selected.insert(tk.END, f)

            type_label = ttk.Label(file_pickers, text=type_name)
            type_label.grid(row=row, column=0)

            selected = tk.Text(file_pickers, wrap='none', height=1)
            selected.grid(row=row, column=1, sticky=tk.EW)
            if default:
                selected.insert(tk.END, default)

            button = ttk.Button(file_pickers, text='...', command=internal_callback)
            button.grid(row=row, column=2)

            self.file_picker_textboxes[type_name] = selected

        create_required_file_picker('boot9', [('boot9 file', '*.bin')], default_b9_path, 1)
        create_required_file_picker('seeddb', [('seeddb file', '*.bin')], default_seeddb_path, 2)
        create_required_file_picker('movable.sed', [('movable.sed file', '*.sed')], default_movable_sed_path, 3)

        # ---------------------------------------------------------------- #
        # create buttons to add cias
        listbox_buttons = ttk.Frame(self)
        listbox_buttons.grid(row=1, column=0)

        def add_cias_callback():
            files = fd.askopenfilenames(parent=parent, title='Select CIA files', filetypes=[('CIA files', '*.cia')],
                                        initialdir=file_parent)
            for f in files:
                self.add_cia(f)

        add_cias = ttk.Button(listbox_buttons, text='Add CIAs', command=add_cias_callback)
        add_cias.grid(row=0, column=0)

        def add_dirs_callback():
            d = fd.askdirectory(parent=parent, title='Select folder containing CIA files', initialdir=file_parent)
            if d:
                for f in scandir(d):
                    if f.name.lower().endswith('.cia'):
                        self.add_cia(f.path)

        add_dirs = ttk.Button(listbox_buttons, text='Add folder', command=add_dirs_callback)
        add_dirs.grid(row=0, column=1)

        def remove_selected_callback():
            indexes = self.cia_listbox.curselection()
            n = 0
            for i in indexes:
                self.cia_listbox.delete(i - n)
                n += 1

        remove_selected = ttk.Button(listbox_buttons, text='Remove selected', command=remove_selected_callback)
        remove_selected.grid(row=0, column=2)

        # ---------------------------------------------------------------- #
        # create listbox
        listbox_frame = ttk.Frame(self)
        listbox_frame.grid(row=2, column=0, sticky=tk.NSEW)
        listbox_frame.rowconfigure(0, weight=1)
        listbox_frame.columnconfigure(0, weight=1)

        cia_listbox_scrollbar = ttk.Scrollbar(listbox_frame, orient=tk.VERTICAL)
        cia_listbox_scrollbar.grid(row=0, column=1, sticky=tk.NSEW)

        self.cia_listbox = tk.Listbox(listbox_frame, highlightthickness=0, yscrollcommand=cia_listbox_scrollbar.set,
                                      selectmode=tk.EXTENDED)
        self.cia_listbox.grid(row=0, column=0, sticky=tk.NSEW)

        cia_listbox_scrollbar.config(command=self.cia_listbox.yview)

        # ---------------------------------------------------------------- #
        # create progressbar

        self.progressbar = ttk.Progressbar(self, orient=tk.HORIZONTAL, mode='determinate')
        self.progressbar.grid(row=3, column=0, sticky=tk.NSEW)

        # ---------------------------------------------------------------- #
        # create start and console buttons

        control_frame = ttk.Frame(self)
        control_frame.grid(row=4, column=0)

        self.skip_contents_var = tk.IntVar()
        skip_contents_checkbox = ttk.Checkbutton(control_frame, text='Skip contents (only add to title database)',
                                                 variable=self.skip_contents_var)
        skip_contents_checkbox.grid(row=0, column=0)

        self.overwrite_saves_var = tk.IntVar()
        overwrite_saves_checkbox = ttk.Checkbutton(control_frame, text='Overwrite existing saves',
                                                   variable=self.overwrite_saves_var)
        overwrite_saves_checkbox.grid(row=0, column=1)

        show_console = ttk.Button(control_frame, text='Show console', command=self.open_console)
        show_console.grid(row=0, column=2)

        start = ttk.Button(control_frame, text='Start install', command=self.start_install)
        start.grid(row=0, column=3)

        self.status_label = ttk.Label(self, text='Waiting...')
        self.status_label.grid(row=5, column=0, sticky=tk.NSEW)

        self.log('custom-install by ihaveamac', status=False)
        self.log('https://github.com/ihaveamac/custom-install', status=False)

        if is_windows and not taskbar:
            self.log('Note: comtypes module not found.')
            self.log('Note: Progress will not be shown in the Windows taskbar.')

        self.log('Ready.')

        self.disable_during_install = (add_cias, add_dirs, remove_selected, start, *self.file_picker_textboxes.values())

    def add_cia(self, path):
        path = abspath(path)
        self.cia_listbox.insert(tk.END, path)

    def open_console(self):
        if self.console:
            self.console.parent.lift()
            self.console.focus()
        else:
            console_window = tk.Toplevel()
            console_window.title('custom-install Console')

            self.console = ConsoleFrame(console_window, self.log_messages)
            self.console.pack(fill=tk.BOTH, expand=True)

            def close():
                with self.lock:
                    try:
                        console_window.destroy()
                    except:
                        pass
                    self.console = None

            console_window.focus()

            console_window.protocol('WM_DELETE_WINDOW', close)

    def log(self, line, status=True):
        with self.lock:
            log_msg = f"{strftime('%H:%M:%S')} - {line}"
            self.log_messages.append(log_msg)
            if self.console:
                self.console.log(log_msg)

            if status:
                self.status_label.config(text=line)

    def show_error(self, message):
        mb.showerror('Error', message, parent=self.parent)

    def ask_warning(self, message):
        return mb.askokcancel('Warning', message, parent=self.parent)

    def show_info(self, message):
        mb.showinfo('Info', message, parent=self.parent)

    def disable_buttons(self):
        for b in self.disable_during_install:
            b.config(state=tk.DISABLED)

    def enable_buttons(self):
        for b in self.disable_during_install:
            b.config(state=tk.NORMAL)

    def start_install(self):
        sd_root = self.file_picker_textboxes['sd'].get('1.0', tk.END).strip()
        boot9 = self.file_picker_textboxes['boot9'].get('1.0', tk.END).strip()
        seeddb = self.file_picker_textboxes['seeddb'].get('1.0', tk.END).strip()
        movable_sed = self.file_picker_textboxes['movable.sed'].get('1.0', tk.END).strip()

        if not sd_root:
            self.show_error('SD root is not specified.')
            return
        if not boot9:
            self.show_error('boot9 is not specified.')
            return
        if not movable_sed:
            self.show_error('movable.sed is not specified.')
            return

        if not seeddb:
            if not self.ask_warning('seeddb was not specified. Titles that require it will fail to install.\n'
                                    'Continue?'):
                return

        self.disable_buttons()
        self.log('Starting install...')

        cias = self.cia_listbox.get(0, tk.END)
        if not len(cias):
            self.show_error('There are no titles added to install.')
            return

        installer = CustomInstall(boot9=boot9,
                                  seeddb=seeddb,
                                  movable=movable_sed,
                                  sd=sd_root,
                                  skip_contents=self.skip_contents_var.get() == 1,
                                  overwrite_saves=self.overwrite_saves_var.get() == 1)

        finished_percent = 0
        max_percentage = 100 * len(cias)
        self.progressbar.config(maximum=max_percentage)

        def ci_on_log_msg(message, *args, **kwargs):
            # ignoring end
            self.log(message)

        def ci_update_percentage(total_percent, total_read, size):
            self.progressbar.config(value=total_percent + finished_percent)
            if taskbar:
                taskbar.SetProgressValue(self.hwnd, int(total_percent + finished_percent), max_percentage)

        def ci_on_error(exc):
            if taskbar:
                taskbar.SetProgressState(self.hwnd, tbl.TBPF_ERROR)
            for line in format_exception(*exc):
                for line2 in line.split('\n')[:-1]:
                    installer.log(line2)
            self.show_error('An error occurred during installation.')
            self.open_console()

        def ci_on_cia_start(idx):
            nonlocal finished_percent
            finished_percent = idx * 100
            if taskbar:
                taskbar.SetProgressValue(self.hwnd, finished_percent, max_percentage)

        installer.event.on_log_msg += ci_on_log_msg
        installer.event.update_percentage += ci_update_percentage
        installer.event.on_error += ci_on_error
        installer.event.on_cia_start += ci_on_cia_start

        try:
            installer.prepare_titles(cias)
        except Exception as e:
            for line in format_exception(*exc_info()):
                for line2 in line.split('\n')[:-1]:
                    installer.log(line2)
            self.show_error('An error occurred when trying to read the files.')
            self.open_console()

        if taskbar:
            taskbar.SetProgressState(self.hwnd, tbl.TBPF_NORMAL)

        def install():
            try:
                result, copied_3dsx = installer.start()
                if result is True:
                    self.log('Done!')
                    if copied_3dsx:
                        self.show_info('custom-install-finalize has been copied to the SD card.\n'
                                       'To finish the install, run this on the console through the homebrew launcher.\n'
                                       'This will install a ticket and seed if required.')
                    else:
                        self.show_info('To finish the install, run custom-install-finalize on the console.\n'
                                       'This will install a ticket and seed if required.')
                elif result is False:
                    self.show_error('An error occurred when trying to run save3ds_fuse.')
                    self.open_console()
            except:
                installer.event.on_error(exc_info())
            finally:
                self.enable_buttons()

        Thread(target=install).start()


window = tk.Tk()
window.title('custom-install')
frame = CustomInstallGUI(window)
frame.pack(fill=tk.BOTH, expand=True)
window.mainloop()
