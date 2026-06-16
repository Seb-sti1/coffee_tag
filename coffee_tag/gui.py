from __future__ import annotations

import asyncio
import importlib
import logging
import os
import random
import time
import tkinter as tk
import unicodedata
from asyncio import Future
from datetime import datetime as dt, timezone
from enum import Enum
from itertools import count  # Islice for list iteration not starting at 0
from tkinter import Button, Scale
from tkinter import ttk
from typing import Tuple, Optional, Callable, Literal, List

import bcrypt
from PIL import Image, ImageTk
from juracoffeemachine import JuraProtocol, BrewingStatus, JuraCommand
from juracoffeemachine.coffee_machine import CoffeeMakerResult, BrewingStage, CoffeeMaker

from coffee_tag import media
from coffee_tag.config import Config
from coffee_tag.database import User, Database, Purchase
from coffee_tag.rfid import RFIDReader

logger = logging.getLogger(__name__)

WHITE = 'white'
LIGHT_BROWN = '#c9a589'
BROWN = '#754c24'
DARK_BROWN = '#5b3719'


class AbstractUI:

    def __init__(self, main: MainGUI, title: str, w: int, h: int,
                 border: int = 3, x: int = None, y: int = None):
        self.future = asyncio.get_event_loop().create_future()
        self.main = main
        self.w = w
        self.h = h
        self.x = main.tk.winfo_rootx() + (main.tk.winfo_width() - w) // 2 if x is None else x
        self.y = main.tk.winfo_rooty() + (main.tk.winfo_height() - h) // 2 if y is None else y
        # set up the new popup
        self.gui = tk.Toplevel(main.tk)
        self.gui['bg'] = LIGHT_BROWN
        self.gui.protocol("WM_DELETE_WINDOW",
                          lambda: [self.future.set_result(None), self.on_closing(), self.gui.destroy()])
        self.gui.transient(main.tk)
        self.gui.grab_set()
        self.gui.overrideredirect(True)
        self.gui.geometry(f"{w}x{h}+{self.x}+{self.y}")
        self.gui.title(title)
        self.gui.resizable(height=False, width=False)
        # create the border by adding a frame inside the toplevel gui
        self.content = tk.Frame(self.gui, bg=BROWN)
        self.content.place(x=border, y=border,
                           width=self.w - 2 * border,
                           height=self.h - 2 * border)
        self.close_btn = None
        self.close_btn = self.add_button("X",
                                         lambda: [self.future.set_result(None), self.on_closing(), self.gui.destroy()],
                                         x=self.w - 60, y=3, px_width=50, px_height=50)
        main.opened_popup.append(self)

    def is_opened(self) -> bool:
        return self.gui.winfo_exists()

    def on_closing(self):
        """
        Abstract on_closing method that can be overwritten
        """
        pass

    def add_label(self, text: str, **kwargs) -> tk.Label:
        defaults = {"font": "Helvetica 14", "fg": WHITE, "bg": BROWN,
                    "justify": "center", "side": "top", "pady": 10, "fill": "x", "x": 0,
                    "wraplength": self.w - 20, "text": text, "gui": self.content}
        exclude_keys = ["x", "y", "side", "pady", "fill", "gui"]
        kwargs = {**defaults, **kwargs}
        lbl = tk.Label(kwargs["gui"], **{k: kwargs[k] for k in kwargs.keys() if k not in exclude_keys})
        if "x" in kwargs and "y" in kwargs:
            lbl.place(x=kwargs["x"], y=kwargs["y"])
        else:
            lbl.pack(side=kwargs["side"], pady=kwargs["pady"], fill=kwargs["fill"])
        self.close_btn.lift()
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

        entry = tk.Entry(self.content, font=font, textvariable=text_var, width=width)

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
        self.close_btn.lift()
        return entry

    def add_button(self, text: Optional[str], callback: Callable, **kwargs) -> tk.Button:
        font = kwargs["font"] if "font" in kwargs else "Helvetica 14"
        fg = kwargs["fg"] if "fg" in kwargs else DARK_BROWN
        bg = kwargs["bg"] if "bg" in kwargs else LIGHT_BROWN
        height = kwargs["height"] if "height" in kwargs else 3
        px_height = kwargs["px_height"] if "px_height" in kwargs else None
        width = kwargs["width"] if "width" in kwargs else 15
        px_width = kwargs["px_width"] if "px_width" in kwargs else None
        side = kwargs["side"] if "side" in kwargs else "bottom"
        pady = kwargs["pady"] if "pady" in kwargs else 10
        image = kwargs["image"] if "image" in kwargs else None
        gui = kwargs["gui"] if "gui" in kwargs else self.content
        highlightthickness = kwargs["highlightthickness"] if "highlightthickness" in kwargs else None
        bd = kwargs["bd"] if "bd" in kwargs else None
        btn = tk.Button(gui, text=text, font=font, fg=fg, bg=bg, command=callback,
                        height=height, width=width, image=image,
                        highlightthickness=highlightthickness, bd=bd)
        if "x" in kwargs and "y" in kwargs:
            btn.place(x=kwargs["x"], y=kwargs["y"], width=px_width, height=px_height)
        else:
            btn.pack(side=side, pady=pady)
        if self.close_btn is not None:
            self.close_btn.lift()
        return btn


class ManualEntry(AbstractUI):

    def __init__(self, main: MainGUI, search_user: Callable[[str], list[User]]):
        super().__init__(main, "Manual identification", 650, 400)
        self.grid_size = (200, 60)  # shift in x and y
        self.grid_counts = (3, 5)  # number of columns and rows
        self.search_user = search_user
        self.add_label("What is your name ?", font="Helvetica 14 bold italic")
        self.entry = self.add_entry(on_text_change=self.on_text_change, focus=True)
        self.add_button("Create new user", self.btn_callback, x=10, y=25, width=14, height=2)
        self.label = self.add_label("Type at least one character.", font="Helvetica 12 italic", fg=LIGHT_BROWN)
        self.choices: list[tk.Button] = []

    def on_text_change(self, text_var: tk.StringVar):
        for b in self.choices:
            b.place_forget()
        self.choices = []
        self.gui.update()
        if len(text_var.get()) == 0:
            if self.label is None:
                self.label = self.add_label("Type at least one character.", font="Helvetica 12 italic", fg=LIGHT_BROWN)
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
        self.add_label(title, font='Helvetica 22 bold', wraplength=self.w - 140)
        if sub_text and not sub_after_main:
            self.add_label(sub_text, fg=LIGHT_BROWN, font='Helvetica 12 bold italic', pady=None)
        if main_text:
            self.add_label(main_text, font='Helvetica 16 bold')
        if sub_text and sub_after_main:
            self.add_label(sub_text, fg=LIGHT_BROWN, font='Helvetica 12 bold italic', pady=None)
        if button_one:
            self.add_button(button_one, self.btn_one_callback, side="top", font='Helvetica 12 bold')
        if button_two:
            self.add_button(button_two, self.btn_two_callback, side="top", font='Helvetica 12 bold')
        if should_close_in_5:
            self.closing_lbl = self.add_label("The window will close in 5 seconds...",
                                              font='Helvetica 12 bold italic',
                                              fg=LIGHT_BROWN)

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
        super().__init__(main, "Your account", 490, 370)
        self.add_label(f"Hello {user}!", font='Helvetica 22 bold', wraplength=self.w - 140)
        self.add_label("Your balance is currently", font='Helvetica 15', fg=LIGHT_BROWN,
                       pady=None, fill=None)
        self.add_label(f"{-user.get_user_balance()} €", font='Helvetica 22 bold')
        last_coffee = user.get_last_coffee()
        if last_coffee is not None:
            self.add_label(f"Your last coffee was {str(dt.now(timezone.utc) - last_coffee.date).split('.')[0]} ago.",
                           font='Helvetica 15', fg=LIGHT_BROWN, pady=None)
        self.add_label("How many coffees will you take ?", font='Helvetica 15', fg=LIGHT_BROWN, pady=None, fill=None)
        self.entry = self.add_entry(width=3, font='Helvetica 15 bold', x=228, y=237)
        self.entry.delete(0, tk.END)
        self.entry.insert(0, "1")
        self.add_button("►", lambda: self.update_entry(True), font='Helvetica 25', height=1, width=1, x=290, y=225)
        self.add_button("◄", lambda: self.update_entry(False), font='Helvetica 25', height=1, width=1, x=150, y=225)
        self.add_button("OK", self.validate_entry, font='Helvetica 14 bold', height=2, width=2, x=220, y=285)

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
                       fg=LIGHT_BROWN)
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
        self.initial_id_badge = user.id_badge
        self.add_label("Swipe your ENSTA badge or a RFID tag", font='Helvetica 12 bold italic', x=250, y=200)
        self.badge_lbl = self.add_label(self.initial_id_badge, width=33, font='Helvetica 12',
                                        borderwidth=1, highlightthickness=1, x=250, y=220)
        self.rollback_image = ImageTk.PhotoImage(Image.open(os.path.join(os.path.dirname(media.__file__),
                                                                         "rollback.png")).resize((30, 30)))
        self.add_button(text="", image=self.rollback_image, x=560, y=214, px_width=30, px_height=30,
                        callback=lambda: self.badge_lbl.config(text=self.initial_id_badge))
        self.clear_image = ImageTk.PhotoImage(Image.open(os.path.join(os.path.dirname(media.__file__),
                                                                      "clear.png")).resize((30, 30)))
        self.add_button(text="", image=self.clear_image, x=605, y=214, px_width=30, px_height=30,
                        callback=lambda: self.badge_lbl.config(text=""))
        self.card_future = rfid.get_rfid()
        self.card_future.add_done_callback(self.read_card_callback)
        self.add_label("Required fields are marked with an *", font='Helvetica 10 italic', fg=LIGHT_BROWN, x=220, y=255)
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


class Meme(AbstractUI):

    def __init__(self, main: MainGUI, memes: List[str]):
        super().__init__(main, "Meme", 800, 480, x=0, y=0)
        self.content.place_forget()
        self.close_btn.place_forget()
        self.closing_delay = 15
        self.gui.attributes("-fullscreen", True)

        self.canvas = tk.Canvas(self.gui, width=800, height=480, highlightthickness=0)
        self.canvas.pack()
        bg = Image.open(os.path.join(os.path.dirname(media.__file__), "bg.png"))
        self.tk_bg = ImageTk.PhotoImage(bg)
        self.bg_obj = self.canvas.create_image(bg.width, 0, image=self.tk_bg, anchor='nw')
        self.canvas.coords(self.bg_obj, 0, 0)

        self.img = Image.open(random.choice(memes))
        self.tk_img = ImageTk.PhotoImage(self.img)
        self.image_obj = self.canvas.create_image(self.img.width, 0, image=self.tk_img, anchor='nw')

    async def get_future_with_autoclosing(self) -> Optional[bool]:
        for x in range(self.img.width, -self.img.width, - (2 * self.img.width + 1) // 150):
            if self.future.done():
                break
            self.canvas.coords(self.image_obj, x, 0)
            self.gui.update()
            await asyncio.sleep(0.1)

        if not self.future.done():
            self.future.set_result(None)
        self.gui.destroy()
        return await self.get_future()

    def get_future(self) -> Future[Optional[bool]]:
        return self.future


class BrewCoffee(AbstractUI):
    class Status(Enum):
        WAITING_CONNECTION = 0
        JURA_STATUS_OK = 1
        JURA_STATUS_OK_WITH_NO_COFFEE_WARNING = 2
        JURA_STATUS_NOT_OK = 3
        PENDING_USER_REQUEST = 4
        WAITING_JURA_ACKNOWLEDGMENT = 5
        JURA_RECEIVED_ACKNOWLEDGMENT = 6
        JURA_PUMPING_WATER = 7

    ERROR_LBL = {
        None: "An unknown error occurred. Please contact an admin.",
        CoffeeMakerResult.CANNOT_COMMUNICATE: "Error can't communicate with jura. If it is off, turn it on.",
        CoffeeMakerResult.CANNOT_FETCH_HZ: "Could not fetch Jura's status.",
        CoffeeMakerResult.CANNOT_FETCH_GROUNDS_TANK: "Could not fetch Jura's status.",
        CoffeeMakerResult.CANNOT_SET_PARAM: "Could not send your order.",
        CoffeeMakerResult.CANNOT_PRESS_BTN: "Could not send your order.",
        CoffeeMakerResult.SLEEPING: "The Jura is off. Please turn it on.",
        CoffeeMakerResult.WATER_TANK_MISSING: "Please refill/put the water tank back.",
        CoffeeMakerResult.DRAINING_TRAY_MISSING: "The draining tank is absent. Please put it back.",
        CoffeeMakerResult.DRAINING_TRAY_FULL: "The draining tank is full. Please empty it.",
        CoffeeMakerResult.GROUNDS_TANK_FULL: "The coffee grounds tank is full. Please empty it.",
        CoffeeMakerResult.MISSING_COFFEE: "There is no coffee left in the machine. Please refill it.",
        CoffeeMakerResult.CANNOT_CONFIRM_SUCCESSFUL_COFFEE: "It appears the Jura could not brewed your coffee.",
        CoffeeMakerResult.WARMING_UP: "The Jura is warming up! Please check Jura's screen.",
        CoffeeMakerResult.BOWL_MOVING: "The Jura seems to be cleaning! Please check Jura's screen.",
    }

    def __init__(self, main: MainGUI,
                 user: User, price: float,
                 get_brewing_status: Callable[[], BrewingStatus],
                 beans_q: int, water_v: int):
        super().__init__(main, "Brew a coffee", 800, 480)
        self.gui_status: BrewCoffee.Status = BrewCoffee.Status.WAITING_CONNECTION
        self.jura_feedback: Optional[CoffeeMakerResult] = None
        self.user = user
        self.price = price
        self.get_brewing_status = get_brewing_status
        self.req_coffee_bean = beans_q
        self.req_water_volume = water_v

        # TOP PART OF THE GUI
        self.add_label(f"Hello {user}!", font='Helvetica 22 bold', pady=3, fill=None)
        self.add_label(f"Your balance is now", fg=LIGHT_BROWN,
                       font='Helvetica 15 bold italic', x=300, y=60, fill=None)
        self.balance_lbl = self.add_label(f"{-user.get_user_balance()} €",
                                          font='Helvetica 15 bold', x=360, y=100, fill=None)
        last_coffee = user.get_last_coffee()
        if last_coffee is not None:
            self.add_label(f"Your last coffee was {str(dt.now(timezone.utc) - last_coffee.date).split('.')[0]} ago.",
                           fg=LIGHT_BROWN, x=225, y=125)
        self.settings_icon = ImageTk.PhotoImage(Image.open(os.path.join(os.path.dirname(media.__file__),
                                                                        "settings.png")).resize((50, 50)))
        self.settings_btn = self.add_button("", lambda: [self.future.set_result("settings"),
                                                         self.on_closing(),
                                                         self.gui.destroy()],
                                            image=self.settings_icon,
                                            x=5, y=5, px_width=50, px_height=50)
        self.admin_btn = None
        self.feed_btn = None
        self.jura_btn = None
        if user.is_maintainer():
            self.admin_icon = ImageTk.PhotoImage(Image.open(os.path.join(os.path.dirname(media.__file__),
                                                                         "admin.png")).resize((50, 50)))
            self.admin_btn = self.add_button("", lambda: [self.future.set_result("admin"),
                                                          self.on_closing(),
                                                          self.gui.destroy()],
                                             image=self.admin_icon,
                                             x=740, y=100, px_width=50, px_height=50)
            if not user.is_owner():
                self.admin_btn.config(state="disabled")
            self.feed_btn = self.add_button("feed", lambda: [self.future.set_result("feed"),
                                                             self.on_closing(),
                                                             self.gui.destroy()],
                                            x=680, y=100, px_width=50, px_height=50)
            if not user.is_owner():
                self.admin_btn.config(state="disabled")
            self.jura_btn = self.add_button("jura btn", lambda: [self.future.set_result("jura_btn"),
                                                                 self.on_closing(),
                                                                 self.gui.destroy()],
                                            x=620, y=100, px_width=50, px_height=50)
            self.maintenance_btn = self.add_button("maintenance",
                                                   lambda: [self.future.set_result("maintenance"),
                                                            self.on_closing(),
                                                            self.gui.destroy()],
                                                   x=560, y=100, px_width=50, px_height=50)

        self.debug_label = self.add_label("", font='Helvetica 12', fg=LIGHT_BROWN, x=0, y=120, fill=None)

        self.order_rect = tk.LabelFrame(self.content, text="Order a coffee", font='Helvetica 12',
                                        bg=BROWN, fg=WHITE, relief='groove')
        self.order_rect.place(x=5, y=150, width=800 - 17, height=320)

        # CHECK STATUS UI
        self.can_brew = False
        self.title_order_rect = None
        self.progress_label = None
        self.retry_btn = None
        self.continue_btn = None

        # ORDER A COFFEE UI
        self.presets_rect = None
        self.coffee_icon = None
        self.coffee_icon_gray = None
        self.coffee_bean_rect = None
        self.coffee_bean_btns = None
        self.water_volume_rect = None
        self.water_volume_scale = None
        self.submit_btn = None

        # PROGRESS UI
        self.brew_sent_with_success = False
        self.curr_water_volume = 0.
        self.progress_bar = None
        self.stop_btn = None

        # EXIT UI
        self.closing_delay = 5
        self.closing_label = None

        # enable first ui
        self.checking_status_ui()

    # ================================ CHECKING JURA STATUS UI ================================
    def checking_status_ui(self):
        self.title_order_rect = self.add_label(text="Please wait...", gui=self.order_rect, font='Helvetica 20 bold',
                                               pady=30)
        self.progress_label = self.add_label("Checking if Jura is ready...", gui=self.order_rect)

    def can_brew_sb(self, result: CoffeeMakerResult):
        self.jura_feedback = result
        if self.jura_feedback == CoffeeMakerResult.OK:
            self.gui_status = BrewCoffee.Status.JURA_STATUS_OK
        elif self.jura_feedback == CoffeeMakerResult.MISSING_COFFEE:
            self.gui_status = BrewCoffee.Status.JURA_STATUS_OK_WITH_NO_COFFEE_WARNING
        else:
            self.gui_status = BrewCoffee.Status.JURA_STATUS_NOT_OK

    def cleanup_checking_status_ui(self):
        self.title_order_rect.pack_forget()
        self.title_order_rect = None
        self.progress_label.pack_forget()
        self.progress_label = None

    # ================================ ORDER A COFFEE UI ================================
    def request_ui(self):
        self.gui_status = BrewCoffee.Status.PENDING_USER_REQUEST
        self.coffee_icon = ImageTk.PhotoImage(Image.open(os.path.join(os.path.dirname(media.__file__),
                                                                      "coffee_icon.png")).resize((50, 50)))
        self.coffee_icon_gray = ImageTk.PhotoImage(Image.open(os.path.join(os.path.dirname(media.__file__),
                                                                           "coffee_icon_gray.png")).resize((50, 50)))

        # ==== PRESETS
        self.presets_rect = tk.LabelFrame(self.order_rect, text="Presets", font='Helvetica 12',
                                          bg=BROWN, fg=WHITE, relief='groove')
        self.presets_rect.place(x=5, y=5, width=110, height=290)

        def wrapper_preset_cb(c: int, w: int):
            def _cb():
                self.change_coffee_bean(c)
                self.change_water_volume(w)

            return _cb

        shift = 60
        self.add_button("Ristretto", wrapper_preset_cb(8, 25), gui=self.presets_rect,
                        x=5, y=10, width=6, height=2)
        self.add_button("Expresso", wrapper_preset_cb(6, 45), gui=self.presets_rect,
                        x=5, y=10 + shift * 1, width=6, height=2)
        self.add_button("Coffee", wrapper_preset_cb(4, 100), gui=self.presets_rect,
                        x=5, y=10 + shift * 2, width=6, height=2)
        self.add_button("Special", wrapper_preset_cb(8, 220), gui=self.presets_rect,
                        x=5, y=10 + shift * 3, width=6, height=2)
        # ==== COFFEE BEAN QUANTITY
        self.coffee_bean_rect = tk.LabelFrame(self.order_rect, text="Coffee quantity:", font='Helvetica 12',
                                              bg=BROWN, fg=WHITE, relief='groove')
        self.coffee_bean_rect.place(x=130, y=10, width=8 * 60 + 2 * 60 + 2 * 15, height=105)
        self.coffee_bean_btns: list[Button] = []

        def _coffee_cb(idx):
            return lambda: self.change_coffee_bean(idx)

        for i in range(8):
            img = self.coffee_icon if i < self.req_coffee_bean else self.coffee_icon_gray
            btn = self.add_button(gui=self.coffee_bean_rect, text="a", image=img, callback=_coffee_cb(i + 1),
                                  pady=None, bg=BROWN, fg=BROWN,
                                  highlightthickness=0, bd=0,
                                  x=i * 60 + 60 + 15, y=10, height=60, width=60)
            self.coffee_bean_btns.append(btn)
        # ==== WATER VOLUME
        self.water_volume_rect = tk.LabelFrame(self.order_rect, text=f"Water volume: {self.req_water_volume} mL",
                                               font='Helvetica 12', bg=BROWN, fg=WHITE, relief='groove')
        self.water_volume_rect.place(x=130, y=125, width=8 * 60 + 2 * 60 + 2 * 15, height=105)
        self.water_volume_scale = Scale(self.water_volume_rect, from_=25, to=240, resolution=5,
                                        variable=tk.IntVar(value=self.req_water_volume),
                                        command=lambda v: self.change_water_volume(int(v)),
                                        bg=BROWN, fg=LIGHT_BROWN, troughcolor=LIGHT_BROWN,
                                        tickinterval=15, showvalue=False,
                                        length=8 * 60, width=50, sliderlength=50,
                                        bd=0, highlightthickness=0,
                                        orient="horizontal")
        self.water_volume_scale.place(x=60 + 15, y=10)

        # ==== SUBMIT REQUEST
        self.submit_btn = self.add_button(f"Brew! ({self.price}€)", self.submit_callback,
                                          gui=self.order_rect,
                                          font='Helvetica 16 bold', width=10, height=2,
                                          x=245 + 121, y=236)

    def cleanup_request_ui(self):
        self.jura_feedback = None
        self.presets_rect.place_forget()
        self.coffee_bean_rect.place_forget()
        self.water_volume_rect.place_forget()
        self.submit_btn.place_forget()

    def change_coffee_bean(self, coffee: int):
        self.req_coffee_bean = (max(JuraProtocol.coffee_param[0],
                                    min(JuraProtocol.coffee_param[2], coffee))
                                // JuraProtocol.coffee_param[3]
                                * JuraProtocol.coffee_param[3])
        for i in range(8):
            img = self.coffee_icon if i < self.req_coffee_bean else self.coffee_icon_gray
            self.coffee_bean_btns[i].config(image=img)

    def change_water_volume(self, volume: int):
        self.req_water_volume = (max(JuraProtocol.water_param[0],
                                     min(JuraProtocol.water_param[2], volume))
                                 // JuraProtocol.water_param[3]
                                 * JuraProtocol.water_param[3])
        self.water_volume_scale.set(self.req_water_volume)
        self.water_volume_rect.config(text=f"Water volume: {self.req_water_volume} mL")

    def submit_callback(self):
        self.settings_btn.config(state="disabled")
        if self.admin_btn is not None:
            self.admin_btn.config(state="disabled")
        if self.feed_btn is not None:
            self.feed_btn.config(state="disabled")
        if self.jura_btn is not None:
            self.jura_btn.config(state="disabled")
        if self.jura_btn is not None:
            self.maintenance_btn.config(state="disabled")
        self.close_btn.config(state="disabled")
        self.future.set_result((int(self.req_coffee_bean), int(self.req_water_volume)))
        self.cleanup_request_ui()
        self.progress_ui()

    async def get_request(self) -> Optional[Tuple[int, int]
                                            | Literal["settings", "admin", "retry", "feed", "jura_btn", "maintenance"]]:
        # reset future for the request
        self.future = asyncio.get_event_loop().create_future()
        last_gui_status = None
        while not self.future.done():
            if last_gui_status != self.gui_status:
                if self.gui_status == BrewCoffee.Status.JURA_STATUS_OK:
                    self.cleanup_checking_status_ui()
                    self.request_ui()
                elif self.gui_status == BrewCoffee.Status.JURA_STATUS_OK_WITH_NO_COFFEE_WARNING:
                    self.title_order_rect.config(text="Caution!")
                    self.progress_label.config(
                        text="There was no more coffee for last coffee! Please make sure it was refilled.")
                    self.continue_btn = self.add_button("Continue",
                                                        self.continue_callback,
                                                        gui=self.order_rect)
                    break
                elif self.gui_status == BrewCoffee.Status.JURA_STATUS_NOT_OK:
                    self.title_order_rect.config(text="Oops...")
                    self.progress_label.config(text=self.ERROR_LBL.get(self.jura_feedback, "Unknown error"))
                    self.retry_btn = self.add_button("Retry",
                                                     self.retry_callback,
                                                     gui=self.order_rect)
                    break
            await asyncio.sleep(0.3)
        return await self.future

    def continue_callback(self):
        self.gui_status = BrewCoffee.Status.JURA_STATUS_OK
        self.retry_btn.pack_forget()
        self.retry_btn = None
        self.request_ui()

    def retry_callback(self):
        self.gui_status = BrewCoffee.Status.WAITING_CONNECTION
        self.cleanup_checking_status_ui()
        self.retry_btn.pack_forget()
        self.retry_btn = None
        self.checking_status_ui()
        self.future.set_result("retry")

    # ================================ COFFEE BREWING PROGRESS UI ================================
    def progress_ui(self):
        self.gui_status = BrewCoffee.Status.WAITING_JURA_ACKNOWLEDGMENT
        self.title_order_rect = self.add_label(text="Brewing...", gui=self.order_rect, font='Helvetica 20 bold',
                                               pady=30)
        self.progress_label = self.add_label("Checking if Jura is still ready...", gui=self.order_rect)
        s = ttk.Style()
        s.theme_use('clam')
        s.configure("bg.Horizontal.TProgressbar", foreground=LIGHT_BROWN, background=BROWN)
        self.progress_bar = ttk.Progressbar(self.order_rect, style="bg.Horizontal.TProgressbar", orient="horizontal",
                                            length=300, mode="determinate")
        self.progress_bar.pack()

    def jura_brew_cb(self, result: CoffeeMakerResult):
        self.jura_feedback = result
        self.brew_sent_with_success = result == CoffeeMakerResult.OK

    async def update(self):
        start_time = time.time()
        while self.jura_feedback is None and (time.time() - start_time) < 120:
            status = self.get_brewing_status()
            if status is None:
                continue
            if status.stage in [BrewingStage.SETTING_PARAM, BrewingStage.PRESSING_BTN]:
                self.progress_label.config(text=f"Sending your order...")
            elif status.stage == BrewingStage.BREWING:
                if self.gui_status == BrewCoffee.Status.WAITING_JURA_ACKNOWLEDGMENT:
                    if self.get_brewing_status().water_volume == 0:
                        self.gui_status = BrewCoffee.Status.JURA_RECEIVED_ACKNOWLEDGMENT
                        self.progress_label.config(text=f"Grinding the coffee beans...")
                else:
                    if self.get_brewing_status().water_volume > 0:
                        self.gui_status = BrewCoffee.Status.JURA_PUMPING_WATER
                        self.progress_label.config(text=f"Pumping the water...")
                        self.curr_water_volume = max(self.curr_water_volume, self.get_brewing_status().water_volume)
                        self.progress_bar.config(value=self.curr_water_volume / self.req_water_volume * 100)
            await asyncio.sleep(1)
        self.ui_before_exit()

    # ================================ COFFEE BREWING PROGRESS UI ================================
    def ui_before_exit(self):
        self.progress_bar.pack_forget()
        self.close_btn.config(state="active")
        if self.brew_sent_with_success:
            self.title_order_rect.config(text="You're coffee is ready!")
            self.progress_label.config(text="Enjoy :)")
            self.add_label("One coffee will be debited from your account.",
                           gui=self.order_rect, font='Helvetica 12 italic', fg=LIGHT_BROWN)
            self.balance_lbl.config(text=f"{-self.user.get_user_balance() - self.user.db.coffee_price} €")
        else:
            self.title_order_rect.config(text="Oops...")
            self.progress_label.config(text=self.ERROR_LBL.get(self.jura_feedback, "Unknown error"))
            if self.jura_feedback is None:
                self.add_label("If you continue to get this message, please contact us at cafe.u2is@gmail.com.",
                               gui=self.order_rect, font='Helvetica 12 italic')
            self.add_label("Nothing will be debited from your account.", gui=self.order_rect,
                           font='Helvetica 13 bold')
            self.closing_delay = 15
        self.closing_label = self.add_label(f"The window will close in {self.closing_delay} seconds...",
                                            gui=self.order_rect,
                                            font='Helvetica 12 italic',
                                            fg=LIGHT_BROWN, pady=20)

    async def get_future_with_autoclosing(self) -> Optional[bool]:
        # reset future for the auto closing
        self.future = asyncio.get_event_loop().create_future()
        for i in range(self.closing_delay, -1, -1):
            if self.future.done():
                break
            self.closing_label.config(text=f"The window will close in {i} seconds...")
            self.gui.update()
            await asyncio.sleep(1)
        if not self.future.done():
            self.future.set_result(None)
        self.gui.destroy()
        return await self.get_future()

    def get_future(self) -> Future[Optional[bool]]:
        return self.future


class AskPassword(AbstractUI):
    def __init__(self, main: MainGUI, rfid: RFIDReader, user: User):
        super().__init__(main, "Login", 370, 250)
        self.rfid = rfid
        self.add_label(f"Hello {user}!", font='Helvetica 22 bold')
        self.add_label("Please enter your password", font='Helvetica 15', fg=LIGHT_BROWN, pady=None, fill=None)
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


class AdminGUI(AbstractUI):
    def __init__(self, main: MainGUI, users: Optional[List[User]]):
        super().__init__(main, "Admin GUI", 800, 480)
        users = users if users is not None else []
        self.users = sorted(users, key=lambda u: f"{u.name} {u.surname}")

        self.search_bar = self.add_entry(x=10, y=10, width=30, on_text_change=self.search)
        self.search_txt = ""
        self.search_result = self.users

        self.users_list = tk.Listbox(self.gui)
        self.users_list.place(x=13, y=50, height=480 - 50 - 10, width=303)
        self.users_list.bind("<<ListboxSelect>>", self.show_user)
        self.current_user: Optional[User] = None

        self.info_label = self.add_label("Select a user.", x=320, y=10, justify="left")
        self.add_label("DD/MM/YY HH:MM:SS", x=320, y=180)
        self.add_coffee_entry = self.add_entry(x=320, y=200, width=19)
        self.add_coffee_btn = self.add_button("Add coffee", self.add_coffee, x=520, y=195, width=7, height=1)

        self.coffee_list = tk.Listbox(self.gui)
        self.coffee_list.place(x=320, y=235, height=200, width=300)
        self.coffee_list.bind("<<ListboxSelect>>", self.select_coffee)
        self.coffee_list.config(font=("Courier New", 11))
        self.current_coffee_list: List[Purchase] = []
        self.current_coffee: Optional[Purchase] = None
        self.delete_coffee_btn = self.add_button(f"Delete coffee", self.delete_coffee, x=320, y=435,
                                                 width=27, height=1)

        self.perm_combobox = ttk.Combobox(self.gui, textvariable=tk.StringVar())
        self.perm_combobox['values'] = ('user', 'maintainer', 'owner')
        self.perm_combobox.place(x=320 + 5, y=152, height=25, width=145)
        self.status_combobox = ttk.Combobox(self.gui)
        self.status_combobox['values'] = ('active', 'banned', 'shadow_banned')
        self.status_combobox.place(x=320 + 150 + 10 + 5, y=152, height=25, width=145)
        self.save_btn = self.add_button(f"Save", self.save, x=320 + 2 * 150 + 2 * 10 + 5, y=145,
                                        width=7, height=1)

        self.draw_list()

    def search(self, txt: tk.StringVar):
        self.search_txt = txt.get()
        self.draw_list()

    def reset_btn(self):
        self.add_coffee_btn.config(bg=LIGHT_BROWN)
        self.delete_coffee_btn.config(bg=LIGHT_BROWN)
        self.save_btn.config(bg=LIGHT_BROWN)

    def draw_list(self):
        def normalize(text):
            return ''.join(c for c in unicodedata.normalize('NFD', text) if unicodedata.category(c) != 'Mn').lower()

        self.users_list.delete(0, tk.END)
        self.search_result = list(filter(lambda u: any(map(lambda txt: txt is not None and
                                                                       normalize(self.search_txt) in normalize(txt),
                                                           [u.name, u.surname, u.nickname, u.mail])),
                                         self.users)) if len(self.search_txt) > 0 else self.users
        for user in self.search_result:
            self.users_list.insert(tk.END, f"{user.name} {user.surname}")

    def show_user(self, _):
        self.reset_btn()
        selection = self.users_list.curselection()
        if not selection:
            return
        user = self.search_result[selection[0]]
        self.current_user = user
        departure_str = f"Departure {user.date_of_departure.strftime('%Y/%m/%d')}." if user.date_of_departure is not None else "No date of departure."
        self.info_label.config(text=f"{user.user_id} {user.name} {user.surname} ({user.nickname})\n"
                                    f"{user.mail}.\n"
                                    f"Cascad: {user.cascad_username}. "
                                    f"{'Password set' if user.passcode is not None else 'No password set'}.\n"
                                    f"Badge {user.id_badge}.\n"
                                    f"Balance: {user.get_user_balance()} (init {user.initial_balance}).\n"
                                    f"{departure_str}\n"
                                    f"Preset {user.water_v}ml {user.beans_q} beans.\n")
        self.perm_combobox.set(user.permissions)
        self.status_combobox.set(user.status)
        self.coffee_list.delete(0, tk.END)
        self.current_coffee_list = user.get_coffees()
        for coffee in self.current_coffee_list:
            self.coffee_list.insert(tk.END, f"{coffee.purchase_id:>6} {coffee.nb_coffee} {coffee.price}€ "
                                            f"{coffee.date.strftime('%y/%m/%d %H:%M:%S')}")

    def save(self):
        if self.current_user is None:
            logger.warning(f"Couldn't add coffee manually: no user selected.")
            self.save_btn.config(bg="red")
            return

        self.current_user.permissions = self.perm_combobox.get()
        self.current_user.status = self.status_combobox.get()

        if self.current_user.update(True):
            logger.warning(f"{self.current_user} status/permissions were updated:"
                           f" {self.current_user.permissions}, {self.current_user.status}.")
            self.save_btn.config(bg="green")
        else:
            logger.warning(f"Unknown database error occurred will updating status/permissions.")
            self.save_btn.config(bg="red")

    def add_coffee(self):
        if self.current_user is None:
            self.add_coffee_btn.config(bg="red")
            logger.warning(f"Couldn't add coffee manually: no user selected.")
            return
        try:
            date = dt.strptime(self.add_coffee_entry.get(), "%d/%m/%y %H:%M:%S").replace(tzinfo=timezone.utc)
        except:
            logger.warning(f"Couldn't add coffee manually: can't parse {self.add_coffee_entry.get()}.")
            self.add_coffee_btn.config(bg="red")
            return

        if self.current_user.buy_coffees(1, date):
            logger.warning(f"A coffee was added manually for {self.current_user} at {self.add_coffee_entry.get()}.")
            self.show_user(None)
            self.add_coffee_btn.config(bg="green")
        else:
            logger.warning(f"Unknown database error occurred will adding a coffee manually.")
            self.add_coffee_btn.config(bg="red")

    def select_coffee(self, _):
        self.reset_btn()
        if self.current_user is None:
            self.current_coffee = None
            return
        selection = self.coffee_list.curselection()
        if not selection:
            self.current_coffee = None
            return
        self.current_coffee = self.current_coffee_list[selection[0]]

    def delete_coffee(self):
        if self.current_user is None or self.current_coffee is None:
            logger.warning(f"Can't delete this coffee: no user ({self.current_user})"
                           f" or coffee ({self.current_coffee}) selected.")
            self.delete_coffee_btn.config(bg="red")
            return

        if self.current_user.delete_coffee(self.current_coffee.purchase_id):
            logger.warning(f"A coffee was deleted for {self.current_user}: {self.current_coffee}.")
            self.show_user(None)
            self.delete_coffee_btn.config(bg="green")
        else:
            logger.warning(f"Unknown database error occurred will deleting a coffee.")
            self.delete_coffee_btn.config(bg="red")

    def close(self):
        self.future.set_result(None)
        self.gui.destroy()

    def get_future(self) -> Future[None]:
        return self.future


class AdminFeedGui(AbstractUI):
    def __init__(self, main: MainGUI, new_users: Optional[List[User]],
                 last_coffees: Optional[List[Purchase]]):
        super().__init__(main, "Admin Feed", 800, 480)

        # === Last coffees
        self.coffees = [] if last_coffees is None else last_coffees
        self.coffee_list = tk.Listbox(self.gui)
        self.coffee_list.place(x=13, y=10, height=480 - 50 - 10, width=303)
        self.coffee_list.bind("<<ListboxSelect>>", self.select_coffee)
        self.current_coffee: Optional[Purchase] = None
        self.users_index = {u.user_id: u for u in new_users} if new_users else {}
        self.delete_btn = self.add_button(f"Delete", self.delete_coffee, x=10, y=430,
                                          width=7, height=1)
        self.to_loss_btn = self.add_button(f"To loss", self.coffee_to_loss, x=120, y=430,
                                           width=7, height=1)

        # === New users
        self.users = [] if new_users is None else new_users
        self.users_list = tk.Listbox(self.gui)
        self.users_list.place(x=390, y=10, height=480 - 50 - 10, width=303)
        self.users_list.bind("<<ListboxSelect>>", self.select_user)
        self.current_user: Optional[User] = None

        self.status_combobox = ttk.Combobox(self.gui)
        self.status_combobox['values'] = ('active', 'banned', 'shadow_banned')
        self.status_combobox.place(x=390, y=440, height=25, width=115)
        self.save_btn = self.add_button(f"Save", self.save, x=520, y=430,
                                        width=7, height=1)

        self.draw_list()

    def reset_btn(self):
        self.delete_btn.config(bg=LIGHT_BROWN)
        self.to_loss_btn.config(bg=LIGHT_BROWN)
        self.save_btn.config(bg=LIGHT_BROWN)

    def draw_list(self):
        self.users_list.delete(0, tk.END)
        for user in self.users:
            self.users_list.insert(tk.END, f"{user.name} {user.surname}")
        self.coffee_list.delete(0, tk.END)
        for coffee in self.coffees:
            u = self.users_index.get(coffee.user_id, None)
            self.coffee_list.insert(tk.END, f"{coffee.purchase_id:>6} {coffee.nb_coffee} {coffee.price}€ "
                                            f"{coffee.date.strftime('%y/%m/%d %H:%M:%S')} {u.name} {u.surname}")

    def select_user(self, _):
        selection: Optional[Tuple[int]] = self.users_list.curselection()
        if not selection:
            return
        user = self.users[selection[0]]
        self.current_user = user
        self.status_combobox.set(user.status)
        self.reset_btn()

    def save(self):
        if self.current_user is None:
            logger.warning(f"Couldn't update user manually: no user selected.")
            self.save_btn.config(bg="red")
            return
        self.current_user.status = self.status_combobox.get()
        if self.current_user.update(True):
            logger.warning(f"{self.current_user} status/permissions were updated:"
                           f" {self.current_user.permissions}, {self.current_user.status}.")
            self.save_btn.config(bg="green")
        else:
            logger.warning(f"Unknown database error occurred will updating status/permissions.")
            self.save_btn.config(bg="red")

    def select_coffee(self, _):
        selection: Optional[Tuple[int]] = self.coffee_list.curselection()
        if not selection:
            return
        coffee = self.coffees[selection[0]]
        self.current_coffee = coffee

    def delete_coffee(self):
        if self.current_coffee is None:
            logger.warning(f"Couldn't delete coffee manually: no coffee selected.")
            self.delete_btn.config(bg="red")
            return
        if self.current_coffee.delete():
            logger.warning(f"{self.current_coffee.purchase_id:>6} {self.current_coffee.nb_coffee} "
                           f"{self.current_coffee.price}€ {self.current_coffee.date.strftime('%y/%m/%d %H:%M:%S')}"
                           f" was deleted.")
            self.delete_btn.config(bg="green")
        else:
            logger.warning(f"Unknown database error occurred will deleting coffee.")
            self.delete_btn.config(bg="red")

    def coffee_to_loss(self):
        if self.current_coffee is None:
            logger.warning(f"Couldn't change coffee to loss manually: no coffee selected.")
            self.to_loss_btn.config(bg="red")
            return
        if self.current_coffee.to_loss():
            logger.warning(f"{self.current_coffee.purchase_id:>6} {self.current_coffee.nb_coffee} "
                           f"{self.current_coffee.price}€ {self.current_coffee.date.strftime('%y/%m/%d %H:%M:%S')}"
                           f" changed to loss.")
            self.to_loss_btn.config(bg="green")
        else:
            logger.warning(f"Unknown database error occurred will updating coffee (to loss).")
            self.to_loss_btn.config(bg="red")

    def close(self):
        self.future.set_result(None)
        self.gui.destroy()

    def get_future(self) -> Future[None]:
        return self.future


class AdminJuraGui(AbstractUI):
    def __init__(self, main: MainGUI, coffee_maker: Optional[CoffeeMaker]):
        super().__init__(main, "Admin Jura", 370, 220)

        self.coffee_maker = coffee_maker

        if self.coffee_maker is None:
            self.lbl = self.add_label("No Jura is configured.")
        else:
            self.jura_btn = [JuraCommand.BUTTON_1, JuraCommand.BUTTON_2, JuraCommand.BUTTON_3,
                             JuraCommand.BUTTON_4, JuraCommand.BUTTON_5, JuraCommand.BUTTON_6]
            self.btn = [
                self.add_button(f"Left Up", self.wrapper_press_jura_btn(0), x=10, y=10, width=7, height=1),
                self.add_button(f"Left Mid", self.wrapper_press_jura_btn(1), x=10, y=70, width=7, height=1),
                self.add_button(f"Left Down", self.wrapper_press_jura_btn(2), x=10, y=130, width=7, height=1),
                self.add_button(f"Right Up", self.wrapper_press_jura_btn(3), x=170, y=10, width=7, height=1),
                self.add_button(f"Right Mid", self.wrapper_press_jura_btn(4), x=170, y=70, width=7, height=1),
                self.add_button(f"Right Down", self.wrapper_press_jura_btn(5), x=170, y=130, width=7, height=1)
            ]

    def wrapper_press_jura_btn(self, btn_id: int):
        def press_jura_btn():
            if self.coffee_maker.jura.write_with_response(self.jura_btn[btn_id]) == "ok:":
                self.btn[btn_id].config(bg="green")
            else:
                self.btn[btn_id].config(bg="red")

        return press_jura_btn

    def close(self):
        self.future.set_result(None)
        self.gui.destroy()

    def get_future(self) -> Future[None]:
        return self.future


class MaintenanceScreen(AbstractUI):
    def __init__(self, main: MainGUI, rfid: RFIDReader, get_user_by_rfid: Callable[[str], Optional[User]]):
        super().__init__(main, "Maintenance", 800, 480)
        self.close_btn.place_forget()
        self.get_user_by_rfid = get_user_by_rfid
        self.rfid = rfid
        self.card_future = rfid.get_rfid()
        self.card_future.add_done_callback(self.read_card_callback)

        self.add_label("The coffee machine is under maintenance!", font='Helvetica 20 bold',
                       pady=80)
        self.add_label("It will be back as soon as possible.")
        self.add_label("Cafément votre,")
        self.add_label("The U2IS Coffee Team.")

    def read_card_callback(self, f: Future[str]):
        badge = f.result()
        user = self.get_user_by_rfid(badge)
        if user is None or not user.is_maintainer():
            self.card_future = self.rfid.get_rfid()
            self.card_future.add_done_callback(self.read_card_callback)
            return
        self.future.set_result(user)
        self.gui.destroy()

    def get_future(self) -> Future[Optional[User]]:
        return self.future


def get_app_version():
    try:
        return importlib.metadata.version('coffee_tag')
    except importlib.metadata.PackageNotFoundError:
        return "unknown (dev)"


def get_driver_version():
    try:
        return importlib.metadata.version('juracoffeemachine')
    except importlib.metadata.PackageNotFoundError:
        return "unknown (dev)"


class MainGUI:

    def __init__(self, main_callback: Callable[[], None],
                 create_user_callback: Callable[[], None],
                 coffee_price: float):
        self.opened_popup = []
        self.tk = tk.Tk()
        self.tk.geometry('800x480')
        self.tk.title('My wonderful coffee app')
        self.tk["bg"] = BROWN  # background color
        self.tk.resizable(height=False, width=False)

        # Use fullscreen but bind an escape key to window destruction to escape fullscreen
        self.tk.attributes("-fullscreen", True)
        self.tk.bind("<Escape>", lambda e: self.tk.destroy())

        # Place the text label on the window, 10 pixels from the top, and fill the window on x
        txt_lbl1 = tk.Label(self.tk, text="You should take a break...",
                            font='Helvetica 22 bold', fg=WHITE, bg=BROWN)
        txt_lbl1.pack(side="top", pady=10, fill='x')

        # Add coffee price
        txt_lbl2 = tk.Label(self.tk, text=f"Badge for a coffee ({coffee_price:.2f} €)",
                            font='Helvetica 16 bold', fg=LIGHT_BROWN, bg=BROWN)
        txt_lbl2.pack(side="top", fill='x')

        # Button label to manually check identity
        search_btn = tk.Button(self.tk, text="Use manual search", font='Helvetica 15 bold', fg=DARK_BROWN,
                               bg=LIGHT_BROWN, height=2, width=20,
                               command=main_callback)
        search_btn.place(x=120, y=410)

        # Button to add new user
        new_btn = tk.Button(self.tk, text="Create new account", font='Helvetica 15 bold', fg=DARK_BROWN,
                            bg=LIGHT_BROWN, height=2, width=20,
                            command=create_user_callback)
        new_btn.place(x=430, y=410)

        # Version label
        version_lbl = tk.Label(self.tk, text=f"{get_app_version()} - {get_driver_version()}",
                               font='Helvetica 10', fg=LIGHT_BROWN,
                               bg=BROWN)
        version_lbl.place(x=5, y=460)

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


def show_gui(config: Config):
    rfid = RFIDReader(config)
    db = Database(config)
    users = db.search_by_name("dit-")
    gui = MainGUI(lambda: None, lambda: None, 0.25)

    async def wrapper(entity, **args):
        return await entity(**args).get_future()

    async def tk_loop():
        loop = asyncio.get_event_loop()
        asyncio.set_event_loop(loop)

        loop.create_task(wrapper(ManualEntry, main=gui, search_user=db.search_by_name))
        loop.create_task(wrapper(AdminGUI, main=gui, users=db.get_users()))
        loop.create_task(wrapper(AskPassword, main=gui, rfid=rfid, user=users[0]))
        loop.create_task(wrapper(GeneralUI, main=gui, title="Sorry!",
                                 w=350, h=310,
                                 sub_text="I could not find you",
                                 main_text="Former user with new badge?",
                                 button_one="Synchronize",
                                 button_two="Add me"))
        loop.create_task(wrapper(GeneralUI, main=gui, title="Welcome back!",
                                 w=320, h=250,
                                 main_text="Your badge has been successfully linked to your account",
                                 button_one="Ok"))
        loop.create_task(wrapper(GeneralUI, main=gui, title="Please update your profile.",
                                 w=320, h=250,
                                 main_text="To access your account please update your profile.",
                                 button_one="Ok"))
        loop.create_task(wrapper(GeneralUI, main=gui, title="Your account is deactivated.",
                                 w=320, h=300,
                                 main_text="Your account has been blocked indefinitely.",
                                 sub_text="Please contact us at cafe.u2is@gmail.com.",
                                 sub_after_main=True,
                                 button_one="Ok"))
        loop.create_task(wrapper(GeneralUI, main=gui, title="Oops...",
                                 w=320, h=300,
                                 main_text="An unexpected error occurred while opening your profile!",
                                 sub_text="If it is continues, please contact us at cafe.u2is@gmail.com.",
                                 sub_after_main=True,
                                 button_one="Ok"))
        loop.create_task(wrapper(GeneralUI, main=gui, title="Wrong password!",
                                 w=320, h=300,
                                 main_text="The provided password is not correct!",
                                 sub_text="Please contact an admin if you're having trouble login in.",
                                 sub_after_main=True,
                                 button_one="Ok"))
        loop.create_task(wrapper(GeneralUI, main=gui, title="Wow, are you sure?",
                                 w=320, h=320,
                                 main_text=f"Do you confirm buying {5} coffees?",
                                 button_one="Yes", button_two="Oops"))
        loop.create_task(wrapper(GeneralUI, main=gui, title=f"Thank you {users[0]}!",
                                 w=490, h=230,
                                 sub_text="Your balance is now",
                                 main_text=f"{-users[0].get_user_balance()} €",
                                 should_close_in_5=True))
        loop.create_task(wrapper(GeneralUI, main=gui, title="Fill all the required field.",
                                 w=320, h=290,
                                 main_text="You must provide your password."
                                           " It needs to be at least 4 characters.",
                                 button_one="Ok"))
        loop.create_task(wrapper(GeneralUI, main=gui, title="Fill all the required field.",
                                 w=320, h=290,
                                 main_text="You must provide your date of departure."
                                           " Mind the format YYYY/MM/DD.",
                                 button_one="Ok"))
        loop.create_task(wrapper(GeneralUI, main=gui, title="Your mail is not valid.",
                                 w=320, h=290,
                                 main_text="Please provide a valid mail.",
                                 button_one="Ok"))
        loop.create_task(wrapper(GeneralUI, main=gui, title="Account already exists.",
                                 w=320, h=290,
                                 main_text="An account with this name and surname or mail or badge id already exists.",
                                 button_one="Ok"))
        loop.create_task(wrapper(GeneralUI, main=gui, title="Your account is deactivated.",
                                 w=320, h=300,
                                 main_text="Your account is past its date of departure.",
                                 sub_text="Please contact an admin or email us at cafe.u2is@gmail.com.",
                                 sub_after_main=True,
                                 button_one="Ok"))
        loop.create_task(wrapper(GeneralUI, main=gui, title=f"Welcome {str(users[0])}!",
                                 w=320, h=270,
                                 main_text="Your profile is now created!" if users[0] is None \
                                     else "Your profile was updated!",
                                 button_one="Ok"))
        loop.create_task(wrapper(GeneralUI, main=gui, title="Oops...",
                                 w=320, h=250,
                                 main_text="An unexpected error occurred while creating your profile!",
                                 button_one="Ok"))
        loop.create_task(wrapper(UserMenu, main=gui, user=users[0]))
        loop.create_task(wrapper(UserProperties, main=gui, rfid=rfid, is_creation=False, user=users[0]))
        loop.create_task(wrapper(BrewCoffee, main=gui, user=users[0],
                                 get_brewing_status=lambda: None, beans_q=2, water_v=80))

        while True:
            gui.tk.update()
            await asyncio.sleep(1 / 60)

    asyncio.run(tk_loop())
