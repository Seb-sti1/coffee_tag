import argparse
import asyncio
import logging
import os
import subprocess
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from juracoffeemachine import CoffeeMaker

from coffee_tag.coffee import CoffeeManager
from coffee_tag.database import Database
from coffee_tag.gui import show_gui
from coffee_tag.rfid import RFIDReader
from coffee_tag.website.app import Website

logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(prog="coffee_tag")
    parser.add_argument('price', default=0.25, type=float, help='Price of each coffee')
    parser.add_argument('path', default="coffee.db", type=Path, help='Path to the db')
    parser.add_argument('tty', default="/dev/ttyUSB0", type=str,
                        help='Path to the tty of the machin\'s uart')
    parser.add_argument('--verbose', '-v', action='store_true', help='Enable debug output')
    parser.add_argument('--dev', action='store_true', help='Enable development mode')
    parser.add_argument('--debug-gui', action='store_true', help='Show all configured windows')
    parser.add_argument('--read-only', '-r', action='store_true', help='Enable read only mode for the database')
    parser.add_argument('--no-monitor', action='store_true', help='Don\'t monitor jura machine.')
    parser.add_argument('--no-authentication', '-a', action='store_true',
                        help='Should the authentication be deactivated')
    parser.add_argument('--install-autoboot', action='store_true',
                        help='To ensure the app starts at boot')
    parser.add_argument('--uninstall-autoboot', action='store_true',
                        help='To disable autoboot')
    args = parser.parse_args()
    path = Path(args.path).expanduser()
    user_home = Path("~/").expanduser()

    if args.install_autoboot:
        if not os.path.exists(f"{user_home}/.local/share/applications/coffee-tag.desktop"):
            os.makedirs(f"{user_home}/.local/share/applications", exist_ok=True)
            os.symlink(os.path.join(os.path.dirname(__file__), "coffee-tag.desktop"),
                       f"{user_home}/.local/share/applications/coffee-tag.desktop")
        if not os.path.exists(f"{user_home}/.config/autostart/coffee-tag.desktop"):
            os.makedirs(f"{user_home}/.config/autostart/", exist_ok=True)
            os.symlink(os.path.join(os.path.dirname(__file__), "coffee-tag.desktop"),
                       f"{user_home}/.config/autostart/coffee-tag.desktop")
        subprocess.run(["gtk-launch", "coffee-tag"])
        logging.info("Desktop file was installed, the app should start at boot.")
        exit(0)

    if args.uninstall_autoboot:
        if os.path.exists(f"{user_home}/.local/share/applications/coffee-tag.desktop"):
            os.remove(f"{user_home}/.local/share/applications/coffee-tag.desktop")
        if os.path.exists(f"{user_home}/.config/autostart/coffee-tag.desktop"):
            os.remove(f"{user_home}/.config/autostart/coffee-tag.desktop")
        logging.info("Desktop file was uninstalled.")
        exit(0)

    if args.debug_gui:
        show_gui(str(path), args.price)
        exit(0)

    fmt = logging.Formatter("%(levelname)s:%(asctime)s:%(name)s:%(message)s", datefmt='%Y-%m-%d %H:%M:%S')
    rotating_handler = RotatingFileHandler(path.parent / "debug.log", maxBytes=10485760, backupCount=3)
    rotating_handler.setFormatter(fmt)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(fmt)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        handlers=[rotating_handler, console_handler])

    db = Database(str(path), args.read_only, args.price)
    rfid = RFIDReader(args.dev)
    website = Website(db)

    async def asyncio_main():
        CoffeeManager(db, rfid, args)
        await website.app.run_task(host="0.0.0.0", port=8080)

    asyncio.run(asyncio_main())
    rfid.stop()


if __name__ == "__main__":
    main()
