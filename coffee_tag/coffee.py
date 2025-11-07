"""
In this file is implemented the logic of the app.
It triggers the display of GUI and reactive depending on the user inputs.
"""
import asyncio
import datetime
import logging
import time
from argparse import Namespace
from typing import Optional, Union

from juracoffeemachine import CoffeeMaker, JuraCommand

from coffee_tag.database import User, Database
from coffee_tag.gui import GeneralUI, MainGUI, ManualEntry, UserMenu, UserProperties, AdminStatus, AskPassword, \
    BrewCoffee
from coffee_tag.rfid import RFIDReader

logger = logging.getLogger(__name__)


class CoffeeManager:
    def __init__(self, db: Database, rfid: RFIDReader, args: Namespace):
        self.db = db
        self.rfid = rfid
        self.args = args
        self.coffee_maker: CoffeeMaker = CoffeeMaker.create_from_uart(self.args.tty)
        self.root_gui = MainGUI(self.__main_gui_callback__,
                                self.db.coffee_price)
        self.rfid_can_open_menu = True
        self.next_ping_to_machine: Optional[Union[JuraCommand.HZ, JuraCommand.CS]] = JuraCommand.HZ
        self.statistics_were_log: bool = False

        self.loop = asyncio.get_event_loop()
        asyncio.set_event_loop(self.loop)

        self.loop.create_task(self.listen_to_card_reader())
        self.loop.create_task(self.monitor_machine())
        self.loop.create_task(self.tk_loop())

    def __main_gui_callback__(self):
        self.loop.create_task(self.manual_search_and_open_account())

    async def tk_loop(self):
        while True:
            self.root_gui.tk.update()
            await asyncio.sleep(1 / 60)

    async def monitor_machine(self) -> None:
        while self.rfid.run and not self.args.no_monitor:
            date = datetime.datetime.now()
            if 7 <= date.hour <= 20:
                self.statistics_were_log = False  # reset for next night
                if self.coffee_maker is not None and self.next_ping_to_machine == JuraCommand.HZ:
                    msg = self.coffee_maker.ping(JuraCommand.HZ)
                    if msg is not None:
                        logger.debug(f"{msg.raw}: {msg}")
                    else:
                        logger.warning("No message returned for HZ")
                    self.next_ping_to_machine = JuraCommand.CS
                elif self.coffee_maker is not None and self.next_ping_to_machine == JuraCommand.CS:
                    msg = self.coffee_maker.ping(JuraCommand.CS)
                    if msg is not None:
                        logger.debug(f"{msg.raw}: {msg}")
                    else:
                        logger.warning("No message returned for CS")
                    self.next_ping_to_machine = JuraCommand.HZ
                await asyncio.sleep(60)
            # else: # TODO fix is in driver
            #     if self.coffee_maker is not None and date.hour == 0 and not self.statistics_were_log:
            #         self.statistics_were_log = True
            #         self.coffee_maker.log_statistics()
            #     await asyncio.sleep(20 * 60)

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
                                          "I could not find you", main_text="Former user with new badge?",
                                          button_one="Synchronize", button_two="Add me").get_future()
            if should_sync:  # TODO security vulnerability
                user = await self.get_user_by_manual_search()
                if user is not None:
                    self.db.sync_badge(user, card)
                    await GeneralUI(self.root_gui, "Welcome back!",
                                    260, 200,
                                    main_text="Your badge has been successfully linked to your account",
                                    button_one="Ok").get_future()
            elif should_sync is False:
                self.loop.create_task(self.add_or_update_user())
        else:
            logger.info(f"Opening {user.name} {user.surname} account.")
            self.loop.create_task(self.open_user_account(user, True))

    async def get_user_by_manual_search(self) -> Optional[User]:
        user = await ManualEntry(self.root_gui, self.db.search_by_name).get_future()
        if user is None:
            return None
        if type(user) == str:
            if user == "add_user":
                self.loop.create_task(self.add_or_update_user())
            return None
        return user

    async def manual_search_and_open_account(self) -> None:
        user = await self.get_user_by_manual_search()
        if user is None:
            return None
        logger.info(f"Opening {user.name} {user.surname} account.")
        self.loop.create_task(self.open_user_account(user))
        return None

    async def open_user_account(self, user: User, is_authenticated: bool = False) -> None:
        # before anything else ask missing infos
        if user.is_valid() is not True:
            was_updated = await self.add_or_update_user(user)
            if was_updated is False or was_updated is None:
                await GeneralUI(self.root_gui, "Please update your profile.",
                                320, 250,
                                main_text="To access your account please update your profile.",
                                button_one="Ok").get_future()
                logger.warning(f"{user} avoided updating its profile.")
        # verify account status
        if user.status == "banned":
            await GeneralUI(self.root_gui, "Your account is deactivated.",
                            320, 250,
                            main_text="Your account has been blocked indefinitely.",
                            sub_text="Please contact us at cafe.u2is@gmail.com.",
                            sub_after_main=True,
                            button_one="Ok").get_future()
            return None
        if user.status == "shadow_banned":
            await GeneralUI(self.root_gui, "Oops...",
                            320, 250,
                            main_text="An unexpected error occurred while opening your profile!",
                            sub_text="If it is continues, please contact us at cafe.u2is@gmail.com.",
                            sub_after_main=True,
                            button_one="Ok").get_future()
            return None
        # verify access rights
        if not is_authenticated and not self.args.no_authentication:
            result = await AskPassword(self.root_gui, self.rfid, user).get_future()
            if result is None:
                return None
            is_password, login = result
            if not user.is_authorized(is_password, login):
                logger.warning(f"Someone failed to authenticate as {user}"
                               f"with a {'password' if is_password else 'badge'}.")
                await GeneralUI(self.root_gui, "Wrong password!",
                                320, 250,
                                main_text="The provided password is not correct!",
                                sub_text="Please contact an admin if you're having trouble login in.",
                                sub_after_main=True,
                                button_one="Ok").get_future()
                return None
            logger.info(f"Someone authenticate as {user} with a {'password' if is_password else 'badge'}.")
        # show admin ui for admin
        admin_status = None
        if user.permissions == "owner":
            admin_status = AdminStatus(self.root_gui, self.db.get_last_coffees())
        if user.user_id == 100:
            self.next_ping_to_machine = False
            param = await BrewCoffee(self.root_gui,
                                     f"Last contact {time.time() - self.coffee_maker.status[0]}s ago."
                                     f" {self.coffee_maker.status[1]}.").get_future()
            if param is not None:
                coffee_bean, water_volume = param
                logger.warning(f"Sending command c {coffee_bean}, w {water_volume}")
                self.coffee_maker.brew_coffee(coffee_bean, water_volume)
                await asyncio.sleep(10)  # TODO check timing
            self.next_ping_to_machine = JuraCommand.HZ
        # show account ui for everyone
        coffee_bought = await UserMenu(self.root_gui, user).get_future()
        if user.user_id == 100:
            logger.info(f"Resetting param to actual default: {self.coffee_maker.reset_coffee_param()}")
        if admin_status is not None:
            admin_status.close()
            await admin_status.get_future()
        if coffee_bought is None:
            return None
        # double check when high count
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
                            main_text=f"{-user.get_user_balance()} €",
                            should_close_in_5=True).get_future_with_autoclosing()
        else:
            logger.error("Couldn't save in db!")
        return None

    async def add_or_update_user(self, current_user: Optional[User] = None) -> Optional[bool]:
        valid = False
        if current_user is None:
            tmp_user = User(self.db, -1, "", "", None, None, 0,
                            None, "user", "active", None, "", None)
        else:
            tmp_user = current_user

        while valid is not True:
            tmp_user = await UserProperties(self.root_gui, self.rfid, current_user is None, tmp_user).get_future()
            if tmp_user is None:
                return False
            valid = tmp_user.is_valid()
            if valid == "missing_field":
                await GeneralUI(self.root_gui, "Fill all the required field.",
                                320, 250,
                                main_text="You must provide at least your name, surname, mail, passcode"
                                          " and date of departure.",
                                button_one="Ok").get_future()
            elif valid == "mail_format":
                await GeneralUI(self.root_gui, "Your mail is not valid.",
                                320, 250,
                                main_text="Please provide a valid mail.",
                                button_one="Ok").get_future()
            elif valid == "duplicate":
                await GeneralUI(self.root_gui, "Account already exists.",
                                320, 250,
                                main_text="An account with this name and surname or mail or badge id already exists.",
                                button_one="Ok").get_future()
        if (current_user is None and tmp_user.register()) or (current_user is not None and tmp_user.update()):
            logger.info(f"Creating profile '{tmp_user}'" if current_user is None else f"Updating profile '{tmp_user}'")
            await GeneralUI(self.root_gui, f"Welcome {str(tmp_user)}!",
                            320, 250,
                            main_text="Your profile is now created!" if current_user is None \
                                else "Your profile was updated!",
                            button_one="Ok").get_future()
            return True
        else:
            logger.warning(f"Error while creating profile '{tmp_user}'")
            await GeneralUI(self.root_gui, "Oops...",
                            320, 250,
                            main_text="An unexpected error occurred while creating your profile!",
                            button_one="Ok").get_future()
            return False

    def stop(self):
        self.rfid.stop()
        self.root_gui.tk.destroy()
