"""
In this file is implemented the logic of the app.
It triggers the display of GUI and reactive depending on the user inputs.
"""
import asyncio
import logging
import os
from asyncio import Event
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, List, Tuple

from juracoffeemachine import CoffeeMaker, CoffeeStatistics

from coffee_tag.config import Config
from coffee_tag.database import User, Database
from coffee_tag.gui import GeneralUI, MainGUI, ManualEntry, UserMenu, UserProperties, AskPassword, \
    BrewCoffee, Meme, AdminGUI, AdminFeedGui, AdminJuraGui, MaintenanceScreen
from coffee_tag.rfid import RFIDReader
from mail.email import EmailManager

logger = logging.getLogger(__name__)


class CoffeeManager:
    def __init__(self, db: Database, rfid: RFIDReader, email: EmailManager, coffee_maker: Optional[CoffeeMaker],
                 config: Config):
        self.db = db
        self.rfid = rfid
        self.email = email
        self.config = config
        self.coffee_maker = coffee_maker
        self.root_gui = MainGUI(self.__main_gui_callback__, self.__main_gui_create_user__, self.db.config.price)

        self.loop = asyncio.get_event_loop()
        asyncio.set_event_loop(self.loop)

        self.loop.create_task(self.listen_to_card_reader())
        self.loop.create_task(self.monitor_statistics())
        self.loop.create_task(self.tk_loop())

    def __main_gui_callback__(self):
        self.loop.create_task(self.manual_search_and_open_account())

    def __main_gui_create_user__(self):
        self.loop.create_task(self.add_or_update_user())

    async def __check_authentication__(self, user) -> Tuple[bool, bool]:
        if not self.config.authentication:
            return True, False
        result = await AskPassword(self.root_gui, self.rfid, user).get_future()
        if result is None:
            return False, False
        is_password, login = result
        is_authorized, is_admin = user.is_authorized(is_password, login)
        if is_authorized:
            logger.info(f"Someone authenticate as {user} with a {'password' if is_password else 'badge'}.")
            return True, is_admin
        logger.warning(f"Someone failed to authenticate as {user}"
                       f" with a {'password' if is_password else 'badge'}.")
        await GeneralUI(self.root_gui, "Wrong password!",
                        320, 300,
                        main_text="The provided password is not correct!",
                        sub_text="Please contact an admin if you're having trouble login in.",
                        sub_after_main=True,
                        button_one="Ok").get_future()
        return False, False

    async def tk_loop(self):
        while self.rfid.run:
            self.root_gui.tk.update()
            await asyncio.sleep(1 / 60)

    async def __save_statistics__(self, use_power_gpio: bool):
        if self.coffee_maker is None:
            return
        last_stat: List[Optional[CoffeeStatistics]] = [None]
        done = Event()

        def _cb(stat: Optional[CoffeeStatistics]):
            if stat is not None:
                last_stat[0] = stat
            else:
                logger.warning(f"Couldn't fetch jura's statistics."
                               f" Next statistics monitoring in {self.config.monitor_snap_delay} min.")
            done.set()

        logging.getLogger("juracoffeemachine").setLevel(level=logging.FATAL)
        self.coffee_maker.get_totals_statistics(cb=_cb, use_power_gpio=use_power_gpio)
        logging.getLogger("juracoffeemachine").setLevel(level=logging.DEBUG if self.config.verbose else logging.INFO)
        await done.wait()
        if last_stat[0] is not None:
            if self.db.save_statistics(datetime.now(tz=timezone.utc), last_stat[0]):
                logger.info(f"Statistics were saved."
                            f" Next statistics monitoring in {self.config.monitor_snap_delay} min.")
            else:
                logger.info(f"An error occurred while saving statistics in db."
                            f" Next statistics monitoring in {self.config.monitor_snap_delay} min.")

    async def monitor_statistics(self) -> None:
        if self.config.dev or self.config.monitor_snap_delay <= 0 or self.coffee_maker is None:
            return None
        while self.rfid.run:
            delay = (self.config.monitor_snap_delay - (datetime.now().minute % self.config.monitor_snap_delay))
            await asyncio.sleep(60 * delay)
            d = datetime.now()
            if d.weekday() < 5:
                if 7 <= d.hour <= 20:
                    await self.__save_statistics__(False)
                elif d.hour == 23 and d.minute >= 60 - self.config.monitor_snap_delay:
                    await self.__save_statistics__(True)
        return None

    async def daily_clock(self) -> None:
        if self.config.dev:
            return None
        while self.rfid.run:
            now = datetime.now()
            next_run = now.replace(hour=7, minute=0, second=0, microsecond=0)
            if next_run <= now:
                next_run += timedelta(days=1)
            await asyncio.sleep((next_run - now).total_seconds())
            # send date of departure remainder
            for days in self.config.notification_date_of_departure_remainders:
                for user in self.db.get_user_leaving_in(days) or []:
                    if self.email.date_of_departure_remainder(user, [] if days != 1 else self.db.get_owners() or []):
                        logger.info(f"Successfully sent remainder email to {user}.")
                    else:
                        logger.warning(f"Failed to sent remainder email to {user}.")
        return None

    async def listen_to_card_reader(self) -> None:
        while self.rfid.run:
            while any(map(lambda w: w and w.is_opened(), self.root_gui.opened_popup)):
                await asyncio.sleep(1)
            self.root_gui.opened_popup = list(filter(lambda w: w and w.is_opened(), self.root_gui.opened_popup))
            card = await self.rfid.get_rfid()
            if card is None:
                continue
            if any(map(lambda w: w and w.is_opened(), self.root_gui.opened_popup)):
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
                is_authorized, _ = await self.__check_authentication__(user)
                if is_authorized:
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
        if user.is_owner():
            await AdminGUI(self.root_gui, self.db.get_users()).get_future()
        return None

    async def open_admin_feed_gui(self, user: User) -> None:
        if user.is_owner():
            await AdminFeedGui(self.root_gui, self.db.get_recent_users(), self.db.get_recent_coffees()).get_future()
        return None

    async def open_admin_jura_gui(self, user: User) -> None:
        if user.is_maintainer():
            await AdminJuraGui(self.root_gui, self.coffee_maker).get_future()
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
        # verify access rights
        signed_in_by_admin = user.is_maintainer()
        if not is_authenticated:
            is_authorized, signed_in_by_admin = await self.__check_authentication__(user)
            if not is_authorized:
                return None
        # verify account status
        if user.status == "banned" and not signed_in_by_admin:
            await GeneralUI(self.root_gui, "Your account is deactivated.",
                            320, 300,
                            main_text="Your account has been blocked indefinitely.",
                            sub_text=f"Please contact us at {self.config.contact_email}.",
                            sub_after_main=True,
                            button_one="Ok").get_future()
            return None
        if user.status == "shadow_banned" and not signed_in_by_admin:
            await GeneralUI(self.root_gui, "Oops...",
                            320, 300,
                            main_text="An unexpected error occurred while opening your profile!",
                            sub_text=f"If it is continues, please contact us at {self.config.contact_email}.",
                            sub_after_main=True,
                            button_one="Ok").get_future()
            return None
        # ask missing infos
        if user.is_valid() not in [True, "date_of_departure_in_the_past"] and not signed_in_by_admin:
            was_updated = await self.add_or_update_user(user)
            if was_updated is False or was_updated is None:
                await GeneralUI(self.root_gui, "Please update your profile.",
                                320, 250,
                                main_text="To access your account please update your profile.",
                                button_one="Ok").get_future()
                return None
        # check date_of_departure
        if (user.date_of_departure is None or user.date_of_departure <= datetime.now(tz=timezone.utc)) \
                and not signed_in_by_admin:
            await GeneralUI(self.root_gui, "Your account is deactivated.",
                            320, 300,
                            main_text="Your account is past its date of departure.",
                            sub_text=f"Please contact an admin or email us at {self.config.contact_email}.",
                            sub_after_main=True,
                            button_one="Ok").get_future()
            return None
        coffee_bought = 0
        if self.config.authoritative:
            await self.check_for_meme(user)
            brew = BrewCoffee(self.root_gui, user, self.config.price,
                              self.coffee_maker.get_brewing_status,
                              user.beans_q, user.water_v)
            r = None
            # TODO popup warning when no more coffee
            while type(r) != tuple:
                self.coffee_maker.can_brew(cb=brew.can_brew_sb)
                r = await brew.get_request()
                if r == "settings":
                    self.loop.create_task(self.add_or_update_user(user))
                    return None
                if r == "admin":
                    self.loop.create_task(self.open_admin_gui(user))
                    return None
                if r == "feed":
                    self.loop.create_task(self.open_admin_feed_gui(user))
                    return None
                if r == "jura_btn":
                    self.loop.create_task(self.open_admin_jura_gui(user))
                    return None
                if r == "maintenance":
                    self.loop.create_task(self.open_maintenance(user))
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
                coffee_bought = 1

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
            logger.info(f"{user} bought {coffee_bought} coffees at {self.db.config.price} €.")
            ceiling = self.config.debt_grace_ceiling if self.config.debt_grace_period > (
                    datetime.now(tz=timezone.utc) - user.creation_date).days else self.config.debt_default_ceiling
            for threshold in self.config.notification_balance_thresholds:
                if self.config.price >= - user.get_user_balance() - (threshold + ceiling) > 0:
                    if self.email.send_low_balance(user):
                        logger.info(f"Sent a low balance remainder to {user}.")
                    else:
                        logger.warning(f"Failed to send a low balance remainder to {user}.")
            if user.buy_coffees(coffee_bought):
                logger.info("This was saved in db.")
                if not self.config.authoritative:
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
                            None, "user", "active", None, "", None,
                            3, 100, None)
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
            'date_of_departure_in_the_past': ("Have you already left?", "You must provide your date of departure "
                                                                        "in the future."),
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
            if current_user is None:
                if self.email.registration_email(tmp_user, self.db.get_owners() or []):
                    logger.info(f"Successfully sent registration email to {tmp_user}.")
                else:
                    logger.warning(f"Failed to send registration email to {tmp_user}.")
            return True
        else:
            logger.warning(f"Error while creating profile '{tmp_user}'")
            await GeneralUI(self.root_gui, "Oops...",
                            320, 250,
                            main_text="An unexpected error occurred while creating your profile!",
                            button_one="Ok").get_future()
            return False

    async def open_maintenance(self, user: User):
        if user.is_maintainer():
            logger.info(f"{user} started the maintenance")
            user = await MaintenanceScreen(self.root_gui, self.rfid, self.db.get_user_by_rfid).get_future()
            if user is None:
                logger.info(f"The maintenance was stopped")
            else:
                logger.info(f"{user} stopped the maintenance")
                self.loop.create_task(self.open_user_account(user, True))

    def stop(self):
        self.rfid.stop()
        self.root_gui.tk.destroy()
