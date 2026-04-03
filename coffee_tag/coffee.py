"""
In this file is implemented the logic of the app.
It triggers the display of GUI and reactive depending on the user inputs.
"""
import asyncio
import logging
import os
from argparse import Namespace
from asyncio import Event
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List

from juracoffeemachine import CoffeeMaker, CoffeeStatistics

from coffee_tag.database import User, Database
from coffee_tag.gui import GeneralUI, MainGUI, ManualEntry, UserMenu, UserProperties, AskPassword, \
    BrewCoffee, Meme, AdminGUI
from coffee_tag.rfid import RFIDReader

logger = logging.getLogger(__name__)


class CoffeeManager:
    def __init__(self, db: Database, rfid: RFIDReader, coffee_maker: Optional[CoffeeMaker], args: Namespace):
        self.db = db
        self.rfid = rfid
        self.args = args
        self.coffee_maker = coffee_maker
        self.root_gui = MainGUI(self.__main_gui_callback__, self.__main_gui_create_user__, self.db.coffee_price)

        self.loop = asyncio.get_event_loop()
        asyncio.set_event_loop(self.loop)

        self.loop.create_task(self.listen_to_card_reader())
        self.loop.create_task(self.monitor_statistics())
        self.loop.create_task(self.tk_loop())

    def __main_gui_callback__(self):
        self.loop.create_task(self.manual_search_and_open_account())

    def __main_gui_create_user__(self):
        self.loop.create_task(self.add_or_update_user())

    async def __check_authentication__(self, user) -> bool:
        if self.args.no_authentication:
            return True
        result = await AskPassword(self.root_gui, self.rfid, user).get_future()
        if result is None:
            return False
        is_password, login = result
        if user.is_authorized(is_password, login):
            logger.info(f"Someone authenticate as {user} with a {'password' if is_password else 'badge'}.")
            return True
        logger.warning(f"Someone failed to authenticate as {user}"
                       f"with a {'password' if is_password else 'badge'}.")
        await GeneralUI(self.root_gui, "Wrong password!",
                        320, 300,
                        main_text="The provided password is not correct!",
                        sub_text="Please contact an admin if you're having trouble login in.",
                        sub_after_main=True,
                        button_one="Ok").get_future()
        return False

    async def tk_loop(self):
        while self.rfid.run:
            self.root_gui.tk.update()
            await asyncio.sleep(1 / 60)

    async def monitor_statistics(self) -> None:
        while not self.args.dev and self.args.monitor_delay > 0 and self.rfid.run and self.coffee_maker is not None:
            d = datetime.now()
            if d.weekday() < 5 and 7 <= d.hour <= 23:
                last_stat: List[Optional[CoffeeStatistics]] = [None]
                done = Event()

                def _cb(stat: Optional[CoffeeStatistics]):
                    if stat is not None:
                        last_stat[0] = stat
                    else:
                        logger.warning("Couldn't fetch jura's statistics")
                    done.set()

                self.coffee_maker.get_totals_statistics(cb=_cb)
                await done.wait()
                if last_stat[0] is not None:
                    self.db.save_statistics(datetime.now(tz=timezone.utc), last_stat[0])
            await asyncio.sleep(60 * (self.args.monitor_snap_delay
                                      - (datetime.now().minute % self.args.monitor_snap_delay)))

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
            should_sync = await GeneralUI(self.root_gui, "Sorry!", 350, 310,
                                          "I could not find you", main_text="Former user with new badge?",
                                          button_one="Synchronize", button_two="Add me").get_future()
            if should_sync:
                # verify access rights
                user = await self.get_user_by_manual_search()
                if user is None:
                    return None
                if await self.__check_authentication__(user):
                    self.db.sync_badge(user, card)
                    await GeneralUI(self.root_gui, title="Welcome back!",
                                    w=320, h=270,
                                    main_text="Your badge has been successfully linked to your account",
                                    button_one="Ok").get_future()
            elif should_sync is False:
                self.loop.create_task(self.add_or_update_user())
        else:
            logger.info(f"Opening {user.name} {user.surname} account.")
            self.loop.create_task(self.open_user_account(user, True))
        return None

    async def open_admin_gui(self, user: User) -> None:
        if user.permissions == "owner":
            await AdminGUI(self.root_gui, self.db.get_users()).get_future()
        return None

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

    async def check_for_meme(self, user: User) -> None:
        meme_folder = Path("~/coffee/meme/").expanduser()
        if meme_folder.exists():
            meme = [f"{meme_folder}/{name}" for name in os.listdir(meme_folder)
                    if name.startswith(f"meme{user.user_id}")]
            if len(meme) == 0:
                return None
            await Meme(self.root_gui, meme).get_future_with_autoclosing()
        return None

    async def open_user_account(self, user: User, is_authenticated: bool = False) -> None:
        # verify account status
        if user.status == "banned" and user.permissions != "owner":
            await GeneralUI(self.root_gui, "Your account is deactivated.",
                            320, 300,
                            main_text="Your account has been blocked indefinitely.",
                            sub_text="Please contact us at cafe.u2is@gmail.com.",
                            sub_after_main=True,
                            button_one="Ok").get_future()
            return None
        if user.status == "shadow_banned" and user.permissions != "owner":
            await GeneralUI(self.root_gui, "Oops...",
                            320, 300,
                            main_text="An unexpected error occurred while opening your profile!",
                            sub_text="If it is continues, please contact us at cafe.u2is@gmail.com.",
                            sub_after_main=True,
                            button_one="Ok").get_future()
            return None
        # verify access rights
        if not is_authenticated and not await self.__check_authentication__(user):
            return None
        # ask missing infos
        if user.is_valid() is not True:
            was_updated = await self.add_or_update_user(user)
            if was_updated is False or was_updated is None:
                await GeneralUI(self.root_gui, "Please update your profile.",
                                320, 250,
                                main_text="To access your account please update your profile.",
                                button_one="Ok").get_future()
                logger.warning(f"{user} avoided updating its profile.")
        if self.args.authoritative or user.user_id in ([100] if self.args.beta is None else self.args.beta):
            await self.check_for_meme(user)
            brew = BrewCoffee(self.root_gui, user,
                              self.coffee_maker.get_brewing_status,
                              user.beans_q, user.water_v)
            r = None
            while type(r) != tuple:
                self.coffee_maker.can_brew(cb=brew.can_brew_sb)
                r = await brew.get_request()
                if r == "settings":
                    self.loop.create_task(self.add_or_update_user(user))
                    return None
                if r == "admin":
                    self.loop.create_task(self.open_admin_gui(user))
                    return None
                if r is None:
                    return None
            user.beans_q, user.water_v = r
            if not user.update():
                logger.error(f"Could not save new coffee params.")
            self.coffee_maker.brew_coffee(user.beans_q, user.water_v, brew.jura_brew_cb)
            await brew.update()
            await brew.get_future_with_autoclosing()
            if brew.brew_sent_with_success:
                logger.info(f"{user} bought 1 coffees at {self.db.coffee_price} €.")
                if user.buy_coffees(1):
                    logger.info("This was saved in db.")
                else:
                    logger.error("Couldn't save in db!")

            def _cb(reset):
                logger.warning(f"Resetting param to actual default: {reset}")

            self.coffee_maker.reset_coffee_param(cb=_cb)
        else:
            coffee_bought = await UserMenu(self.root_gui, user).get_future()
            if coffee_bought is None:
                return None
            # double check when high count
            if coffee_bought > 9:
                validate = await GeneralUI(self.root_gui, "Wow, are you sure?",
                                           w=320, h=320,
                                           main_text=f"Do you confirm buying {coffee_bought} coffees?",
                                           button_one="Yes", button_two="Oops").get_future()
                if validate is None or validate is False:
                    return None
            # if coffee was bought, saves it
            if coffee_bought > 0:
                logger.info(f"{user} bought {coffee_bought} coffees at {self.db.coffee_price} €.")
                if user.buy_coffees(coffee_bought):
                    logger.info("This was saved in db.")
                    await GeneralUI(self.root_gui, title=f"Thank you {user}!",
                                    w=490, h=230,
                                    sub_text="Your balance is now",
                                    main_text=f"{-user.get_user_balance()} €",
                                    should_close_in_5=True).get_future_with_autoclosing()
                else:
                    logger.error("Couldn't save in db!")
        return None

    async def add_or_update_user(self, current_user: Optional[User] = None) -> Optional[bool]:
        valid = False
        if current_user is None:
            tmp_user = User(self.db, -1, "", "", None, None, 0,
                            None, "user", "active", None, "", None, 3, 100)
        else:
            tmp_user = current_user

        LBL_ERRORS = {
            'missing_name': ("Fill all the required field", "You must provide your name."),
            'missing_surname': ("Fill all the required field", "You must provide your surname."),
            'missing_mail': ("Fill all the required field", "You must provide your mail."),
            'missing_password': ("Fill all the required field", "You must provide your password."
                                                                " It needs to be at least 4 characters."),
            'missing_date_of_departure': ("Fill all the required field", "You must provide your date of departure."
                                                                         " Mind the format YYYY/MM/DD."),
            'mail_format': ("Your mail is not valid", "Please provide a valid mail."),
            'duplicate': ("Account already exists",
                          "An account with this name and surname or mail or badge id already exists."),
        }

        while valid is not True:
            tmp_user = await UserProperties(self.root_gui, self.rfid, current_user is None, tmp_user).get_future()
            if tmp_user is None:
                return False
            valid = tmp_user.is_valid()
            if valid is True:
                break
            error = LBL_ERRORS.get(valid, ("Unknown error", "Please check the fields of the form."))
            await GeneralUI(self.root_gui, error[0], 320, 290, main_text=error[1], button_one="Ok").get_future()
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
