from __future__ import annotations

import asyncio
import logging
import os
import tkinter as tk
from asyncio import Future
from datetime import datetime as dt, timezone
from itertools import count  # Islice for list iteration not starting at 0
from typing import Tuple, Optional

from PIL import Image, ImageTk

from coffee_tag import media
from coffee_tag.database import User, COFFEE_PRICE
from coffee_tag.rfid import RFIDReader

logger = logging.getLogger(__name__)


def setup_popup(main: MainGUI,
                title: str, size: str) -> Tuple[tk.Toplevel, Future]:
    future = asyncio.get_event_loop().create_future()
    gui = tk.Toplevel(main.tk)
    gui.protocol("WM_DELETE_WINDOW", lambda: [future.set_result(None), gui.destroy()])
    gui.transient(main.tk)
    gui.grab_set()
    gui.geometry(size)
    gui.title(title)
    gui['bg'] = '#754c24'
    gui.resizable(height=False, width=False)
    main.opened_popup.append(gui)
    return gui, future


async def ManualEntryPopup(main: MainGUI):
    gui, future = setup_popup(main, "Manual identification", '280x140')
    lbl = tk.Label(gui, text="What is your name ?",
                   font='Helvetica 14 bold italic', fg="white", bg='#754c24')
    lbl.pack(side="top", pady=10, fill='x')
    entry = tk.Entry(gui, font='Helvetica 14')
    entry.focus_set()
    entry.pack(side="top")
    bt_label = tk.Button(gui, text="Find me !", font='Helvetica 12 bold', fg='#5b3719', bg='#c9a589',
                         command=lambda: [future.set_result(entry.get()), gui.destroy()])
    bt_label.pack(side="bottom", pady=10)
    return await future


async def OneButtonPopup(main: MainGUI,
                         title: str, message: str, button_msg: str) -> Optional[bool]:
    gui, future = setup_popup(main, title, '260x200')
    msg_lbl = tk.Label(gui, text=message, wraplength=240, justify="center", font='Helvetica 12 bold italic',
                       fg='white', bg='#754c24')
    msg_lbl.pack(side="top", pady=10, fill='x')
    bt_lbl = tk.Button(gui, text=button_msg, font='Helvetica 16 bold', fg='#5b3719', bg='#c9a589', height=2, width=4,
                       command=lambda: [future.set_result(True), gui.destroy()])
    bt_lbl.pack(side="top", pady=20)
    return await future


async def ChooseUserPopup(main: MainGUI, users: list[User]):
    gui, future = setup_popup(main, "Choose", f"300x{210 + 40 * len(users)}+247+120")
    found_lbl = tk.Label(gui, text=f"I found {len(users)} results",
                         font='Helvetica 14 bold', fg='#c9a589', bg='#754c24')
    found_lbl.pack(side="top", fill='x')
    txt_lbl = tk.Label(gui, text="Are you... ?", font='Helvetica 12 bold italic', fg='#c9a589', bg='#754c24')
    txt_lbl.pack(side="top", pady=10, fill='x')
    for i, user in enumerate(users):
        bt_lbl = tk.Button(gui, text=f"{user.name} {user.surname}",
                           font='Helvetica 12 bold', fg='#5b3719',
                           bg='#c9a589', height=1,
                           width=18, command=lambda: [future.set_result(user), gui.destroy()])
        bt_lbl.pack(side="top")
    add_bt_lbl = tk.Button(gui, text="Add me", font='Helvetica 12 bold', fg='#5b3719',
                           bg='#c9a589', height=1, width=10,
                           command=lambda: [future.set_result("add_user"),
                                            gui.destroy()])
    add_bt_lbl.pack(side="top")
    return await future


async def UserNotFoundPopup(main: MainGUI, is_by_badge: bool):
    gui, future = setup_popup(main, "Sorry", '270x230' if is_by_badge else '200x200')
    sorry_lbl = tk.Label(gui, text="Sorry !", font='Helvetica 22 bold', fg="white", bg='#754c24')
    sorry_lbl.pack(side="top", pady=10, fill='x')
    txt_lbl = tk.Label(gui, text="I could not find you",
                       font='Helvetica 12 bold italic', fg='#c9a589', bg='#754c24')
    txt_lbl.pack(side="top", fill='x')
    if is_by_badge:
        exist_txt_lbl = tk.Label(gui, text="Former user with new badge ?",
                                 font='Helvetica 12 bold italic', fg='white', bg='#754c24')
        exist_txt_lbl.pack(side="top", pady=10, fill='x')
        bis_bt_lbl = tk.Button(gui, text="Synchronize", font='Helvetica 12 bold',
                               fg='#5b3719', bg='#c9a589', height=1, width=14,
                               command=lambda: [future.set_result("sync_badge"), gui.destroy()])
        bis_bt_lbl.pack(side="top")
    else:
        bis_bt_lbl = tk.Button(gui, text="Try again", font='Helvetica 12 bold',
                               fg='#5b3719', bg='#c9a589', height=1, width=10,
                               command=lambda: [future.set_result("try_again"), gui.destroy()])
        bis_bt_lbl.pack(side="top", pady=10)
    add_bt_lbl = tk.Button(gui, text="Add me", font='Helvetica 12 bold', fg='#5b3719',
                           bg='#c9a589', height=1, width=10,
                           command=lambda: [future.set_result("add_new_user"), gui.destroy()])
    add_bt_lbl.pack(side="top")
    return await future


async def UserMenuPopup(main: MainGUI, user: User):
    gui, future = setup_popup(main, "Your account", "420x370")
    welcome_lbl = tk.Label(gui, text=f"Hello {user}!", font='Helvetica 22 bold', fg="white", bg='#754c24')
    welcome_lbl.pack(side="top", pady=10, fill='x')
    txt_lbl = tk.Label(gui, text="Your balance is currently",
                       font='Helvetica 15', fg='#c9a589', bg='#754c24')
    txt_lbl.pack(side="top")
    amount_lbl = tk.Label(gui, text=f"{-user.get_user_balance()} €", font='Helvetica 22 bold', fg="white", bg='#754c24')
    amount_lbl.pack(side="top", pady=10, fill='x')
    last_coffee = user.get_last_coffee()
    if last_coffee is not None:
        info_time_lbl = tk.Label(gui,
                                 text=f"Your last coffee was {str(dt.now(timezone.utc) - last_coffee.date).split('.')[0]} ago.",
                                 font='Helvetica 15', fg='#c9a589', bg='#754c24')
        info_time_lbl.pack(side="top", fill='x')
    coffee_lbl = tk.Label(gui, text="How many coffees will you take ?",
                          font='Helvetica 15', fg='#c9a589', bg='#754c24')
    coffee_lbl.pack(side="top")
    # Create entry and buttons to set the amount of coffee
    entry = tk.Entry(gui, width=3, font='Helvetica 15 bold')
    entry.delete(0, tk.END)
    entry.insert(0, "1")
    entry.focus_set()
    entry.place(x=193, y=227)

    def update_entry(add: bool):
        coffee_count = 1
        if entry.get().isdigit():
            coffee_count = int(entry.get())
            coffee_count += 1 if add else -1
            coffee_count = max(1, coffee_count)
        entry.delete(0, tk.END)
        entry.insert(0, str(coffee_count))

    incr_bt_lbl = tk.Button(gui, text="►", font='Helvetica 25', fg='#5b3719', bg='#c9a589',
                            height=1, width=1, command=lambda: update_entry(True))
    incr_bt_lbl.place(x=255, y=215)
    incr_bt_lbl = tk.Button(gui, text="◄", font='Helvetica 25', fg='#5b3719', bg='#c9a589',
                            height=1, width=1, command=lambda: update_entry(False))
    incr_bt_lbl.place(x=115, y=215)

    # A button to validate number of coffees to count
    def validate_input():
        if entry.get().isdigit():
            future.set_result(int(entry.get()))
            gui.destroy()
        else:
            entry.delete(0, tk.END)
            entry.insert(0, str(1))

    bt_lbl = tk.Button(gui, text="OK", font='Helvetica 14 bold', fg='#5b3719', bg='#c9a589',
                       height=2, width=2, command=validate_input)
    bt_lbl.place(x=185, y=275)
    return await future


async def AskConfirmationPopup(main: MainGUI,
                               title: str,
                               question: str):
    gui, future = setup_popup(main, title, "220x220")
    warning_lbl = tk.Label(gui, text=question, wraplength=220, justify="center", font='Helvetica 22 bold', fg="white",
                           bg='#754c24')
    warning_lbl.pack(side="top", pady=10, fill='x')
    # Buttons
    yes_bt_lbl = tk.Button(gui, text="Yes", font='Helvetica 12 bold', fg='#5b3719', bg='#c9a589', height=1,
                           width=10, command=lambda: [future.set_result(True), gui.destroy()])
    yes_bt_lbl.pack(side="top", pady=10)
    oops_bt_lbl = tk.Button(gui, text="Oops", font='Helvetica 12 bold', fg='#5b3719', bg='#c9a589', height=1,
                            width=10, command=lambda: [future.set_result(False), gui.destroy()])
    oops_bt_lbl.pack(side="top")
    return await future


async def ThanksPopup(main: MainGUI, user):
    gui, future = setup_popup(main, "Thank you!", "320x230")
    welcome_lbl = tk.Label(gui, text=f"Thank you {user},", wraplength=280, justify="center",
                           font='Helvetica 22 bold', fg="white", bg='#754c24')
    welcome_lbl.pack(side="top", pady=10, fill='x')
    txt_lbl = tk.Label(gui, text="Your balance is now", font='Helvetica 15', fg='#c9a589', bg='#754c24')
    txt_lbl.pack(side="top")
    amount_lbl = tk.Label(gui, text=f"{-user.get_user_balance()} €", font='Helvetica 22 bold', fg="white",
                          bg='#754c24')
    amount_lbl.pack(side="top", pady=10, fill='x')
    # automatic close
    closing_lbl = tk.Label(gui, text=f"Closing window in 5 seconds...",
                           font='Helvetica 12 bold italic', fg="white", bg='#754c24')
    closing_lbl.pack(side="top", fill='x', pady=10)
    for i in range(5, -1, -1):
        closing_lbl.config(text=f"Closing window in {i} seconds...")
        gui.update()
        await asyncio.sleep(1)
    future.set_result(None)
    gui.destroy()
    return await future


async def AddNewUserPopup(main: MainGUI, rfid: RFIDReader,
                          name: str, surname: str, nickname: str, mail: str, badge: str):
    gui, future = setup_popup(main, "Add user", "650x350")

    txt_lbl = tk.Label(gui, text="Enter your data", font='Helvetica 16 bold', fg='#c9a589', bg='#754c24')
    txt_lbl.pack(side="top", pady=10, fill='x')
    # Name
    name_lbl = tk.Label(gui, text="Name", font='Helvetica 12 bold italic', fg="white", bg='#754c24')
    name_lbl.place(x=40, y=50)
    name_entry = tk.Entry(gui, textvariable=tk.StringVar(value=name), width=20, font='Helvetica 12')
    name_entry.focus_set()
    name_entry.place(x=40, y=80)
    # Surname
    surname_lbl = tk.Label(gui, text="Surname", font='Helvetica 12 bold italic', fg="white", bg='#754c24')
    surname_lbl.place(x=40, y=110)
    surname_entry = tk.Entry(gui, textvariable=tk.StringVar(value=surname), width=20, font='Helvetica 12')
    surname_entry.place(x=40, y=140)
    # Nickname
    nickname_lbl = tk.Label(gui, text="Nickname (optional)", font='Helvetica 12 bold italic', fg="white", bg='#754c24')
    nickname_lbl.place(x=40, y=170)
    nickname_entry = tk.Entry(gui, textvariable=tk.StringVar(value=nickname), width=20, font='Helvetica 12')
    nickname_entry.place(x=40, y=200)
    # Mail
    mail_lbl = tk.Label(gui, text="E-mail address", font='Helvetica 12 bold italic', fg="white", bg='#754c24')
    mail_lbl.place(x=250, y=50)
    mail_entry = tk.Entry(gui, textvariable=tk.StringVar(value=mail), width=35, font='Helvetica 12')
    mail_entry.place(x=250, y=80)
    # Badge
    badge_txt_lbl = tk.Label(gui, text="Swipe your ENSTA badge if you have one to synchronize it with your profile",
                             wraplength=320, font='Helvetica 12 bold italic', fg='#c9a589', bg='#754c24')
    badge_txt_lbl.place(x=250, y=140)
    # Create a dynamic label displaying current badge code
    badge_lbl = tk.Label(gui, text=badge, width=35, font='Helvetica 12 bold', fg="white", bg='#754c24', borderwidth=1,
                         highlightthickness=1)
    badge_lbl.place(x=250, y=200)
    card_future = [rfid.get_rfid()]  # use array to shit and have a kind of pointer

    def read_card_callback(f: Future[str]):
        if not future.done():  # check if the windows is still open
            badge_lbl.config(text=f.result())
            card_future[0] = rfid.get_rfid()
            card_future[0].add_done_callback(read_card_callback)

    card_future[0].add_done_callback(read_card_callback)
    # Submit button
    add_bt_lbl = tk.Button(gui, text="OK", font='Helvetica 16 bold', fg='#5b3719', bg='#c9a589', height=2, width=4,
                           command=lambda: [future.set_result((name_entry.get(), surname_entry.get(),
                                                               nickname_entry.get(), mail_entry.get(),
                                                               badge_lbl.cget("text"))),
                                            gui.destroy()])
    add_bt_lbl.place(x=290, y=250)
    return await future


class MainGUI:

    def __init__(self, manager):
        self.opened_popup = []
        self.manager = manager

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
        txt_lbl2 = tk.Label(self.tk, text=f"Badge for a coffee ({COFFEE_PRICE:.2f} €)",
                            font='Helvetica 16 bold', fg='#c9a589', bg='#754c24')
        txt_lbl2.pack(side="top", fill='x')

        # Button label to manually check identity
        bt_lbl = tk.Button(self.tk, text="Can't read my badge ?", font='Helvetica 15 bold', fg='#5b3719',
                           bg='#c9a589', height=2, width=24,
                           command=lambda: self.manager.loop.create_task(
                               self.manager.manual_search_and_open_account()))
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
