from custominstall import CustomInstall
import tkinter as tk
from tkinter.filedialog import askopenfilenames
from tkinter.ttk import Progressbar
import os
import datetime
import threading
import queue


class CustomInstallGui(tk.Frame):
    def __init__(self, master=None):
        tk.Frame.__init__(self, master)
        self.master = master

        # Title name for window
        self.window_title = "Custom-Install GUI"

        # Config
        self.skip_contents = False
        self.cias = []
        self.boot9 = None
        self.movable = None
        self.sd = None
        self.skip_cont_var = tk.IntVar(self)

        for x in range(8):
            tk.Grid.rowconfigure(self, x, weight=1)
        for x in range(1):
            tk.Grid.columnconfigure(self, x, weight=1)
    
    def set_cias(self, filename):
        self.cias = filename
    
    def set_boot9(self, filename):
        self.boot9 = filename
    
    def set_movable(self, filename):
        self.movable = filename
    
    def set_sd(self, directory):
        self.sd = directory
    
    def start_install(self, event):
        self.progress['value'] = 0
        error = False

        # Checks
        if len(self.cias) == 0:
            self.add_log_msg("Error: Please select CIA file(s)")
            error = True
        if self.boot9 == None:
            self.add_log_msg("Error: Please add your boot9 file")
            error = True
        if self.movable == None:
            self.add_log_msg("Error: Please add your movable file")
        if self.sd == None:
            self.add_log_msg("Error: Please locate your SD card directory")
            self.add_log_msg("Note: Linux usually mounts to /media/")
        if error:
            self.add_log_msg("--- Errors occured, aborting ---")
            return False

        # Start the job
        if self.skip_cont_var.get() == 1: self.skip_contents = True
        else: self.skip_contents = False

        print(f'{self.cias}\n{self.boot9}\n{self.movable}\n{self.skip_contents}')
        self.log.insert(tk.END, "Starting install...\n")

        installer = CustomInstall(boot9=self.boot9, 
                movable=self.movable, 
                cias=self.cias, 
                sd=self.sd, 
                skip_contents=self.skip_contents)
        

        # DEBUG
        # self.debug_values()
        
        def start_install():
            def log_handle(message, end=None): self.add_log_msg(message)
            def percentage_handle(percent, total_read, size): self.progress['value'] = percent

            installer.event.on_log_msg += log_handle
            installer.event.update_percentage += percentage_handle
            installer.start()
            print('--- Script is done ---')

        t = threading.Thread(target=start_install)
        t.start()
    

        

    def debug_values(self):
        self.add_log_msg(self.boot9)
        self.add_log_msg(self.movable)
        self.add_log_msg(self.cias)
        self.add_log_msg(self.sd)
        self.add_log_msg(self.skip_contents)

    def start(self):
        self.master.title(self.window_title)
        self.pack(fill=tk.BOTH, expand=True)

        self.log = tk.Text(self, height=10, width=40)
        install = tk.Button(self, text="Install CIA")
        skip_checkbox = tk.Checkbutton(self, text="Skip Contents", variable=self.skip_cont_var)

        self.progress = Progressbar(self, orient=tk.HORIZONTAL, length=100, mode='determinate')

        # File pickers
        cia_picker = self.filepicker_option("CIA file(s)", True, self.set_cias)
        boot9_picker = self.filepicker_option("Select boot9.bin...", False, self.set_boot9)
        movable_picker = self.filepicker_option("Select movable.sed...", False, self.set_movable)
        sd_picker = self.filepicker_option("Select SD card...", False, self.set_sd, True)
        
        # Place widgets
        self.log.grid(column=0, row=0, sticky=tk.N+tk.E+tk.W)
        self.progress.grid(column=0, row=1, sticky=tk.E+tk.W)
        sd_picker.grid(column=0, row=2, sticky=tk.E+tk.W)
        boot9_picker.grid(column=0, row=3, sticky=tk.E+tk.W)
        movable_picker.grid(column=0, row=4, sticky=tk.E+tk.W)
        cia_picker.grid(column=0, row=5, sticky=tk.E+tk.W)
        skip_checkbox.grid(column=0, row=6, sticky=tk.E+tk.W)
        install.grid(column=0, row=7, sticky=tk.S+tk.E+tk.W)
        

        # Events
        install.bind('<Button-1>', self.start_install)

        # Just a greeting :)
        now = datetime.datetime.now()
        time_short = "day!"
        if now.hour < 12: time_short = "morning!"
        elif now.hour > 12: time_short = "afternoon!"  
        self.add_log_msg(f'Good {time_short} Please pick your boot9, movable.sed, SD, and CIA file(s).\n---\nPress "Install CIA" when ready!')

    def add_log_msg(self, message):
        self.log.insert(tk.END, str(message)+"\n")
        self.log.see(tk.END)
    
    def filepicker_option(self, title, multiple_files, on_file_add, dir_only=False):
        frame = tk.Frame(self)
        
        browse_button = tk.Button(frame, text="Pick file")
        filename_label = tk.Label(frame, text=title, wraplength=200)

        browse_button.grid(column=0, row=0)
        filename_label.grid(column=1, row=0)

        # Wrapper for event
        def file_add(event):
            if dir_only:
                folder = tk.filedialog.askdirectory()
                if not folder:
                    return False
                    
                dir = os.path.basename(folder)
                filename_label.config(text="SD => "+dir)

                on_file_add(folder)
                return True
            # Returns multiple files in a tuple
            filename = (tk.filedialog.askopenfilenames()
                            if multiple_files else
                            tk.filedialog.askopenfilename())

            # User may select "cancel"
            if not filename:
                return False


            if multiple_files:
                basename = os.path.basename(filename[0])
                if len(filename) <= 1:
                    more = ""
                elif len(filename) > 1:
                    more = " + "+str(len(filename))+" more"
            else:
                basename = os.path.basename(filename)
                more = ""

            filename_label.config(text=basename+more)

            # Runs callback provided
            on_file_add(filename)

        browse_button.bind('<Button-1>', file_add)

        return frame


root = tk.Tk()
app = CustomInstallGui(root)
app.start()

root.mainloop()
