"""
In this file is implemented the logic of the app.
It triggers the display of GUI and reactive depending on the user inputs.
"""
import asyncio
import logging
import re
from typing import Optional

from coffee_tag.database import User, Database
from coffee_tag.gui import GeneralUI, MainGUI, ManualEntry, UserMenu, AddNewUser, AdminStatus
from coffee_tag.rfid import RFIDReader

logger = logging.getLogger(__name__)


class CoffeeManager:
    def __init__(self, db: Database, rfid: RFIDReader):
        self.db = db
        self.rfid = rfid
        self.root_gui = MainGUI(self.__main_gui_callback__,
                                self.db.coffee_price)
        self.rfid_can_open_menu = True

        self.loop = asyncio.get_event_loop()
        asyncio.set_event_loop(self.loop)

        self.loop.create_task(self.listen_to_card_reader())
        self.loop.create_task(self.tk_loop())

    def __main_gui_callback__(self):
        self.loop.create_task(self.manual_search_and_open_account())

    async def tk_loop(self):
        while True:
            self.root_gui.tk.update()
            await asyncio.sleep(1 / 60)

    async def listen_to_card_reader(self) -> None:
        while self.rfid.run:
            while any(map(lambda w: w and w.is_opened(), self.root_gui.opened_popup)):
                await asyncio.sleep(1)
            self.root_gui.opened_popup = list(filter(lambda w: w and w.is_opened(), self.root_gui.opened_popup))
            card = await self.rfid.get_rfid()
            if card is None:
                continue
            if any(map(lambda w: w and w.is_opened(), self.root_gui.opened_popup)):
                logger.info(f"GUI already opened ignoring tag {card}...")
                continue
            else:
                logger.info(f"Read rfid tag {card}...")
                self.loop.create_task(self.get_user_by_rfid_and_open_account(card))

    async def get_user_by_rfid_and_open_account(self, card: str) -> None:
        user = self.db.get_user_by_rfid(card)
        if user is None:
            logger.info(f"No user account with badge {card}.")
            should_sync = await GeneralUI(self.root_gui, "Sorry!", 350, 290,
                                          "I could not find you", "Former user with new badge?",
                                          "Synchronize", "Add me").get_future()
            if should_sync:
                user = await self.get_user_by_manual_search()
                if user is not None:
                    self.db.sync_badge(user, card)
                    await GeneralUI(self.root_gui, "Welcome back!",
                                    260, 200,
                                    main_text="Your badge has been successfully linked to your account",
                                    button_one="Ok").get_future()
            elif should_sync is False:
                self.loop.create_task(self.add_new_user())
        else:
            logger.info(f"Opening {user.name} {user.surname} account.")
            self.loop.create_task(self.open_user_account(user))

    async def get_user_by_manual_search(self) -> Optional[User]:
        user = await ManualEntry(self.root_gui, self.db.search_by_name).get_future()
        if user is None:
            return None
        if type(user) == str:
            if user == "add_user":
                self.loop.create_task(self.add_new_user())
            return None
        return user

    async def manual_search_and_open_account(self) -> None:
        user = await self.get_user_by_manual_search()
        if user is None:
            return None
        logger.info(f"Opening {user.name} {user.surname} account.")
        self.loop.create_task(self.open_user_account(user))
        return None

    async def open_user_account(self, user: User) -> None:
        admin_status = None
        if user.permissions == "owner":
            admin_status = AdminStatus(self.root_gui, self.db.get_last_coffees())
        coffee_bought = await UserMenu(self.root_gui, user).get_future()
        if admin_status is not None:
            admin_status.close()
            await admin_status.get_future()
        if coffee_bought is None:
            return None
        if coffee_bought > 9:
            validate = await GeneralUI(self.root_gui, "Wow, are you sure?",
                                       260, 250,
                                       main_text=f"Do you confirm buying {coffee_bought} coffee?",
                                       button_one="Yes", button_two="Oops").get_future()
            if validate is None or validate is False:
                return None
        logger.info(f"{user} bought {coffee_bought} coffees at {self.db.coffee_price} €.")
        if self.db.buy_coffees(user, coffee_bought):
            logger.info("This was saved in db.")
            await GeneralUI(self.root_gui, f"Thank you {user}!", 320, 230, "Your balance is now",
                            f"{-user.get_user_balance()} €",
                            should_close_in_5=True).get_future_with_autoclosing()
        else:
            logger.error("Couldn't save in db!")
        return None

    async def add_new_user(self) -> None:
        valid = False
        name, surname, nickname, mail, badge = "", "", "", "", ""
        while not valid:
            user_info = await AddNewUser(self.root_gui, self.rfid, name, surname, nickname, mail, badge).get_future()
            if user_info is None:
                return None
            name, surname, nickname, mail, badge = user_info
            if name == "" or surname == "" or mail == "":
                await GeneralUI(self.root_gui, "Fill all the required field.",
                                320, 250,
                                main_text="You must provide at least your name, surname and mail.",
                                button_one="Ok").get_future()
            elif not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', mail):
                await GeneralUI(self.root_gui, "Your mail is not valid.",
                                320, 250,
                                main_text="Please provide a valid mail.",
                                button_one="Ok").get_future()
            elif not self.db.check_duplicate(name, surname, mail, badge):
                await GeneralUI(self.root_gui, "Account already exists.",
                                320, 250,
                                main_text="An account with this name and surname or mail or badge id already exists.",
                                button_one="Ok").get_future()
            else:
                valid = True
        logger.info(f"Creating profile '{name}' '{surname}' '{nickname}' '{mail}' '{badge}'")
        self.db.register_new_user(name, surname, nickname, mail, badge)
        user = self.db.get_user_by_mail(mail)
        if user is not None:
            await GeneralUI(self.root_gui, f"Welcome {str(user)}!",
                            320, 250,
                            main_text="Your profile is now created!",
                            button_one="Ok").get_future()
        else:
            await GeneralUI(self.root_gui, "Oops...",
                            320, 250,
                            main_text="An unexpected error occurred while creating your profile!",
                            button_one="Ok").get_future()
        return None

    def stop(self):
        self.rfid.stop()
        self.root_gui.tk.destroy()
