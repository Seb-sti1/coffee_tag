"""
In this file is implemented the logic of the app.
It triggers the display of GUI and reactive depending on the user inputs.
"""
import asyncio
import logging
import re
from typing import Optional

from coffee_tag.database import User, Database, COFFEE_PRICE
from coffee_tag.gui import OneButtonPopup, ChooseUserPopup, UserNotFoundPopup, ManualEntryPopup, MainGUI, UserMenuPopup, \
    AskConfirmationPopup, ThanksPopup, AddNewUserPopup
from coffee_tag.rfid import RFIDReader

logger = logging.getLogger(__name__)


class CoffeeManager:
    def __init__(self, db: Database, rfid: RFIDReader):
        self.db = db
        self.rfid = rfid
        self.root_gui = MainGUI(self)
        self.rfid_can_open_menu = True

        self.loop = asyncio.get_event_loop()
        asyncio.set_event_loop(self.loop)

        self.loop.create_task(self.listen_to_card_reader())
        self.loop.create_task(self.tk_loop())

    async def tk_loop(self):
        while True:
            self.root_gui.tk.update()
            await asyncio.sleep(1 / 60)

    async def listen_to_card_reader(self) -> None:
        while self.rfid.run:
            while any(map(lambda w: w and w.winfo_exists(), self.root_gui.opened_popup)):
                await asyncio.sleep(1)
            self.root_gui.opened_popup = list(filter(lambda w: w and w.winfo_exists(), self.root_gui.opened_popup))
            card = await self.rfid.get_rfid()
            if card is None or any(map(lambda w: w and w.winfo_exists(), self.root_gui.opened_popup)):
                logger.info(f"GUI already opened ignoring tag {card}...")
                continue
            else:
                logger.info(f"Read rfid tag {card}...")
                self.loop.create_task(self.get_user_by_rfid_and_open_account(card))

    async def get_user_by_rfid_and_open_account(self, card: str) -> None:
        user = self.db.get_user_by_rfid(card)
        if user is None:
            logger.info(f"No user account with badge {card}.")
            action = await UserNotFoundPopup(self.root_gui, True)
            if action == "sync_badge":
                user = await self.get_user_by_manual_search()
                if user is not None:
                    self.db.sync_badge(user, card)
                    await OneButtonPopup(self.root_gui, "Welcome back!",
                                         "Your badge has been successfully linked to your account",
                                         "Ok")
            elif action == "try_again":
                logger.error(f"Returned try_again action in get_user_by_rfid_and_open_account: this is not possible")
                self.loop.create_task(self.manual_search_and_open_account())
            elif action == "add_new_user":
                self.loop.create_task(self.add_new_user())
        else:
            logger.info(f"Opening {user.name} {user.surname} account.")
            self.loop.create_task(self.open_user_account(user))

    async def get_user_by_manual_search(self) -> Optional[User]:
        users = None
        while users is None:
            user_input = await ManualEntryPopup(self.root_gui)
            if user_input is None:
                return None
            elif user_input == "":
                await OneButtonPopup(self.root_gui,
                                     title="Missing name",
                                     message="Well...\nYou must provide at least your name, surname or nickname",
                                     button_msg="Ok")
            else:
                logger.info(f"Searching for users by name '{user_input}'")
                users = self.db.search_by_name(user_input)

        if len(users) == 0:
            action = await UserNotFoundPopup(self.root_gui, False)
            if action == "sync_badge":
                logger.error(f"Returned syn_badge action in get_user_by_manual_search: this is not possible")
            elif action == "try_again":
                return await self.get_user_by_manual_search()
            elif action == "add_new_user":
                self.loop.create_task(self.add_new_user())
        else:
            logger.info(f"Found {len(users)}: {', '.join([str(u) for u in users])}")
            user = await ChooseUserPopup(self.root_gui, users)
            if user == "add_user":
                self.loop.create_task(self.add_new_user())
            else:
                return user
        return None

    async def manual_search_and_open_account(self) -> None:
        user = await self.get_user_by_manual_search()
        if user is None:
            return None
        logger.info(f"Opening {user.name} {user.surname} account.")
        self.loop.create_task(self.open_user_account(user))
        return None

    async def open_user_account(self, user: User) -> None:
        coffee_bought = await UserMenuPopup(self.root_gui, user)
        if coffee_bought is None:
            return None
        if coffee_bought > 9:
            validate = await AskConfirmationPopup(self.root_gui, "Wow, are you sure?",
                                                  f"Do you confirm buying {coffee_bought} coffee?")
            if validate is None or validate is False:
                return None
        logger.info(f"{user} bought {coffee_bought} coffees at {COFFEE_PRICE} €.")
        if self.db.buy_coffees(user, coffee_bought):
            logger.info("This was saved in db.")
            await ThanksPopup(self.root_gui, user)
        else:
            logger.error("Couldn't save in db!")
        return None

    async def add_new_user(self) -> None:
        valid = False
        name, surname, nickname, mail, badge = "", "", "", "", ""
        while not valid:
            user_info = await AddNewUserPopup(self.root_gui, self.rfid, name, surname, nickname, mail, badge)
            if user_info is None:
                return None
            name, surname, nickname, mail, badge = user_info
            if name == "" or surname == "" or mail == "":
                await OneButtonPopup(self.root_gui, "Fill all the required field.",
                                     "You must provide at least your name, surname and mail.",
                                     "Ok")
            elif not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', mail):
                await OneButtonPopup(self.root_gui, "Your mail is not valid.",
                                     "Please provide a valid mail.",
                                     "Ok")
            elif not self.db.check_duplicate(name, surname, mail, badge):
                await OneButtonPopup(self.root_gui, "Account already exists.",
                                     "An account with this name and surname or mail or badge id already exists.",
                                     "Ok")
            else:
                valid = True
        logger.info(f"Creating profile '{name}' '{surname}' '{nickname}' '{mail}' '{badge}'")
        self.db.register_new_user(name, surname, nickname, mail, badge)
        user = self.db.get_user_by_mail(mail)
        if user is not None:
            await OneButtonPopup(self.root_gui, f"Welcome {str(user)}!",
                                 "Your profile is now created!",
                                 "Ok")
        else:
            await OneButtonPopup(self.root_gui, f"Oops...",
                                 "An unexpected error occurred while creating your profile!",
                                 "Ok")
        return None

    def stop(self):
        self.rfid.stop()
        self.root_gui.tk.destroy()
