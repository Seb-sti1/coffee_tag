from __future__ import annotations

import asyncio
import logging
import os
import tkinter as tk
from asyncio import Future
from datetime import datetime as dt, timezone
from itertools import count  # Islice for list iteration not starting at 0
from tkinter import Button, Scale
from tkinter import ttk
from typing import Tuple, Optional, Callable, Literal

import bcrypt
from PIL import Image, ImageTk
from juracoffeemachine.coffee_machine import CoffeeMaker, MakerStatus

from coffee_tag import media
from coffee_tag.database import User, Database, Purchase
from coffee_tag.rfid import RFIDReader

logger = logging.getLogger(__name__)


class AbstractUI:

    def __init__(self, main: MainGUI, title: str, w: int, h: int,
                 x: int = None, y: int = None):
        self.future = asyncio.get_event_loop().create_future()
        self.main = main
        self.gui = tk.Toplevel(main.tk)
        self.gui.protocol("WM_DELETE_WINDOW", lambda: [self.future.set_result(None), self.gui.destroy()])
        self.gui.transient(main.tk)
        self.gui.grab_set()
        self.x = (main.tk.winfo_width() - w) // 2 if x is None else x
        self.y = (main.tk.winfo_height() - h) // 2 if y is None else y
        self.gui.geometry(f"{w}x{h}+{self.x}+{self.y}")
        self.gui.title(title)
        self.gui['bg'] = '#754c24'
        self.gui.resizable(height=False, width=False)
        self.w = w
        self.h = h
        main.opened_popup.append(self)

    def is_opened(self) -> bool:
        return self.gui.winfo_exists()

    def add_label(self, text: str, **kwargs) -> tk.Label:
        defaults = {"font": "Helvetica 14", "fg": "white", "bg": "#754c24",
                    "justify": "center", "side": "top", "pady": 10, "fill": "x", "x": 0,
                    "wraplength": self.w - 20, "text": text, "gui": self.gui}
        exclude_keys = ["x", "y", "side", "pady", "fill", "gui"]
        kwargs = {**defaults, **kwargs}
        lbl = tk.Label(kwargs["gui"], **{k: kwargs[k] for k in kwargs.keys() if k not in exclude_keys})
        if "x" in kwargs and "y" in kwargs:
            lbl.place(x=kwargs["x"], y=kwargs["y"])
        else:
            lbl.pack(side=kwargs["side"], pady=kwargs["pady"], fill=kwargs["fill"])
        return lbl

    def add_entry(self, **kwargs) -> tk.Entry:
        font = kwargs["font"] if "font" in kwargs else "Helvetica 14"
        side = kwargs["side"] if "side" in kwargs else "top"
        width = kwargs["width"] if "width" in kwargs else None
        text_var = tk.StringVar(value=kwargs["value"]) if "value" in kwargs else tk.StringVar()

        if "on_text_change" in kwargs:
            def on_text_change(*_):
                kwargs["on_text_change"](text_var)

            text_var.trace_add("write", on_text_change)

        entry = tk.Entry(self.gui, font=font, textvariable=text_var, width=width)

        if "suggestion" in kwargs and ("value" not in kwargs or kwargs["value"] is None or kwargs["value"] == ""):
            def handle_focus_in(_):
                if entry.cget("fg") == 'grey':
                    entry.delete(0, tk.END)
                    entry.config(fg='black')

            def handle_focus_out(_):
                if entry.get() == '':
                    entry.delete(0, tk.END)
                    entry.config(fg='grey')
                    entry.insert(0, kwargs["suggestion"])

            entry.delete(0, tk.END)
            entry.config(fg='grey')
            entry.insert(0, kwargs["suggestion"])
            entry.bind("<FocusIn>", handle_focus_in)
            entry.bind("<FocusOut>", handle_focus_out)
        if "focus" in kwargs and kwargs["focus"]:
            entry.focus_set()
        if "x" in kwargs and "y" in kwargs:
            entry.place(x=kwargs["x"], y=kwargs["y"])
        else:
            entry.pack(side=side)
        return entry

    def add_button(self, text: Optional[str], callback: Callable, **kwargs) -> tk.Button:
        font = kwargs["font"] if "font" in kwargs else "Helvetica 14"
        fg = kwargs["fg"] if "fg" in kwargs else "#5b3719"
        bg = kwargs["bg"] if "bg" in kwargs else "#c9a589"
        height = kwargs["height"] if "height" in kwargs else 3
        width = kwargs["width"] if "width" in kwargs else 15
        side = kwargs["side"] if "side" in kwargs else "bottom"
        pady = kwargs["pady"] if "pady" in kwargs else 10
        image = kwargs["image"] if "image" in kwargs else None
        gui = kwargs["gui"] if "gui" in kwargs else self.gui
        highlightthickness = kwargs["highlightthickness"] if "highlightthickness" in kwargs else None
        bd = kwargs["bd"] if "bd" in kwargs else None
        btn = tk.Button(gui, text=text, font=font, fg=fg, bg=bg, command=callback,
                        height=height, width=width, image=image,
                        highlightthickness=highlightthickness, bd=bd)
        if "x" in kwargs and "y" in kwargs:
            btn.place(x=kwargs["x"], y=kwargs["y"])
        else:
            btn.pack(side=side, pady=pady)
        return btn


class ManualEntry(AbstractUI):

    def __init__(self, main: MainGUI, search_user: Callable[[str], list[User]]):
        super().__init__(main, "Manual identification", 650, 400)
        self.grid_size = (200, 60)  # shift in x and y
        self.grid_counts = (3, 5)  # number of columns and rows
        self.search_user = search_user
        self.add_label("What is your name ?", font="Helvetica 14 bold italic")
        self.entry = self.add_entry(on_text_change=self.on_text_change, focus=True)
        self.add_button("Create new user", self.btn_callback, x=455, y=25, width=14, height=2)
        self.label = self.add_label("Type at least one character.", font="Helvetica 12 italic", fg="#c9a589")
        self.choices: list[tk.Button] = []

    def on_text_change(self, text_var: tk.StringVar):
        for b in self.choices:
            b.place_forget()
        self.choices = []
        self.gui.update()
        if len(text_var.get()) == 0:
            if self.label is None:
                self.label = self.add_label("Type at least one character.", font="Helvetica 12 italic", fg="#c9a589")
                return
        elif self.label is not None:
            self.label.pack_forget()
            self.label = None

        def wrapper_select_user(user: User):
            def select_user():
                self.future.set_result(user)
                self.gui.destroy()

            return select_user

        for idx, u in zip(range(self.grid_counts[0] * self.grid_counts[1]), self.search_user(text_var.get())):
            x, y = (35 + self.grid_size[0] * (idx // self.grid_counts[1]),
                    85 + self.grid_size[1] * (idx % self.grid_counts[1]))

            self.choices.append(self.add_button(f"{u}", wrapper_select_user(u), width=15, height=2, x=x, y=y))

    def btn_callback(self):
        self.future.set_result("add_user")
        self.gui.destroy()

    def get_future(self) -> Future[Optional[User | str]]:
        return self.future


class GeneralUI(AbstractUI):

    def __init__(self, main: MainGUI,
                 title: str,
                 w: int, h: int,
                 sub_text: Optional[str] = None,
                 sub_after_main: Optional[bool] = False,
                 main_text: Optional[str] = None,
                 button_one: Optional[str] = None,
                 button_two: Optional[str] = None,
                 should_close_in_5: bool = False):
        super().__init__(main, title, w, h)
        self.add_label(title, font='Helvetica 22 bold')
        if sub_text and not sub_after_main:
            self.add_label(sub_text, fg="#c9a589", font='Helvetica 12 bold italic', pady=None)
        if main_text:
            self.add_label(main_text, font='Helvetica 16 bold')
        if sub_text and sub_after_main:
            self.add_label(sub_text, fg="#c9a589", font='Helvetica 12 bold italic', pady=None)
        if button_one:
            self.add_button(button_one, self.btn_one_callback, side="top", font='Helvetica 12 bold')
        if button_two:
            self.add_button(button_two, self.btn_two_callback, side="top", font='Helvetica 12 bold')
        if should_close_in_5:
            self.closing_lbl = self.add_label("The window will close in 5 seconds...",
                                              font='Helvetica 12 bold italic',
                                              fg="#c9a589")

    def btn_one_callback(self):
        self.future.set_result(True)
        self.gui.destroy()

    def btn_two_callback(self):
        self.future.set_result(False)
        self.gui.destroy()

    async def get_future_with_autoclosing(self) -> Future[Optional[bool]]:
        for i in range(5, -1, -1):
            if self.future.done():
                break
            self.closing_lbl.config(text=f"The window will close in {i} seconds...")
            self.gui.update()
            await asyncio.sleep(1)
        if not self.future.done():
            self.future.set_result(None)
        self.gui.destroy()
        return self.get_future()

    def get_future(self) -> Future[Optional[bool]]:
        return self.future


class UserMenu(AbstractUI):
    def __init__(self, main: MainGUI, user: User):
        super().__init__(main, "Your account", 420, 370)
        self.add_label(f"Hello {user}!", font='Helvetica 22 bold')
        self.add_label("Your balance is currently", font='Helvetica 15', fg='#c9a589',
                       pady=None, fill=None)
        self.add_label(f"{-user.get_user_balance()} €", font='Helvetica 22 bold')
        last_coffee = user.get_last_coffee()
        if last_coffee is not None:
            self.add_label(f"Your last coffee was {str(dt.now(timezone.utc) - last_coffee.date).split('.')[0]} ago.",
                           font='Helvetica 15', fg='#c9a589', pady=None)
        self.add_label("How many coffees will you take ?", font='Helvetica 15', fg='#c9a589', pady=None, fill=None)
        self.entry = self.add_entry(width=3, font='Helvetica 15 bold', x=193, y=227)
        self.entry.delete(0, tk.END)
        self.entry.insert(0, "1")
        self.add_button("►", lambda: self.update_entry(True), font='Helvetica 25', height=1, width=1, x=255, y=215)
        self.add_button("◄", lambda: self.update_entry(False), font='Helvetica 25', height=1, width=1, x=115, y=215)
        self.add_button("OK", self.validate_entry, font='Helvetica 14 bold', height=2, width=2, x=185, y=275)

    def get_current_entry_value(self) -> Optional[int]:
        if self.entry.get().isdigit() and int(self.entry.get()) > 0:
            return int(self.entry.get())
        return None

    def validate_entry(self):
        current = self.get_current_entry_value()
        if current is None:
            self.entry.delete(0, tk.END)
            self.entry.insert(0, str(1))
        else:
            self.future.set_result(current)
            self.gui.destroy()

    def update_entry(self, add: bool):
        current = self.get_current_entry_value()
        if current is None:
            current = 1
        else:
            current += 1 if add else -1
        self.entry.delete(0, tk.END)
        self.entry.insert(0, str(current))

    def get_future(self) -> Future[Optional[int]]:
        return self.future


class UserProperties(AbstractUI):
    def __init__(self, main: MainGUI, rfid: RFIDReader, is_creation: bool,
                 user: User):
        super().__init__(main, "Add user" if is_creation else "Update user", 650, 350)
        self.rfid = rfid
        self.user = user
        self.entries = []
        self.add_label("Enter your data" if is_creation else "Please update your data", font='Helvetica 16 bold',
                       fg='#c9a589')
        # === First column
        self.add_label("Name*", font='Helvetica 12 bold italic', x=40, y=50)
        self.entries.append(self.add_entry(value=user.name, width=20, font='Helvetica 12', focus=True, x=40, y=70))
        self.add_label("Surname*", font='Helvetica 12 bold italic', x=40, y=100)
        self.entries.append(self.add_entry(value=user.surname, width=20, font='Helvetica 12', x=40, y=120))
        self.add_label("Nickname", font='Helvetica 12 bold italic', x=40, y=150)
        self.entries.append(self.add_entry(value=user.nickname, width=20, font='Helvetica 12', x=40, y=170))
        self.add_label("Cascad username", font='Helvetica 12 bold italic', x=40, y=200)
        self.entries.append(self.add_entry(value=user.cascad_username, width=20, font='Helvetica 12', x=40, y=220))
        # === Second column
        self.add_label("E-mail address*", font='Helvetica 12 bold italic', x=250, y=50)
        self.entries.append(self.add_entry(value=user.mail, width=35, font='Helvetica 12', x=250, y=70))
        self.add_label("Password" + ("*" if user.passcode is None else ""), font='Helvetica 12 bold italic', x=250,
                       y=100)
        if user.passcode is None:
            self.entries.append(self.add_entry(width=20, font='Helvetica 12', x=250, y=120))
        else:
            self.entries.append(self.add_entry(width=20, font='Helvetica 12', suggestion="Already created",
                                               x=250, y=120))
        self.add_label("Date of departure* (Permanent: put far in the future)", font='Helvetica 12 bold italic',
                       x=250, y=150)
        date_str = user.date_of_departure.strftime("%Y/%m/%d") if user.date_of_departure is not None else None
        self.entries.append(self.add_entry(value=date_str, width=20, font='Helvetica 12',
                                           suggestion="YYYY/MM/DD", x=250, y=170))
        self.add_label("Swipe your ENSTA badge or a RFID tag", font='Helvetica 12 bold italic', x=250, y=200)
        self.badge_lbl = self.add_label(user.id_badge, width=35, font='Helvetica 12',
                                        borderwidth=1, highlightthickness=1, x=250, y=220)
        self.card_future = rfid.get_rfid()
        self.card_future.add_done_callback(self.read_card_callback)
        self.add_label("Required fields are marked with an *", font='Helvetica 10 italic', fg='#c9a589', x=220, y=255)
        self.add_button("OK", self.submit_callback, font='Helvetica 16 bold', height=2, width=4, x=290, y=280)

    def read_card_callback(self, f: Future[str]):
        if not self.future.done():  # check if the windows is still open
            self.badge_lbl.config(text=f.result())
            self.card_future = self.rfid.get_rfid()
            self.card_future.add_done_callback(self.read_card_callback)

    def submit_callback(self):
        self.user.name = self.entries[0].get()
        self.user.surname = self.entries[1].get()
        self.user.nickname = self.entries[2].get() if len(self.entries[2].get()) > 0 else None
        self.user.cascad_username = self.entries[3].get() if len(self.entries[3].get()) > 0 else None
        self.user.mail = self.entries[4].get()
        if self.user.passcode is None or self.entries[5].cget("fg") == 'black':
            passcode = self.entries[5].get()
            self.user.passcode = bcrypt.hashpw(self.entries[5].get().encode(),
                                               bcrypt.gensalt()).decode() if len(passcode) >= 4 else None
        self.user.date_of_departure = None
        try:
            self.user.date_of_departure = (dt.strptime(self.entries[6].get(), "%Y/%m/%d")
                                           .replace(tzinfo=timezone.utc))
        except:
            pass
        self.user.id_badge = self.badge_lbl.cget("text") if len(self.badge_lbl.cget("text")) > 0 else None
        self.future.set_result(self.user)
        self.gui.destroy()

    def get_future(self) -> Future[Optional[User]]:
        return self.future


class BrewCoffee(AbstractUI):
    def __init__(self, main: MainGUI, status: str,
                 beans_q: int, water_v: int,
                 with_arrows: bool = False):
        super().__init__(main, "Brew a coffee", 8 * 60 + 2 * 60 + 170, 450)
        self.gui_status: Literal["req", "wt_fb", "brew", "ack"] = "req"

        self.top_label = self.add_label("What coffee would you like?", font='Helvetica 22 bold', pady=None, fill=None)
        self.debug_label = self.add_label(status, font='Helvetica 12', fg='#c9a589', x=0, y=420, fill=None)

        self.req_coffee_bean = beans_q
        self.req_water_volume = water_v
        self.with_arrows = with_arrows

        self.coffee_icon = None
        self.coffee_icon_gray = None
        self.presets_rect = None
        self.coffee_bean_rect = None
        self.coffee_bean_btns = None
        self.water_volume_rect = None
        self.water_volume_scale = None
        self.request_future = None
        self.submit_btn = None
        self.request_ui()

        self.progress_label = None
        self.received_jura_cb = False
        self.brew_sent_with_success = False
        self.curr_water_volume = 0.
        self.progress_bar = None
        self.closing_delay = 5
        self.closing_label = None

    def request_ui(self):
        self.coffee_icon = ImageTk.PhotoImage(Image.open(os.path.join(os.path.dirname(media.__file__),
                                                                      "coffee_icon.png")).resize((50, 50)))
        self.coffee_icon_gray = ImageTk.PhotoImage(Image.open(os.path.join(os.path.dirname(media.__file__),
                                                                           "coffee_icon_gray.png")).resize((50, 50)))

        # ==== PRESETS
        self.presets_rect = tk.LabelFrame(self.gui, text="Presets", font='Helvetica 12',
                                          bg="#754c24", fg="white", relief='groove')
        self.presets_rect.place(x=70, y=35, width=8 * 60 + 2 * 60 + 2 * 15, height=105)

        def wrapper_preset_cb(c: int, w: int):
            def _cb():
                self.change_coffee_bean(c)
                self.change_water_volume(w)

            return _cb

        self.add_button("Expresso", wrapper_preset_cb(6, 45), gui=self.presets_rect,
                        x=15, y=10, width=15, height=2)
        self.add_button("Coffee", wrapper_preset_cb(4, 100), gui=self.presets_rect,
                        x=225, y=10, width=15, height=2)
        self.add_button("Ristretto", wrapper_preset_cb(2, 150), gui=self.presets_rect,
                        x=435, y=10, width=15, height=2)

        # ==== COFFEE BEAN QUANTITY
        self.coffee_bean_rect = tk.LabelFrame(self.gui, text="Coffee quantity:", font='Helvetica 12',
                                              bg="#754c24", fg="white", relief='groove')
        self.coffee_bean_rect.place(x=70, y=150, width=8 * 60 + 2 * 60 + 2 * 15, height=105)

        self.coffee_bean_btns: list[Button] = []

        def _coffee_cb(idx):
            return lambda: self.change_coffee_bean(idx)

        for i in range(8):
            img = self.coffee_icon if i <= self.req_coffee_bean else self.coffee_icon_gray
            btn = self.add_button(gui=self.coffee_bean_rect, text="a", image=img, callback=_coffee_cb(i),
                                  pady=None, bg="#754c24", fg="#754c24",
                                  highlightthickness=0, bd=0,
                                  x=i * 60 + 60 + 15, y=10, height=60, width=60)
            self.coffee_bean_btns.append(btn)
        if self.with_arrows:
            self.add_button("◄", self.wrapper_left_right(False, True),
                            gui=self.coffee_bean_rect,
                            font='Helvetica 25', height=1, width=1, x=15, y=10)
            self.add_button("►", self.wrapper_left_right(True, True),
                            gui=self.coffee_bean_rect,
                            font='Helvetica 25', height=1, width=1, x=9 * 60 + 9 + 15, y=10)
        # ==== WATER VOLUME
        self.water_volume_rect = tk.LabelFrame(self.gui, text=f"Water volume: {self.req_water_volume} mL",
                                               font='Helvetica 12', bg="#754c24", fg="white", relief='groove')
        self.water_volume_rect.place(x=70, y=265, width=8 * 60 + 2 * 60 + 2 * 15, height=105)
        self.water_volume_scale = Scale(self.water_volume_rect, from_=25, to=240, resolution=5,
                                        variable=tk.IntVar(value=self.req_water_volume),
                                        command=lambda v: self.change_water_volume(int(v)),
                                        bg="#754c24", fg="#c9a589", troughcolor="#c9a589",
                                        tickinterval=15, showvalue=False,
                                        length=8 * 60, width=50, sliderlength=50,
                                        bd=0, highlightthickness=0,
                                        orient="horizontal")
        self.water_volume_scale.place(x=60 + 15, y=10)
        if self.with_arrows:
            self.add_button("◄", self.wrapper_left_right(False, False),
                            gui=self.water_volume_rect,
                            font='Helvetica 25', height=1, width=1, x=15, y=10)
            self.add_button("►", self.wrapper_left_right(True, False),
                            gui=self.water_volume_rect,
                            font='Helvetica 25', height=1, width=1, x=9 * 60 + 9 + 15, y=10)

        # ==== SUBMIT REQUEST
        self.request_future = asyncio.get_event_loop().create_future()
        self.submit_btn = self.add_button("Brew!", self.submit_callback, font='Helvetica 16 bold', width=10, height=2)

    def cleanup_request_ui(self):
        self.presets_rect.place_forget()
        self.coffee_bean_rect.place_forget()
        self.water_volume_rect.place_forget()
        self.submit_btn.pack_forget()

    def change_coffee_bean(self, coffee: int):
        logger.debug(f"User changed coffee to {coffee}")
        self.req_coffee_bean = max(CoffeeMaker.coffee_bean_param[0],
                                   min(CoffeeMaker.coffee_bean_param[2],
                                       coffee)) // CoffeeMaker.coffee_bean_param[3] * CoffeeMaker.coffee_bean_param[3]
        for i in range(8):
            img = self.coffee_icon if i <= self.req_coffee_bean else self.coffee_icon_gray
            self.coffee_bean_btns[i].config(image=img)

    def change_water_volume(self, volume: int):
        logger.debug(f"User changed volume to {volume} mL")
        self.req_water_volume = max(CoffeeMaker.water_volume_param[0],
                                    min(CoffeeMaker.water_volume_param[2],
                                        volume)) // CoffeeMaker.water_volume_param[3] * CoffeeMaker.water_volume_param[
                                    3]
        self.water_volume_scale.set(self.req_water_volume)
        self.water_volume_rect.config(text=f"Water volume: {self.req_water_volume} mL")

    def wrapper_left_right(self, is_more: bool, is_coffee: bool):
        def _cb():
            v = 1 if is_more else -1
            if is_coffee:
                self.change_coffee_bean(self.req_coffee_bean + v)
            else:
                self.change_water_volume(self.req_water_volume + v * 5)

        return _cb

    def submit_callback(self):
        self.request_future.set_result((int(self.req_coffee_bean), int(self.req_water_volume)))
        self.cleanup_request_ui()
        self.progress_ui()

    def progress_ui(self):
        self.gui_status = "wt_fb"
        self.top_label.config(text="Brewing...", pady=75)
        self.progress_label = self.add_label("Contacting the Jura coffee machine...")
        s = ttk.Style()
        s.theme_use('clam')
        s.configure("bg.Horizontal.TProgressbar", foreground='#c9a589', background='#754c24')
        self.progress_bar = ttk.Progressbar(self.gui, style="bg.Horizontal.TProgressbar", orient="horizontal",
                                            length=300, mode="determinate")
        self.progress_bar.pack()

    def ui_before_exit(self):
        self.progress_bar.pack_forget()
        if self.brew_sent_with_success:
            self.top_label.config(text="You're coffee is ready!")
            self.progress_label.config(text="Enjoy :)")
            self.add_label("One coffee will be debited from your account.",
                           font='Helvetica 12 italic', fg='#c9a589')
        else:
            self.top_label.config(text="An unexpected event occurred...")
            self.progress_label.config(text="Please try again...")
            self.add_label("If you continue to get this message, please contact us at cafe.u2is@gmail.com.",
                           font='Helvetica 12 italic')
            self.add_label("Nothing will be debited from your account.", font='Helvetica 13 bold')
            self.closing_delay = 15
        self.closing_label = self.add_label(f"The window will close in {self.closing_delay} seconds...",
                                            font='Helvetica 12 italic',
                                            fg="#c9a589", pady=20)

    def jura_brew_cb(self, success: bool):
        self.received_jura_cb = True
        self.brew_sent_with_success = success

    async def update(self, coffee_maker: CoffeeMaker):
        while not self.received_jura_cb:
            if coffee_maker.get_last_status().maker_status == MakerStatus.BREWING:
                if coffee_maker.get_last_status().water_volume == 0:
                    self.gui_status = "ack"
                    self.progress_label.config(text=f"Grinding the coffee beans...")
                else:
                    self.gui_status = "brew"
                    self.progress_label.config(text=f"Pumping the water...")
                    self.curr_water_volume = max(self.curr_water_volume, coffee_maker.get_last_status().water_volume)
                    self.progress_bar.config(value=self.curr_water_volume / self.req_water_volume * 100)
            await asyncio.sleep(1)
        self.ui_before_exit()

    def get_request(self) -> Future[Optional[Tuple[int, int]]]:
        return self.request_future

    async def get_future_with_autoclosing(self) -> Future[Optional[bool]]:
        for i in range(self.closing_delay, -1, -1):
            if self.future.done():
                break
            self.closing_label.config(text=f"The window will close in {i} seconds...")
            self.gui.update()
            await asyncio.sleep(1)
        if not self.future.done():
            self.future.set_result(None)
        self.gui.destroy()
        return self.get_future()

    def get_future(self) -> Future[Optional[bool]]:
        return self.future


class AskPassword(AbstractUI):
    def __init__(self, main: MainGUI, rfid: RFIDReader, user: User):
        super().__init__(main, "Login", 320, 250)
        self.rfid = rfid
        self.add_label(f"Hello {user}!", font='Helvetica 22 bold')
        self.add_label("Please enter your password", font='Helvetica 15', fg='#c9a589', pady=None, fill=None)
        self.password = self.add_entry(width=20, font='Helvetica 12', focus=True)
        self.card_future = rfid.get_rfid()
        self.card_future.add_done_callback(self.read_card_callback)
        self.add_button("OK", self.submit_callback, font='Helvetica 16 bold')

    def read_card_callback(self, f: Future[str]):
        if not self.future.done():  # check if the windows is still open height=2, width=4
            self.future.set_result((False, f.result()))
            self.gui.destroy()

    def submit_callback(self):
        password = self.password.get()
        self.future.set_result((True, password))
        self.gui.destroy()

    def get_future(self) -> Future[Optional[Tuple[bool, str]]]:
        return self.future


class AdminStatus(AbstractUI):
    def __init__(self, main: MainGUI, last_coffees: list[Tuple[User, Purchase]]):
        super().__init__(main, "Admin status", 220, 480, 0, 0)
        for last_coffee in last_coffees:
            name = str(last_coffee[0])
            if len(name) > 19:
                name = name[:18] + "..."
            self.add_label(f"{name} {last_coffee[1].date.strftime('%d %H:%M')}"
                           f" {last_coffee[1].nb_coffee}",
                           font="Helvetica 10", pady=0, justify='left')

    def close(self):
        self.future.set_result(None)
        self.gui.destroy()

    def get_future(self) -> Future[None]:
        return self.future


class MainGUI:

    def __init__(self, callback: Callable[[], None], coffee_price: float):
        self.opened_popup = []
        self.tk = tk.Tk()
        self.tk.geometry('800x480')
        self.tk.title('My wonderful coffee app')
        self.tk["bg"] = '#754c24'  # background color
        self.tk.resizable(height=False, width=False)

        # Use fullscreen but bind an escape key to window destruction to escape fullscreen
        self.tk.attributes("-fullscreen", True)
        self.tk.bind("<Escape>", lambda e: self.tk.destroy())

        # Place the text label on the window, 10 pixels from the top, and fill the window on x
        txt_lbl1 = tk.Label(self.tk, text="You should take a break...",
                            font='Helvetica 22 bold', fg="white", bg='#754c24')
        txt_lbl1.pack(side="top", pady=10, fill='x')

        # Add coffee price
        txt_lbl2 = tk.Label(self.tk, text=f"Badge for a coffee ({coffee_price:.2f} €)",
                            font='Helvetica 16 bold', fg='#c9a589', bg='#754c24')
        txt_lbl2.pack(side="top", fill='x')

        # Button label to manually check identity
        bt_lbl = tk.Button(self.tk, text="Can't read my badge ?", font='Helvetica 15 bold', fg='#5b3719',
                           bg='#c9a589', height=2, width=24,
                           command=callback)
        bt_lbl.pack(side="bottom", pady=20)

        # Add cup gif, To hide border, set borderwidth and highlightthickness to 0
        lbl = ImageLabel(self.tk, borderwidth=0, highlightthickness=0)
        lbl.pack()
        lbl.load(os.path.join(os.path.dirname(media.__file__), "cup.gif"))


class ImageLabel(tk.Label):
    """ A class for gif animation in image label that inherits from tk Labels """

    def load(self, im: str | Image):
        if isinstance(im, str):  # if image im is a string
            im = Image.open(im)
        self.loc = 0
        self.frames = []

        try:
            for i in count(1):
                w, h = im.size
                upper = h / 4
                lower = 3 * h / 4
                crop_im = im.crop([1, upper, w - 1, lower])
                img = ImageTk.PhotoImage(crop_im)
                self.frames.append(img)
                im.seek(i)
        except EOFError:
            pass

        try:
            self.delay = im.info['duration']
        except BaseException:
            self.delay = 100

        if len(self.frames) == 1:
            self.config(image=self.frames[0])
        else:
            self.next_frame()

    def unload(self):
        self.config(image="")
        self.frames = None

    def next_frame(self):
        if self.frames:
            self.loc += 1
            self.loc %= len(self.frames)
            self.config(image=self.frames[self.loc])
            self.after(self.delay, self.next_frame)


def show_gui(path: str, price: float):
    rfid = RFIDReader(True)
    db = Database(path, True, price)
    users = db.search_by_name("ale")
    gui = MainGUI(lambda: None, 0.25)

    async def wrapper(entity, **args):
        return await entity(**args).get_future()

    async def tk_loop():
        loop = asyncio.get_event_loop()
        asyncio.set_event_loop(loop)

        loop.create_task(wrapper(ManualEntry, main=gui, search_user=db.search_by_name))
        loop.create_task(wrapper(GeneralUI, main=gui, title="Sorry!",
                                 w=200, h=250,
                                 sub_text="I could not find you",
                                 button_one="Try again",
                                 button_two="Add me"))
        loop.create_task(wrapper(GeneralUI, main=gui, title="Sorry!",
                                 w=350, h=290,
                                 sub_text="I could not find you",
                                 main_text="Former user with new badge?",
                                 button_one="Synchronize",
                                 button_two="Add me"))
        loop.create_task(wrapper(GeneralUI, main=gui, title=f"Thank you {users[0]}!",
                                 w=320, h=230,
                                 sub_text="Your balance is now",
                                 main_text=f"{-users[0].get_user_balance()} €",
                                 should_close_in_5=True))
        loop.create_task(wrapper(UserMenu, main=gui, user=users[0]))
        loop.create_task(wrapper(UserProperties, main=gui, rfid=rfid, is_creation=False, user=users[0]))
        loop.create_task(wrapper(BrewCoffee, main=gui, status="status", beans_q=2, water_v=80))

        while True:
            gui.tk.update()
            await asyncio.sleep(1 / 60)

    asyncio.run(tk_loop())
