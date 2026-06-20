import argparse
import asyncio
import json
import logging
import os
import shutil
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Tuple

from juracoffeemachine import CoffeeMaker

from coffee_tag.coffee import CoffeeManager
from coffee_tag.config import Config
from coffee_tag.database import Database
from coffee_tag.gui import show_gui, get_app_version, get_driver_version
from coffee_tag.rfid import RFIDReader
from coffee_tag.website.app import Website
from coffee_tag.mail.email import EmailManager

logger = logging.getLogger(__name__)


def setup() -> Tuple[Config, Database, RFIDReader, Website, EmailManager]:
    parser = argparse.ArgumentParser(prog="coffee_tag")
    parser.add_argument('config', default="config.json", type=Path, help='Path to the config file.')
    # prod related arguments regarding how the app should behave
    parser.add_argument('--no-authentication', action='store_true',
                        help='Should the authentication be deactivated')
    parser.add_argument('--not-authoritative', action='store_true',
                        help='It deactivates ordering via this app for all the users.')
    parser.add_argument('--verbose', '-v', action='store_true', help='Enable debug output')
    # dev related arguments
    parser.add_argument('--dev', action='store_true', help='Enable development mode')
    parser.add_argument('--debug-gui', action='store_true', help='Show all configured windows')
    parser.add_argument('--read-only', '-r', action='store_true', help='Enable read only mode for the database')
    args = parser.parse_args()
    with open(args.config) as f:
        json_content = json.load(f)
        config = Config(not args.no_authentication,
                        not args.not_authoritative,
                        args.verbose,
                        json_content["price"],
                        Path(json_content["database"]).expanduser().resolve(),
                        json_content["tty"],
                        json_content["power_gpio"],
                        json_content["monitor_snap_delay"],
                        json_content["contact_email"],
                        json_content["debt"]["default_ceiling"],
                        json_content["debt"]["grace_period"],
                        json_content["debt"]["grace_ceiling"],
                        json_content["notification"]["date_of_departure_remainders"],
                        json_content["notification"]["balance_thresholds"],
                        json_content["email"]["host"],
                        json_content["email"]["port"],
                        json_content["email"]["username"],
                        json_content["email"]["password"],
                        json_content["email"]["sender"],
                        json_content["email"]["reply_to"],
                        json_content["email"]["bcc"],
                        json_content["email"]["payment_methods"],
                        args.dev,
                        args.read_only)

    if not config.dev:
        user_home = Path("~/").expanduser()
        os.makedirs(f"{user_home}/.local/share/applications", exist_ok=True)
        if os.path.exists(f"{user_home}/.local/share/applications/coffee-tag.desktop"):
            os.remove(f"{user_home}/.local/share/applications/coffee-tag.desktop")
        shutil.copy(str(os.path.join(str(os.path.dirname(__file__)), "coffee-tag.desktop")),
                    f"{user_home}/.local/share/applications/coffee-tag.desktop")
        os.makedirs(f"{user_home}/.config/autostart/", exist_ok=True)
        if not os.path.exists(f"{user_home}/.config/autostart/coffee-tag.desktop"):
            os.symlink(f"{user_home}/.local/share/applications/coffee-tag.desktop",
                       f"{user_home}/.config/autostart/coffee-tag.desktop")
        logging.info("Desktop file was updated.")

    if args.debug_gui:
        show_gui(config)
        exit(0)

    fmt = logging.Formatter("%(levelname)s:%(asctime)s:%(name)s:%(message)s", datefmt='%Y-%m-%d %H:%M:%S')
    rotating_handler = RotatingFileHandler(config.database.parent / "debug.log", maxBytes=1048576, backupCount=5)
    rotating_handler.setFormatter(fmt)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(fmt)
    logging.getLogger("coffee_tag").setLevel(level=logging.DEBUG if config.verbose else logging.INFO)
    logging.getLogger("juracoffeemachine").setLevel(level=logging.DEBUG if config.verbose else logging.INFO)
    logging.getLogger("__main__").setLevel(level=logging.DEBUG if config.verbose else logging.INFO)
    logging.getLogger().handlers = [rotating_handler, console_handler]
    logger.info(f"PID is {os.getpid()}. App version is {get_app_version()}."
                f" Jura driver version is {get_driver_version()}.")

    db = Database(config)
    rfid = RFIDReader(config)
    website = Website(db)
    email = EmailManager(config)

    return config, db, rfid, website, email


def main():
    config, db, rfid, website, email = setup()

    async def asyncio_main():
        CoffeeManager(db, rfid, email,
                      CoffeeMaker.create_from_uart(config.tty, config.power_gpio) if not config.dev else None, config)
        await website.app.run_task(host="0.0.0.0", port=8080)

    asyncio.run(asyncio_main())
    rfid.stop()


if __name__ == "__main__":
    main()
