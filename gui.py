#A gui for custom-install.py
#By LyfeOnEdge
import os, sys, platform, subprocess, threading
import tkinter as tk
import tkinter.filedialog as tkfiledialog
import style

# BUTTON_COLOR = 
# BUTTON_HIGHLIGHT_COLOR =  
# BUTTON_FONT = 

# Custom button

class themedFrame(tk.Frame):
	def __init__(self, frame, **kw):
		tk.Frame.__init__(self, frame, **kw)
		if not (kw.get("background") or kw.get("bg")):
			self.configure(bg = style.BACKGROUND_COLOR)
		if not kw.get("borderwidth"):
			self.configure(borderwidth = 0)
		if not kw.get("highlightthickness"):
			self.configure(highlightthickness = 0)


class Button(tk.Label):
	"""Cross-platform button"""
	def __init__(self,frame,callback,**kw):
		self.callback = callback
		self.background = "#aaaaaa"
		self.selected = False
		tk.Label.__init__(self, frame, **kw)
		self.configure(anchor="center")
		self.configure(background=self.background)
		self.configure(highlightthickness=1)
		if not "font" in kw.keys():
			self.configure(font = style.BUTTON_FONT)
		self.configure(highlightbackground = "#999999")
		self.bind('<Button-1>', self.on_click)

	# Use callback when our makeshift "button" clicked
	def on_click(self, event=None):
		self.configure(background="#dddddd")
		if not self.selected:
			self.after(100, self.on_click_color_change)
		if self.callback:
			self.callback()

	# Function to set the button's image
	def setimage(self, image):
		self.configure(image=image)

	# Function to set the button's text
	def settext(self, text):
		self.configure(text=text)

	def deselect(self):
		self.selected = False
		self.configure(background=self.background)

	def on_click_color_change(self):
		if not self.selected:
			self.configure(background=self.background)

class PathEntry(tk.Entry):
	"""Tkinter entry widget with a button to set the file path using tkinter's file dialog"""
	def __init__(self, frame, dir = False, filetypes = None, *args, **kw):
		self.dir = dir
		self.filetypes = filetypes
		container = themedFrame(frame)
		self.button = Button(container, self.set_path, text = "...")
		self.button.place(relheight = 1, relx = 1, x = - style.BUTTONSIZE, width = style.BUTTONSIZE)
		tk.Entry.__init__(self, container, *args, **kw)
		self.text_var = tk.StringVar()
		self.configure(textvariable = self.text_var)
		self.configure(background = style.ENTRY_COLOR)
		self.configure(foreground = style.ENTRY_FOREGROUND)
		self.configure(borderwidth = 0)
		self.configure(highlightthickness = 2)
		self.configure(highlightbackground = style.BUTTON_COLOR)
		super().place(relwidth = 1, relheight = 1, width = - style.BUTTONSIZE)
		self.container = container

	def clear(self):
		self.text_var.set("")

	def set(self, string):
		self.text_var.set(string)

	def get_var(self):
		return self.text_var

	def get(self):
		return self.text_var.get()

	def place(self, **kw):
		self.container.place(**kw)

	def set_path(self):
		if not self.dir:
			self.set(tkfiledialog.askopenfilename(filetypes = self.filetypes))
		else:
			self.set(tkfiledialog.askdirectory())

class LabeledPathEntry(PathEntry):
	"""Gives the PathEntry class a label"""
	def __init__(self, frame, text, *args, **kw):
		self.xtainer = themedFrame(frame)
		label = tk.Label(self.xtainer, text = text, background = style.BACKGROUND_COLOR, foreground = style.LABEL_COLOR)
		label.place(width = label.winfo_reqwidth(), relheight = 1)
		PathEntry.__init__(self, self.xtainer, *args, **kw)		
		PathEntry.place(self, relwidth = 1, relheight = 1, width = - (label.winfo_reqwidth() + 5), x = label.winfo_reqwidth() + 5)

	def place(self, **kw):
		self.xtainer.place(**kw)


class AutoScroll(object):
	def __init__(self, master):
		try:
			vsb = tk.Scrollbar(master, orient='vertical', command=self.yview)
		except:
			pass
		hsb = tk.Scrollbar(master, orient='horizontal', command=self.xview)

		try:
			self.configure(yscrollcommand=self._autoscroll(vsb))
		except:
			pass
		self.configure(xscrollcommand=self._autoscroll(hsb))

		self.grid(column=0, row=0, sticky='nsew')
		try:
			vsb.grid(column=1, row=0, sticky='ns')
		except:
			pass
		hsb.grid(column=0, row=1, sticky='ew')

		master.grid_columnconfigure(0, weight=1)
		master.grid_rowconfigure(0, weight=1)

		methods = tk.Pack.__dict__.keys() | tk.Grid.__dict__.keys() \
			| tk.Place.__dict__.keys()

		for m in methods:
			if m[0] != '_' and m not in ('config', 'configure'):
				setattr(self, m, getattr(master, m))


	@staticmethod
	def _autoscroll(sbar):
		'''Hide and show scrollbar as needed.'''
		def wrapped(first, last):
			first, last = float(first), float(last)
			if first <= 0 and last >= 1:
				sbar.grid_remove()
			else:
				sbar.grid()
			sbar.set(first, last)
		return wrapped

	def __str__(self):
		return str(self.master)


def _create_container(func):
	'''Creates a tk Frame with a given master, and use this new frame to
	place the scrollbars and the widget.'''
	def wrapped(cls, master, **kw):
		container = themedFrame(master)
		container.bind('<Enter>', lambda e: _bound_to_mousewheel(e, container))
		container.bind(
			'<Leave>', lambda e: _unbound_to_mousewheel(e, container))
		return func(cls, container, **kw)
	return wrapped


def _bound_to_mousewheel(event, widget):
	child = widget.winfo_children()[0]
	if platform.system() == 'Windows' or platform.system() == 'Darwin':
		child.bind_all('<MouseWheel>', lambda e: _on_mousewheel(e, child))
		child.bind_all('<Shift-MouseWheel>',
					   lambda e: _on_shiftmouse(e, child))
	else:
		child.bind_all('<Button-4>', lambda e: _on_mousewheel(e, child))
		child.bind_all('<Button-5>', lambda e: _on_mousewheel(e, child))
		child.bind_all('<Shift-Button-4>', lambda e: _on_shiftmouse(e, child))
		child.bind_all('<Shift-Button-5>', lambda e: _on_shiftmouse(e, child))


def _unbound_to_mousewheel(event, widget):
	if platform.system() == 'Windows' or platform.system() == 'Darwin':
		widget.unbind_all('<MouseWheel>')
		widget.unbind_all('<Shift-MouseWheel>')
	else:
		widget.unbind_all('<Button-4>')
		widget.unbind_all('<Button-5>')
		widget.unbind_all('<Shift-Button-4>')
		widget.unbind_all('<Shift-Button-5>')


def _on_mousewheel(event, widget):
	if platform.system() == 'Windows':
		widget.yview_scroll(-1 * int(event.delta / 120), 'units')
	elif platform.system() == 'Darwin':
		widget.yview_scroll(-1 * int(event.delta), 'units')
	else:
		if event.num == 4:
			widget.yview_scroll(-1, 'units')
		elif event.num == 5:
			widget.yview_scroll(1, 'units')


class ScrolledText(AutoScroll, tk.Text):
	@_create_container
	def __init__(self, master, **kw):
		tk.Text.__init__(self, master, **kw)
		AutoScroll.__init__(self, master)

# from https://stackoverflow.com/questions/3221956/how-do-i-display-tooltips-in-tkinter


class CreateToolTip(object):
	'''
	create a tooltip for a given widget
	'''
	def __init__(self, widget, text='widget info'):
		self.widget = widget
		self.text = text
		self.widget.bind("<Enter>", self.enter)
		self.widget.bind("<Leave>", self.close)

	def enter(self, event=None):
		x = y = 0
		x, y, cx, cy = self.widget.bbox("insert")
		x += self.widget.winfo_rootx()
		y += self.widget.winfo_rooty() + 20
		# creates a toplevel window
		self.tw = tk.Toplevel(self.widget)
		# Leaves only the label and removes the app window
		self.tw.wm_overrideredirect(True)
		self.tw.wm_geometry("+%d+%d" % (x, y))
		label = tk.Label(self.tw, text=self.text, justify='left',
					   background='gray', foreground = style.LABEL_COLOR,
					   relief='solid', borderwidth=2,
					   font=("times", "12", "normal"),
					   wraplength = self.widget.winfo_width())
		label.pack(ipadx=1)

	def close(self, event=None):
		if self.tw:
			self.tw.destroy()


class threader_object:
	"""an object to be declared outside of tk root so 
	things can be called asyncronously (you cannot start
	a new thread from within a tkinter callback so you
	must call it from an object that exists outside)"""
	def do_async(self, func, arglist = []):
		threading.Thread(target = func, args = arglist).start()


class gui(tk.Tk):
	def __init__(self, threader):
		self.threader = threader
		tk.Tk.__init__(self)
		self.minsize(300, 400)
		self.title("custom-install gui")
		self.f = themedFrame(self)
		self.f.place(relwidth = 1, relheight = 1)
		
		outer_frame = themedFrame(self.f)
		outer_frame.place(relwidth = 1, relheight = 1, x = + style.STANDARD_OFFSET, width = - 2 * style.STANDARD_OFFSET, y = + style.STANDARD_OFFSET, height = - 2 * style.STANDARD_OFFSET)
		
		self.sd_box = LabeledPathEntry(outer_frame, "Path to SD root -", dir = True)
		self.sd_box.place(relwidth = 1, height = 20, x = 0)
		CreateToolTip(self.sd_box.xtainer, "Select the root of the sd card you wish to install the cias to.")
		
		self.sed_box = LabeledPathEntry(outer_frame, "Path to movable.sed file -", filetypes = [('sed file', '*.sed')])
		self.sed_box.place(relwidth = 1, height = 20, x = 0, y = 30)
		CreateToolTip(self.sed_box.xtainer, "Select movable.sed file, this can be dumped from a 3ds")

		self.boot9_box = LabeledPathEntry(outer_frame, "Path to boot9 file -", filetypes = [('boot9 file', '*.bin')])
		self.boot9_box.place(relwidth = 1, height = 20, x = 0, y = 60)
		CreateToolTip(self.boot9_box.xtainer, "Select the path to boot9.bin, this can be dumped from a 3ds")

		#-------------------------------------------------
		cia_container = themedFrame(outer_frame, borderwidth = 0, highlightthickness = 0)
		cia_container.place(y = 90, relwidth = 1, height = 115)

		cia_label = tk.Label(cia_container, text = "cia paths - ", foreground = style.LABEL_COLOR, background = style.BACKGROUND_COLOR)
		cia_label.place(relwidth = 1, height = 20)
		self.cia_box = tk.Listbox(cia_container, highlightthickness = 0, bg = style.ENTRY_COLOR, foreground = style.ENTRY_FOREGROUND)
		self.cia_box.place(relwidth = 1, height = 70, y = 20)
		CreateToolTip(cia_label, "Select the cias you wish to install to the sd card. The `add folder` button will add all cias in the selected folder, but will not check subdirs. The `remove cia` button will remove the currently selected file from the listbox.")
		
		add_cia_button = Button(cia_container, self.add_cia, text = "add cia", font = style.monospace)
		add_cia_button.place(relx = 0, relwidth = 0.333, height = 20, y = 92, width = - 6)
		
		add_cia_folder_button = Button(cia_container, self.add_cia_folder, text = "add folder", font = style.monospace)
		add_cia_folder_button.place(relx = 0.333, relwidth = 0.333, height = 20, y = 92, x = + 3, width = - 6)
		
		remove_cia_button = Button(cia_container, self.remove_cia, text = "remove cia", font = style.monospace)
		remove_cia_button.place(relx = 0.666, relwidth = 0.333, height = 20, y = 92, x = + 6, width = - 6)
		#-------------------------------------------------

		self.skip_contents = tk.IntVar()
		skip_contents_checkbutton = tk.Checkbutton(outer_frame, text="Skip contents? (only add title info)", variable=self.skip_contents, background = style.BACKGROUND_COLOR, foreground = style.LABEL_COLOR, borderwidth = 0, highlightthickness = 0)
		skip_contents_checkbutton.place(relwidth = 1, y = 205, height = 20)

		console_label = tk.Label(outer_frame, text = "Console:", background = "black", foreground = "white", font = style.boldmonospace, borderwidth = 0, highlightthickness = 0)
		console_label.place(relwidth = 1, height = 20, y = 230)
		self.console = ScrolledText(outer_frame, background = "black", foreground = "white", highlightthickness = 0)
		self.console.place(relwidth = 1, relheight = 1, y = 250, height = - 272)
		run_button = Button(outer_frame, self.run, text = "run", font = style.boldmonospace)
		run_button.place(relwidth = 1, rely = 1, y = - 22)

	def run(self):
		argstring = ""

		self.output_to_console("-----------------------\nStarting...\n")

		boot9 = self.boot9_box.get()
		if not boot9:
			self.output_to_console("Warning - boot9 not selected, if it's not set externally you may run into problems.\n")
		argstring += f"-b {boot9} "
		
		sed = self.sed_box.get()
		if not sed:
			self.output_to_console("Failed to run - No movable.sed selected.\n")
			return
		argstring += f"-m {sed} "

		sd = self.sd_box.get().strip()
		if not sd:
			self.output_to_console("Failed to run - SD path not selected.\n")
			return
		argstring += f"--sd {sd} "

		cias = []
		for i in range(0, self.cia_box.size()):
			cias.append(self.cia_box.get(i).strip())
		for cia in cias:
			argstring += f" {cia}"

		if self.skip_contents.get():
			argstring += "--skip-contents "

		print(f"Running custom-install.py with args {args}\n")

		self.threader.do_async(execute_script, [argstring, self.output_to_console])

	def output_to_console(self, outstring):
		self.console.insert('end', outstring)
		self.console.see('end')

	def add_cia(self):
		cia_to_add = tkfiledialog.askopenfilename(filetypes = [('cia file', '*.cia')])
		if cia_to_add:
			self.cia_box.insert('end', cia_to_add)

	def add_cia_folder(self):
		cia_dir_to_add = tkfiledialog.askdirectory()
		if cia_dir_to_add:
			cias_to_add = [f for f in os.listdir(cia_dir_to_add) if (os.path.isfile(os.path.join(cia_dir_to_add, f)) and f.endswith(".cia"))]
			if cias_to_add:
				for cia_to_add in cias_to_add:
					self.cia_box.insert('end', cia_to_add)

	def remove_cia(self):
		index = self.cia_box.curselection()
		if index:
			self.cia_box.delete(index)
			if self.cia_box.size():
				self.cia_box.select_clear(0, 'end')
				if self.cia_box.size() > 1:
					try:
						self.cia_box.select_set(index)
					except:
						pass
				else:
					self.cia_box.select_set(0)


def execute_script(argstring, printer):
	"""Wrapper function to pipe install script output to a printer"""
	try:
		args = [sys.executable, '-u', os.path.join(os.path.dirname(__file__), "custom-install.py")]
		for arg in argstring.split():
			args.append(arg.strip())
		p = subprocess.Popen(args,
				stdout=subprocess.PIPE, 
				stderr=subprocess.STDOUT, 
				bufsize=1,
			)

		with p.stdout:
			for line in iter(p.stdout.readline, b''):
				printer(line)
		p.wait()
	except Exception as e:
		printer(f"Error while executing script with args - {argstring} | Exception - {e}\n")


t = threader_object()
window = gui(t)
window.mainloop()
