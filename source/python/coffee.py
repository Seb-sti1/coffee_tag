"""  Main script of the coffee-tag app """

#
#  Imports
#

import pandas as pd
import sqlite3 as sql
from tkinter import ttk  # ttk for ListeCombo
import tkinter as tk
from PIL import Image, ImageTk
import numpy as np
from itertools import count, islice  # Islice for list iteration not starting at 0
import threading  # Threads for non-blocking timer callbacks
import time  # Timer and sleeps
from enum import Enum
from datetime import datetime as dt

DEV_MODE = False
VERBOSE = False
COFFEE_PRICE = 0.25

# Give access to GPIO and import pn532 to use NFC reader
if not DEV_MODE:
    import RPi.GPIO as GPIO
    from pn532 import *


#
#  Global variables
#


# Badge code must be accessible for every window or object of the project
current_badge = []
# TKinter focus and grab methods doesn't seems to allow a easy detection of current window
# Instead, we use a global window counter to check when only main is opened
current_windows = 0


class Identification(Enum):
    """ An enum to differenciate identification way """
    BADGE = 1
    NAME = 2


class Error(Enum):
    """ An enum to differenciate errors """
    NONE = 0
    NAME = 1
    MAIL = 2


def on_closing():
    global current_windows
    current_windows -= 1


def on_opening():
    global current_windows
    current_windows += 1


class BadgeLabel(tk.Label):
    """ A class for an updated text (label that inherits from tk Label to display NFC codes) """

    def start(self, delay) -> None:
        self.delay = delay
        self.run = True
        self.update()

    def stop(self) -> None:
        self.run = False

    def update(self) -> None:
        if not self.run: return

        string = ""
        if current_badge:
            for i in current_badge: string += hex(i) + " "
        self.config(text=string)
        self.after(self.delay, self.update)


class BadgeEntry:
    """
    A class for continuous reading of NFC tags  (communication used for HAT: I2C)
    The timer callback is made through a call to update() method which ends on the
    creation of a Timer on a new thread to re-call update()
    """

    def __init__(self, methodToRun, root):
        if DEV_MODE: print("Running in developpement mode, NFC reader not available")
        else:
            self.pn532 = PN532_I2C(debug=False, reset=20, req=16)
            ic, ver, rev, support = self.pn532.get_firmware_version()
            print('Found PN532 with firmware version: {0}.{1}'.format(ver, rev))
            # Configure PN532 to communicate with MiFare cards
            self.pn532.SAM_configuration()
            print('Ready to read RFID/NFC card...')
        # Register the method to call if a badge is detected
        self.callback = methodToRun
        self.main_root = root
        self.delay = 0.1  # Period in seconds
        self.timeout = 5  # Delay before discarding last badge info
        self.lasttime = time.time()
        self.uid = []
        self.run = True
        self.update()

    def stop(self):
        self.run = False

    def update(self):
        global current_badge
        now = time.time()
        if (now - self.lasttime) > self.timeout:
            self.uid = []
            current_badge = self.uid

        if not self.run: return

        _input = None if DEV_MODE else self.pn532.read_passive_target(timeout=0.01)
        if _input is not None:
            if VERBOSE: print('Found card with UID:', [hex(i) for i in input])
            self.uid = _input
            # Find a user with its badge only if main window is focused (otherwise, another action is ongoing)
            global current_windows
            if VERBOSE: print("Current opened windows:", current_windows)
            if current_windows == 1:
                self.callback(str(self.uid), None, Identification.BADGE)
            current_badge = self.uid
            self.lasttime = now
        threading.Timer(self.delay, self.update).start()


class Finder:
    """ A class to search a user in a database """

    def __init__(self, db_path,view_db, root):
        # Open csv file, and fill NaN with empty string
        self.path = db_path
        self.view_db = view_db
        #self.connection = sql.connect(csv_path)
        #self.cursor=self.connection.cursor()
        # Get csv reader as a list to have an easy access through index
        #self.my_csv_data = self.file.values.tolist()
        self.main = root
        # Create a BadgeEntry object for continuous reading from NFC reader
        self.badgeEntry = BadgeEntry(self.find_me, root)

    def query_txt (self, sql_txt,other=''):
        if (other==''):
            other=self.path
        con = sql.connect(other)
        with con:
            cur = con.cursor()
            cur.execute(sql_txt)
            res = cur.fetchall()
        if con:
            con.close()
        return res

    def query_var (self,sql_txt,values,other=''):
        if (other==''):
            other=self.path
        con = sql.connect(other)
        with con:
            cur = con.cursor()
            cur.execute(sql_txt,values)
            res = cur.fetchall()
        if con:
            con.close()
        return res
    
    def stop(self):
        self.badgeEntry.stop()
        global current_windows
        current_windows = 0
        self.main.destroy()
        # It doesn't seem mandatory to close any file as we just "read" and not "open" it

    def manual_entry(self):
        new_root = tk.Toplevel(self.main)
        new_root.protocol("WM_DELETE_WINDOW", lambda: [
                          on_closing(), new_root.destroy()])
        on_opening()
        new_root.transient(self.main)  # set to be on top of the main window
        # hijack all commands from the master (clicks on the main window are ignored)
        new_root.grab_set()
        new_root.geometry('280x140')
        new_root.title('Manual identification')
        new_root['bg'] = '#754c24'
        new_root.resizable(height=False, width=False)
        # Create an Entry widget to accept User Input for name
        new_txt_lbl = tk.Label(new_root, text="What is your name ?",
                               font='Helvetica 14 bold italic', fg="white", bg='#754c24')
        new_txt_lbl.pack(side="top", pady=10, fill='x')
        user_name = tk.StringVar()
        entry = tk.Entry(new_root, textvariable=user_name, font='Helvetica 14')
        entry.focus_set()
        entry.pack(side="top")
        # Add button to validate Entry Widget
        new_bt_label = tk.Button(
            new_root,
            text="Find me !",
            font='Helvetica 12 bold',
            fg='#5b3719',
            bg='#c9a589',
            command=lambda: self.find_entry(
                entry,
                new_root,
                Identification.NAME))
        new_bt_label.pack(side="bottom", pady=10)

    def erase(self, root):
        on_closing()
        root.destroy()
    # If badge can't be read, allow user to manually identity

    def erase_and_manual_entry(self, root):
        on_closing()
        root.destroy()
        self.manual_entry()

    def erase_and_found(self, root, index):
        on_closing()
        root.destroy()
        self.found(index)

    def update_coffee(self, int_update, entry):
        coffee = int(entry.get())
        coffee += int_update
        if coffee < 0: coffee = 0
        # Delete all caracters in coffee selection and insert the updated value
        entry.delete(0, tk.END)
        entry.insert(0, coffee)

    def confirm(self, entry, root, index):
        """ A security function for too high / error (2 digits and more) entry of coffees """
        coffee = int(entry.get())
        if coffee > 9:
            new_root = tk.Toplevel(self.main)
            new_root.protocol("WM_DELETE_WINDOW", lambda: [
                              on_closing(), new_root.destroy()])
            global current_windows
            current_windows += 1
            new_root.transient(root)  # set to be on top of the main window
            # hijack all commands from the master (clicks on the main window are ignored)
            new_root.grab_set()
            new_root.geometry('220x220')
            new_root.title('Confirm')
            new_root['bg'] = '#754c24'
            new_root.resizable(height=False, width=False)
            warning_lbl = tk.Label(
                new_root, text="Wow !", font='Helvetica 22 bold', fg="white", bg='#754c24')
            warning_lbl.pack(side="top", pady=10, fill='x')
            amount_lbl = tk.Label(
                new_root,
                text="Do you confirm " +
                str(coffee) +
                " coffees ?",
                wraplength=220,
                justify="center",
                font='Helvetica 15',
                fg='#c9a589',
                bg='#754c24')
            amount_lbl.pack(side="top")
            # Buttons
            yes_bt_lbl = tk.Button(
                new_root,
                text="Yes",
                font='Helvetica 12 bold',
                fg='#5b3719',
                bg='#c9a589',
                height=1,
                width=10,
                command=lambda: [
                    self.update_csv(
                        entry,
                        root,
                        index),
                    new_root.destroy(),
                    on_closing(),
                    self.summation(index)])
            yes_bt_lbl.pack(side="top", pady=10)
            oops_bt_lbl = tk.Button(
                new_root,
                text="Oops",
                font='Helvetica 12 bold',
                fg='#5b3719',
                bg='#c9a589',
                height=1,
                width=10,
                command=lambda: [
                    new_root.destroy(),
                    on_closing()])
            oops_bt_lbl.pack(side="top")
        else:
            self.update_csv(entry, root, index)
            self.summation(index)

    def summation(self, index):
        new_root = tk.Toplevel(self.main)
        new_root.protocol("WM_DELETE_WINDOW", lambda: [
                          on_closing(), new_root.destroy()])
        on_opening()
        # set to be on top of the previous window
        new_root.transient(self.main)
        new_root.grab_set()
        new_root.geometry('320x230')
        new_root.title('Summation')
        new_root['bg'] = '#754c24'
        #on_closing()
        query="SELECT * FROM current WHERE id = ? "
        query_variables=(index,)
        res=self.query_var(query,query_variables)
        response=res[0]
        use_surname = response[3] == "" 
        user = str(response[1 if use_surname else 3])
        welcome_lbl = tk.Label(
            new_root,
            text="Thank you " +
            str(user) +
            ",",
            wraplength=280,
            justify="center",
            font='Helvetica 22 bold',
            fg="white",
            bg='#754c24')
        welcome_lbl.pack(side="top", pady=10, fill='x')
        txt_lbl = tk.Label(new_root, text="Your account is now",
                           font='Helvetica 15', fg='#c9a589', bg='#754c24')
        txt_lbl.pack(side="top")
        amount = -float(response[8])
        amount_lbl = tk.Label(new_root, text=str(
            round(amount, 2)) + " €", font='Helvetica 22 bold', fg="white", bg='#754c24')
        amount_lbl.pack(side="top", pady=10, fill='x')
        # automatic close
        closing_lbl = tk.Label(
            new_root, font='Helvetica 12 bold italic', fg="white", bg='#754c24')
        closing_lbl.pack(side="top", fill='x', pady=30)
        for i in range(5, -1, -1):
            closing_lbl.config(text="Closing window in " +
                               str(i) + " seconds...")
            new_root.update()
            time.sleep(1)
        new_root.destroy()
        on_closing()

    def update_csv(self, entry, root, index):
        entry_val=entry.get()
        price = round(int(entry_val) * COFFEE_PRICE, 2)
        # get iformation of current sold
        current_data=self.query_var("SELECT id, name,surname, debit, sold FROM current WHERE id=?",(index,))
        if VERBOSE: print(f"It will cost {price:.2f} € to {current_data[0][1]}")
        on_closing()
        root.destroy()
        # get time
        date=time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
        
        response=current_data[0]
        self.query_var("INSERT INTO coffee_count VALUES (?,?,?,?)",(index,date,int(entry_val),price))
        # Note: in csv file, a debt is positive and an advance negative
        total_debt=response[3]+price
        new_debt = round(float(response[4]) + price, 2)
        if VERBOSE: print(f"New debt is {-new_debt:.2f}")
        self.query_var("UPDATE current SET debit = ?, sold =? WHERE id = ?",(total_debt,new_debt,index))
        self.query_var("UPDATE view SET sold =? WHERE name = ? AND surname = ?",(new_debt,response[1],response[2]),self.view_db )
        if VERBOSE: print(f"ALL it's ok for update table")
        """   old version
        # set value of a cell which has index label "index" and column label "Amount"
        self.file.at[index, 'Amount'] = new_debt
        # writing into the file (use index False not to print fields for index)
        self.file.to_csv(self.path, index=False)
        # Update local my_csv_data variable with new value as well
        self.my_csv_data = self.file.values.tolist()"""

    def found(self, index):
        new_root = tk.Toplevel(self.main)
        new_root.protocol("WM_DELETE_WINDOW", lambda: [
                          on_closing(), new_root.destroy()])
        on_opening()
        new_root.transient(self.main)  # set to be on top of the main window
        # hijack all commands from the master (clicks on the main window are ignored)
        new_root.grab_set()
        new_root.geometry('370x370')
        new_root.title('found')
        new_root['bg'] = '#754c24'
        new_root.resizable(height=False, width=False)
        query="SELECT * FROM current WHERE id = ? "
        query_variables=(index,)
        res=self.query_var(query,query_variables)
        response=res[0]
        use_surname = response[3] == ""
        user = str(response[1 if use_surname else 3])
        query="SELECT date FROM coffee_count where id = ? order by date desc limit 1"
        query_variables=(index,)
        resdate=self.query_var(query,query_variables)

        welcome_lbl = tk.Label(new_root, text="Hello " + str(user) +
                               " !", font='Helvetica 22 bold', fg="white", bg='#754c24')
        welcome_lbl.pack(side="top", pady=10, fill='x')
        txt_lbl = tk.Label(new_root, text="Your account is currently",
                           font='Helvetica 15', fg='#c9a589', bg='#754c24')
        txt_lbl.pack(side="top")
        query="SELECT * FROM payement WHERE id = ? AND already_taken = ?"
        query_variables=(index,0)
        res_payement=self.query_var(query,query_variables)
        # upodate table with credit account
        for raw in res_payement:
            response=(response[0],response[1],response[2],response[3],response[4],response[5],response[6]+raw[2],response[7],response[8]-raw[2])
            
            query="UPDATE current SET credit = ?, sold = ? WHERE id = ?"
            query_variables=(response[6],response[8],index)
            self.query_var(query,query_variables)
            query="UPDATE payement SET already_taken = ? WHERE id = ? AND already_taken = ? AND date = ?"
            query_variables=(1,index,0,raw[1])
            self.query_var(query,query_variables)
        amount = -float(response[8])
        amount_lbl = tk.Label(new_root, text=str(
            round(amount, 2)) + " €", font='Helvetica 22 bold', fg="white", bg='#754c24')
        amount_lbl.pack(side="top", pady=10, fill='x')

        date_now=time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
        if len(resdate)>0:
            delta=dt.strptime(date_now,"%Y-%m-%d %H:%M:%S") - dt.strptime((resdate[0])[0],"%Y-%m-%d %H:%M:%S")
            info_time_lbl = tk.Label(new_root, text="delta time "+delta.__str__(),
                           font='Helvetica 15', fg='#c9a589', bg='#754c24')
            info_time_lbl.pack(side="top",fill='x')
        #time_lbl = tk.Label(new_root, text=delta.__str__(),
        #                   font='Helvetica 15', fg='#c9a589', bg='#754c24')
        #time_lbl.pack(side="top",fill='x')

        coffee_lbl = tk.Label(new_root, text="How many coffees will you take ?",
                              font='Helvetica 15', fg='#c9a589', bg='#754c24')
        coffee_lbl.pack(side="top")
        # Create entry and buttons to set the amount of coffee
        coffees = 0
        entry = tk.Entry(new_root, textvariable=coffees,
                         width=3, font='Helvetica 15 bold')
        # For some reasons, the entry seems to remind its previous value even when window is destroyed
        # So juste in case, erase the value and set to 1
        entry.delete(0, 'end')
        entry.insert(0, "1")
        entry.focus_set()
        entry.place(x=168, y=227)
        incr_bt_lbl = tk.Button(new_root, text="►", font='Helvetica 25', fg='#5b3719', bg='#c9a589',
                                height=1, width=1, command=lambda: self.update_coffee(1, entry))
        incr_bt_lbl.place(x=230, y=215)
        incr_bt_lbl = tk.Button(new_root, text="◄", font='Helvetica 25', fg='#5b3719', bg='#c9a589',
                                height=1, width=1, command=lambda: self.update_coffee(-1, entry))
        incr_bt_lbl.place(x=90, y=215)
        # A button to validate number of coffees to count
        bt_lbl = tk.Button(new_root, text="OK", font='Helvetica 14 bold', fg='#5b3719', bg='#c9a589',
                           height=2, width=2, command=lambda: self.confirm(entry, new_root, index))
        bt_lbl.place(x=160, y=275)

    def register(self, root, name_entry, surname_entry, mail_entry, nickname_entry):
        surname = surname_entry.get()
        name = name_entry.get()
        mail = mail_entry.get()
        nickname = nickname_entry.get()
        badge_id = ""
        if current_badge:
            badge_id = str(current_badge)

        if name == "" or surname == "" or mail == "":
            # pop_root = tk.Tk()
            pop_root = tk.Toplevel(root)
            pop_root.protocol("WM_DELETE_WINDOW", lambda: [
                              on_closing(), pop_root.destroy()])
            on_opening()
            pop_root.transient(root)  # set to be on top of the previous window
            pop_root.grab_set()
            pop_root.geometry('260x200')
            pop_root.title('Missing value')
            pop_root['bg'] = '#754c24'
            sorry_lbl = tk.Label(
                pop_root, text="Well...", font='Helvetica 22 bold', fg="white", bg='#754c24')
            sorry_lbl.pack(side="top", pady=10, fill='x')
            warn_lbl = tk.Label(
                pop_root,
                text="You must provide at least your name, surname and mail",
                wraplength=240,
                justify="center",
                font='Helvetica 12 bold italic',
                fg='#c9a589',
                bg='#754c24')
            warn_lbl.pack(side="top", pady=10, fill='x')
            bt_lbl = tk.Button(
                pop_root,
                text="OK",
                font='Helvetica 16 bold',
                fg='#5b3719',
                bg='#c9a589',
                height=2,
                width=4,
                command=lambda: self.erase(pop_root))
            bt_lbl.pack(side="top", pady=20)
            return

        # If entries are correctly filled, look for any conflict with existing mail or [surname, name]
        error = Error.NONE
        user_index = -1

        query="SELECT * FROM current WHERE name LIKE ? AND surname LIKE ? UNION SELECT * FROM current WHERE name LIKE ? AND surname LIKE ?"
        query_variables=(name,surname,surname,name)
        res=self.query_var(query,query_variables)
        print("return of query: ",res," ",len(res))
        if (len(res)!=0):
            user_index = res[0][0]
            error = Error.NAME
        query="SELECT * FROM current WHERE mail LIKE ?"
        query_variables=(mail,)
        res=self.query_var(query,query_variables)
        print("return of mail query: ",res," ",len(res))
        if (len(res)!=0):
            user_index = res[0][0]
            error = Error.MAIL

        

        """   old version
        for i in range(0, len(self.my_csv_data)):
            # Look for the user string in Surname, Name, Nickname, or badge ID /!\ For
            # NaN values, csv data is considered as a float, so cast in string if
            # empty
            if mail.lower() == str(self.my_csv_data[i][3]).lower():
                user_index = i
                error = Error.MAIL
                break
            if ((name.lower() == str(self.my_csv_data[i][0]).lower() and
                    surname.lower() == str(self.my_csv_data[i][1]).lower()) or
                (surname.lower() == str(self.my_csv_data[i][0]).lower() and
                    name.lower() == str(self.my_csv_data[i][1]).lower())):
                user_index = i
                error = Error.NAME
                break"""
        new_root = tk.Toplevel(self.main)
        new_root.protocol("WM_DELETE_WINDOW", lambda: [
            on_closing(), new_root.destroy()])
        on_opening()
        # set to be on top of the previous window
        new_root.transient(self.main)
        new_root.grab_set()
        new_root.geometry('300x200')
        new_root.title('New user')
        new_root['bg'] = '#754c24'
        if error == Error.MAIL:
            well_lbl = tk.Label(
                new_root, text="Well...", font='Helvetica 22 bold', fg="white", bg='#754c24')
            well_lbl.pack(side="top", pady=10, fill='x')
            warn_lbl = tk.Label(
                new_root,
                text="It seems your mail is already linked to the account",
                wraplength=240,
                justify="center",
                font='Helvetica 12 bold italic',
                fg='#c9a589',
                bg='#754c24')
            warn_lbl.pack(side="top", pady=10, fill='x')
            query="SELECT * FROM current WHERE id = ?"
            query_variables=(name,surname,surname,name)
            res=self.query_var(user_index)
            name_lbl = tk.Label(new_root,
                                text=str(
                                    res[0][1]) + " " + str(res[0][2]),
                                wraplength=240,
                                justify="center",
                                font='Helvetica 12 bold',
                                fg='white',
                                bg='#754c24')
            name_lbl.pack(side="top", pady=10, fill='x')
            bt_lbl = tk.Button(
                new_root,
                text="OK",
                font='Helvetica 16 bold',
                fg='#5b3719',
                bg='#c9a589',
                height=2,
                width=4,
                command=lambda: self.erase(new_root))
            bt_lbl.pack(side="top", pady=20)
        elif error == Error.NAME:
            well_lbl = tk.Label(
                new_root, text="Well...", font='Helvetica 22 bold', fg="white", bg='#754c24')
            well_lbl.pack(side="top", pady=10, fill='x')
            name_lbl = tk.Label(
                new_root,
                text=name + " " + surname,
                wraplength=240,
                justify="center",
                font='Helvetica 12 bold',
                fg='white',
                bg='#754c24')
            name_lbl.pack(side="top", pady=10, fill='x')
            warn_lbl = tk.Label(
                new_root,
                text="is already in the database",
                wraplength=240,
                justify="center",
                font='Helvetica 12 bold italic',
                fg='#c9a589',
                bg='#754c24')
            warn_lbl.pack(side="top", fill='x')
            bt_lbl = tk.Button(
                new_root,
                text="OK",
                font='Helvetica 16 bold',
                fg='#5b3719',
                bg='#c9a589',
                height=2,
                width=4,
                command=lambda: self.erase(new_root))
            bt_lbl.pack(side="top", pady=20)
        else:  # = if (error == Error.NONE):
            # In this case, no need to return on new user form
            root.destroy()
            on_closing()
            welcome_lbl = tk.Label(
                new_root, font='Helvetica 22 bold', fg="white", bg='#754c24')
            # Display name and adjust windows-wrapped label depending on the length (wraplength)
            if len(nickname) == 0:
                welcome_lbl.config(
                    text="Welcome " + surname + " !", wraplength=280, justify="center")
            else:
                welcome_lbl.config(
                    text="Welcome " + nickname + " !", wraplength=280, justify="center")
            welcome_lbl.pack(side="top", pady=10, fill='x')
            profile_lbl = tk.Label(
                new_root,
                text="Your profile is now created",
                font='Helvetica 12 bold italic',
                fg='#c9a589',
                bg='#754c24')
            profile_lbl.pack(side="top", fill='x')

            query="SELECT id FROM current ORDER BY id DESC limit 1"
            res=self.query_txt(query)
            query="INSERT INTO current VALUES (?,?,?,?,?,?,?,?,?)"
            query_view="INSERT INTO view VALUES (?,?,?,?,?)"
            new_id=res[0][0]+1
            query_variables=(new_id,name,surname,nickname,mail,badge_id,0,0,0)
            query_variables_view=(name,surname,nickname,mail,0)
            self.query_var(query,query_variables)
            self.query_var(query_view,query_variables_view,self.view_db )
            """   old version
            # Append data frame to CSV file
            data = {
                'Surname': [surname],
                'Name': [name],
                'Nickname': [nickname],
                'Mail': [mail],
                'ID': [badge_id],
                'Amount': [str(0.0)]
            }
            df = pd.DataFrame(data)
            df.to_csv(self.path, mode='a', index=False, header=False)
            # update local variables
            self.file = pd.read_csv(self.path, delimiter=',')
            self.my_csv_data = self.file.values.tolist()
            """

            # automatic close
            closing_lbl = tk.Label(
                new_root, font='Helvetica 12 bold italic', fg="white", bg='#754c24')
            closing_lbl.pack(side="top", fill='x', pady=20)
            for i in range(5, -1, -1):
                closing_lbl.config(
                    text="Closing window in " + str(i) + " seconds...")
                new_root.update()
                time.sleep(1)
            # print(self.file)
            new_root.destroy()
            on_closing()

    def link(self, root, combo_box, badge_string):
        #index = combo_box.current()
        value=combo_box.get()
        value=value.split(" ")

        global current_windows
        new_root = tk.Toplevel(self.main)
        new_root.protocol("WM_DELETE_WINDOW", lambda: [
                          on_closing(), new_root.destroy()])
        on_opening()
        # set to be on top of the previous window
        new_root.transient(self.main)
        new_root.grab_set()
        new_root.geometry('320x200')
        new_root.title('Welcome')
        new_root['bg'] = '#754c24'
        root.destroy()
        on_closing()
        #use_surname = self.my_csv_data[index][2] == "" or pd.isna(self.my_csv_data[index][2])
        user = str(value[0])
        welcome_lbl = tk.Label(new_root, text="Hello " + str(user) +
                               ",", font='Helvetica 22 bold', fg="white", bg='#754c24')
        welcome_lbl.pack(side="top", pady=10, fill='x')
        amount_lbl = tk.Label(new_root, text="Your badge has been successfully linked to yout account",
                              font='Helvetica 14', fg='#c9a589', bg='#754c24', wraplength=280, justify="center")
        amount_lbl.pack(side="top")
        query="UPDATE current SET id_badge = ? WHERE name = ? AND surname = ?"
        query2="UPDATE current SET id_badge = ? WHERE surname = ? AND name = ?"
        query_variables=(badge_string,value[0],value[1])
        self.query_var(query,query_variables)
        self.query_var(query2,query_variables)
        """     old version
        # Replace value in Pandas Serie first
        self.file.loc[index, "ID"] = badge_string
        # print(self.file.iloc[index,4])
        self.my_csv_data = self.file.values.tolist()
        # Update the csv by re-writing everything from our local Pandas Serie
        self.file.to_csv(self.path, index=False)
        """
        # automatic close
        closing_lbl = tk.Label(
            new_root, font='Helvetica 12 bold italic', fg="white", bg='#754c24')
        closing_lbl.pack(side="top", fill='x', pady=30)
        for i in range(5, -1, -1):
            closing_lbl.config(text="Closing window in " +
                               str(i) + " seconds...")
            new_root.update()
            time.sleep(1)
        # print(self.file)
        new_root.destroy()
        on_closing()

    def synchronize(self, root, badge_string):
        root.destroy()
        on_closing()
        new_root = tk.Toplevel(self.main)
        new_root.protocol("WM_DELETE_WINDOW", lambda: [
                          on_closing(), new_root.destroy()])
        on_opening()
        new_root.transient(self.main)  # set to be on top of the main window
        # hijack all commands from the master (clicks on the main window are ignored)
        new_root.grab_set()
        new_root.geometry('420x160')
        new_root.title('Synchronize')
        new_root['bg'] = '#754c24'
        new_root.resizable(height=False, width=False)
        txt_lbl = tk.Label(new_root, text="Select a account to synchronize with",
                           font='Helvetica 16 bold', fg='#c9a589', bg='#754c24')
        txt_lbl.pack(side="top", pady=10, fill='x')
        query="SELECT name,surname FROM current ORDER BY name"
        res=self.query_txt(query)
        #sublist = (self.file.loc[:, ["Surname", "Name"]]).values.tolist()
        combo_box = ttk.Combobox(new_root, values=res, width=30)
        combo_box.current(0)
        combo_box.pack(side="top", pady=10)
        # Button
        sync_bt_lbl = tk.Button(
            new_root,
            text="Link",
            font='Helvetica 12 bold',
            fg='#5b3719',
            bg='#c9a589',
            height=1,
            width=10,
            command=lambda: self.link(
                new_root,
                combo_box,
                badge_string))
        # add_bt_lbl.pack(side="top", pady=20)
        sync_bt_lbl.pack(side="top", pady=10)

    def add_user(self, root):
        root.destroy()
        on_closing()
        new_root = tk.Toplevel(self.main)
        new_root.protocol("WM_DELETE_WINDOW", lambda: [
                          on_closing(), new_root.destroy()])
        on_opening()
        new_root.transient(self.main)  # set to be on top of the main window
        # hijack all commands from the master (clicks on the main window are ignored)
        new_root.grab_set()
        new_root.geometry('650x350')
        new_root.title('Add user')
        new_root['bg'] = '#754c24'
        new_root.resizable(height=False, width=False)
        txt_lbl = tk.Label(new_root, text="Enter your data",
                           font='Helvetica 16 bold', fg='#c9a589', bg='#754c24')
        txt_lbl.pack(side="top", pady=10, fill='x')
        # #Create Entry widgets to accept User Input for surname, name, mail, and optionally nickname
        user_name = tk.StringVar()
        user_surname = tk.StringVar()
        user_nickname = tk.StringVar()
        user_mail = tk.StringVar()
        # Name
        name_lbl = tk.Label(
            new_root, text="Name", font='Helvetica 12 bold italic', fg="white", bg='#754c24')
        # name_lbl.pack(side="top", pady=10, fill='x')
        name_lbl.place(x=40, y=50)
        name_entry = tk.Entry(
            new_root, textvariable=user_name, width=20, font='Helvetica 12')
        name_entry.focus_set()
        # name_entry.pack(side="top")
        name_entry.place(x=40, y=80)
        # Surname
        surname_lbl = tk.Label(
            new_root, text="Surname", font='Helvetica 12 bold italic', fg="white", bg='#754c24')
        # surname_lbl.pack(side="top", pady=10, fill='x')
        surname_lbl.place(x=40, y=110)
        surname_entry = tk.Entry(
            new_root, textvariable=user_surname, width=20, font='Helvetica 12')
        # surname_entry.pack(side="top")
        surname_entry.place(x=40, y=140)
        # Nickname
        nickname_lbl = tk.Label(new_root, text="Nickname (optional)",
                                font='Helvetica 12 bold italic', fg="white", bg='#754c24')
        # nickname_lbl.pack(side="top", pady=10, fill='x')
        nickname_lbl.place(x=40, y=170)
        nickname_entry = tk.Entry(
            new_root, textvariable=user_nickname, width=20, font='Helvetica 12')
        # nickname_entry.pack(side="top")
        nickname_entry.place(x=40, y=200)
        # Mail
        mail_lbl = tk.Label(new_root, text="E-mail address",
                            font='Helvetica 12 bold italic', fg="white", bg='#754c24')
        # mail_lbl.pack(side="top", pady=10, fill='x')
        mail_lbl.place(x=250, y=50)
        mail_entry = tk.Entry(
            new_root, textvariable=user_mail, width=35, font='Helvetica 12')
        # mail_entry.pack(side="top")
        mail_entry.place(x=250, y=80)
        # Badge
        badge_txt_lbl = tk.Label(
            new_root,
            text="Swipe your ENSTA badge if you have one to synchronize it with your profile",
            wraplength=320,
            font='Helvetica 12 bold italic',
            fg='#c9a589',
            bg='#754c24')
        # badge_txt_lbl.pack(side="top", pady=10, fill='x')
        badge_txt_lbl.place(x=250, y=140)
        # Create a dynamic label displaying current badge code
        badge_lbl = BadgeLabel(
            new_root,
            width=35,
            font='Helvetica 12 bold',
            fg="white",
            bg='#754c24',
            borderwidth=1,
            highlightthickness=1)
        # badge_lbl.pack(side="top")
        badge_lbl.place(x=250, y=200)
        badge_lbl.start(100)  # 100ms update on label
        # Button
        add_bt_lbl = tk.Button(
            new_root,
            text="OK",
            font='Helvetica 16 bold',
            fg='#5b3719',
            bg='#c9a589',
            height=2,
            width=4,
            command=lambda: self.register(
                new_root,
                name_entry,
                surname_entry,
                mail_entry,
                nickname_entry))
        # add_bt_lbl.pack(side="top", pady=20)
        add_bt_lbl.place(x=290, y=250)

    def find_entry(self, entry, root, identification):
        string = entry.get()
        self.find_me(string, root, identification)

    def find_me(self, user_string, root, identification):
        if user_string == "":
            pop_root = tk.Toplevel(root)
            pop_root.protocol("WM_DELETE_WINDOW", lambda: [
                              on_closing(), pop_root.destroy()])
            on_opening()
            pop_root.transient(root)
            pop_root.grab_set()
            pop_root.geometry('260x200')
            pop_root.title('Missing name')
            pop_root['bg'] = '#754c24'
            sorry_lbl = tk.Label(
                pop_root, text="Well...", font='Helvetica 22 bold', fg="white", bg='#754c24')
            sorry_lbl.pack(side="top", pady=10, fill='x')
            warn_lbl = tk.Label(
                pop_root,
                text="You must provide at least your name, surname or nickname",
                wraplength=240,
                justify="center",
                font='Helvetica 12 bold italic',
                fg='#c9a589',
                bg='#754c24')
            warn_lbl.pack(side="top", pady=10, fill='x')
            bt_lbl = tk.Button(
                pop_root,
                text="OK",
                font='Helvetica 16 bold',
                fg='#5b3719',
                bg='#c9a589',
                height=2,
                width=4,
                command=lambda: self.erase(pop_root))
            bt_lbl.pack(side="top", pady=20)
            return

        if root:
            root.destroy()
            on_closing()
        # print("Looking for ", user_string)
        # Add a reservoir list for found names while searching
        users_index = []
        found = 0
        # table request
        query="SELECT * FROM current WHERE name LIKE ? OR surname LIKE ? OR nickname LIKE ? OR id_badge LIKE ? "
        query_variables=(user_string,user_string,user_string,user_string)
        res=self.query_var(query,query_variables)
        found=len(res)
        for response in res:
            users_index.append(response[0])

        """    old version
        # Look for name (without caps with lower())
        # Ignore first line containing columns names
        for i in range(0, len(self.my_csv_data)):
            # Look for the user string in Surname, Name, Nickname, or badge ID /!\ For
            # NaN values, csv data is considered as a float, so cast in string if
            # empty
            if (True in [user_string.lower() == str(self.my_csv_data[i][j]).lower() for j in range(3)] or
                    user_string == str(self.my_csv_data[i][4])):
                found += 1
                users_index.append(i)
        # print("Found = ", found)"""
        if found == 0:
            # If the user is not found, interface will change depending on the identification way (ID or name)
            if VERBOSE: print("Not found")
            new_root = tk.Toplevel(self.main)
            new_root.protocol("WM_DELETE_WINDOW", lambda: [
                on_closing(), new_root.destroy()])
            on_opening()
            # set to be on top of the main window
            new_root.transient(self.main)
            # hijack all commands from the master (clicks on the main window are ignored)
            new_root.grab_set()
            new_root.title('Sorry')
            new_root['bg'] = '#754c24'
            new_root.resizable(height=False, width=False)
            sorry_lbl = tk.Label(
                new_root, text="Sorry !", font='Helvetica 22 bold', fg="white", bg='#754c24')
            sorry_lbl.pack(side="top", pady=10, fill='x')
            txt_lbl = tk.Label(
                new_root,
                text="I could not find you",
                font='Helvetica 12 bold italic',
                fg='#c9a589',
                bg='#754c24')
            txt_lbl.pack(side="top", fill='x')
            if identification == Identification.NAME:
                new_root.geometry('200x200')
                bis_bt_lbl = tk.Button(
                    new_root,
                    text="Try again",
                    font='Helvetica 12 bold',
                    fg='#5b3719',
                    bg='#c9a589',
                    height=1,
                    width=10,
                    command=lambda: self.erase_and_manual_entry(new_root))
                bis_bt_lbl.pack(side="top", pady=10)
                add_bt_lbl = tk.Button(new_root, text="Add me", font='Helvetica 12 bold', fg='#5b3719',
                                       bg='#c9a589', height=1, width=10, command=lambda: self.add_user(new_root))
                add_bt_lbl.pack(side="top")
            elif identification == Identification.BADGE:
                new_root.geometry('270x230')
                add_bt_lbl = tk.Button(new_root, text="Add me", font='Helvetica 12 bold', fg='#5b3719',
                                       bg='#c9a589', height=1, width=8, command=lambda: self.add_user(new_root))
                add_bt_lbl.pack(side="top", pady=10)
                exist_txt_lbl = tk.Label(
                    new_root,
                    text="Former user with new badge ?",
                    font='Helvetica 12 bold italic',
                    fg='white',
                    bg='#754c24')
                exist_txt_lbl.pack(side="top", pady=10, fill='x')
                bis_bt_lbl = tk.Button(
                    new_root,
                    text="Synchronize",
                    font='Helvetica 12 bold',
                    fg='#5b3719',
                    bg='#c9a589',
                    height=1,
                    width=14,
                    command=lambda: self.synchronize(
                        new_root,
                        user_string))
                bis_bt_lbl.pack(side="top")
        # If you don't want to have to confirm if only one user has been found, uncomment case found == 1
        # elif found == 1:
        #    self.found(users_index[0])
        else:
            if VERBOSE: print("I found", found, user_string)
            new_root = tk.Toplevel(self.main)
            new_root.protocol("WM_DELETE_WINDOW", lambda: [
                on_closing(), new_root.destroy()])
            on_opening()
            # set to be on top of the main window
            new_root.transient(self.main)
            # hijack all commands from the master (clicks on the main window are ignored)
            new_root.grab_set()
            # Set size + position relative to main window
            geometry = "300x" + \
                str(210 + 40 * len(res)) + "+247+120"  #users_index
            new_root.geometry(geometry)
            new_root.title('Precise')
            new_root['bg'] = '#754c24'
            new_root.resizable(height=False, width=False)
            new_lbl = tk.Label(
                new_root, text="Hello !", font='Helvetica 22 bold', fg="white", bg='#754c24')
#                 if found == 1:
#                     new_lbl.config(text = "Hello !")
#                 else:
#                     new_lbl.config(text = "Sorry !")
            new_lbl.pack(side="top", pady=10, fill='x')
            if identification == Identification.NAME:
                found_lbl = tk.Label(
                    new_root,
                    text=(
                        "I found " +
                        str(found) +
                        " " +
                        user_string),
                    font='Helvetica 14 bold',
                    fg='#c9a589',
                    bg='#754c24')
                found_lbl.pack(side="top", fill='x')
            txt_lbl = tk.Label(new_root, text="Are you... ?",
                               font='Helvetica 12 bold italic', fg='#c9a589', bg='#754c24')
            txt_lbl.pack(side="top", pady=10, fill='x')
            for i in range(0, len(res)):
                #  Create a button for each corresponding name, and send the user index depending on the clicked button
                # Warning ! When lambda is used to define the function, the call doesn't get the value of the variable i at the time the function is defined.
                # Instead, it makes a closure, which is sort of like a note to itself saying "I should look for what the value of the variable i is at the time
                # that I am called". Of course, the function is called after the loop is over, so at that time i will always be equal to the last value from the loop.
                # Using the i=i trick causes the function to store the current value of i
                # at the time lambda is defined, instead of waiting to look up the value
                # of i later.
                bt_lbl = tk.Button(new_root,
                                   text=res[i][1] +
                                   " " +
                                   res[i][2],
                                   font='Helvetica 12 bold',
                                   fg='#5b3719',
                                   bg='#c9a589',
                                   height=1,
                                   width=18,
                                   command=lambda i=i: self.erase_and_found(new_root,
                                                                            res[i][0]))
                bt_lbl.pack(side="top")
            not_you_lbl = tk.Label(
                new_root, text="It's not you ?", font='Helvetica 12 bold', fg='white', bg='#754c24')
            not_you_lbl.pack(side="top", pady=10, fill='x')
            add_bt_lbl = tk.Button(
                new_root,
                text="Add me",
                font='Helvetica 12 bold',
                fg='#5b3719',
                bg='#c9a589',
                height=1,
                width=10,
                command=lambda: self.add_user(new_root))
            add_bt_lbl.pack(side="top")


class ImageLabel(tk.Label):
    """ A class for gif animation in image label that inherits from tk Labels """

    def load(self, im):
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


if __name__ == "__main__":
    root = tk.Tk()
    on_opening()
    # Set window dimensions
    # root.geometry('800x480')
    # We choose fullscreen to hide desktop, but we need a solution to escape
    root.attributes("-fullscreen", True)
    root.geometry('800x480')
    # Bind an escape key to window destruction to escape fullscreen
    # Note: As it uses an event e, global function on_closing can't be used

    def close_main(e):
        root.destroy()

    root.bind("<Escape>", lambda e: close_main(e))
    root.title('My wonderful coffee app')
    # Set background color
    root['bg'] = '#754c24'
    # Don't allow user to change size
    root.resizable(height=False, width=False)

    # Create a Finder, the main tool for matching a user with a database
    finder = Finder('/home/pi/Documents/coffee/coffee_test.db','/home/pi/Documents/coffee/coffee_test_view.db', root)

    # Labels
    # Text labels
    txt_lbl1 = tk.Label(root, text="You should take a break...",
                        font='Helvetica 22 bold', fg="white", bg='#754c24')

    # Place the text label on the window, 10 pixels from the top, and fill the window on x
    txt_lbl1.pack(side="top", pady=10, fill='x')
    txt_lbl2 = tk.Label(root, text=f"Badge for a coffee ({COFFEE_PRICE:.2f}€)",
                        font='Helvetica 16 bold', fg='#c9a589', bg='#754c24')
    txt_lbl2.pack(side="top", fill='x')
    # Button label to manually check identity
    bt_lbl = tk.Button(root, text="Can't read my badge ?", font='Helvetica 15 bold', fg='#5b3719',
                       bg='#c9a589', height=2, width=24, command=lambda: finder.manual_entry())
    bt_lbl.pack(side="bottom", pady=20)

    # Image label. To hide border, set borderwidth and highlightthickness to 0
    lbl = ImageLabel(root, borderwidth=0, highlightthickness=0)

    lbl.pack()
    lbl.load('/home/pi/Documents/coffee/media/cup.gif')

    # Add a protocol handler to kill everything if main window is closed
    root.protocol("WM_DELETE_WINDOW", finder.stop)
    root.mainloop()
