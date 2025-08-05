import argparse
import asyncio
import logging
import os
import subprocess
import sys
from logging.handlers import RotatingFileHandler

from coffee_tag.coffee import CoffeeManager
from coffee_tag.database import Database
from coffee_tag.gui import show_gui
from coffee_tag.rfid import RFIDReader
from coffee_tag.website.app import Website

logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(prog="coffee_tag")
    parser.add_argument('price', default=0.25, type=float, help='Price of each coffee')
    parser.add_argument('path', default="coffee.db", type=str, help='Path to the db')
    parser.add_argument('--verbose', '-v', action='store_true', help='Enable debug output')
    parser.add_argument('--dev', action='store_true', help='Enable development mode')
    parser.add_argument('--debug-gui', action='store_true', help='Show all configured windows')
    parser.add_argument('--read-only', '-r', action='store_true', help='Enable read only mode for the database')
    parser.add_argument('--no-authentication', '-a', action='store_true',
                        help='Should the authentication be deactivated')
    parser.add_argument('--install-service', action='store_true',
                        help='If the service should be installed and enable')
    parser.add_argument('--uninstall-service', action='store_true',
                        help='If the service should be uninstalled')
    args = parser.parse_args()

    if (args.install_service or args.uninstall_service) and os.geteuid() != 0:
        logging.fatal("You need to run this as root to (un)install the service.")
        exit(1)

    if args.install_service:
        if not os.path.exists("/etc/systemd/system/coffee-tag.service"):
            os.symlink(os.path.join(os.path.dirname(__file__), "coffee-tag.service"),
                       "/etc/systemd/system/coffee-tag.service")
        subprocess.run(["systemctl", "daemon-reload"], check=True)
        subprocess.run(["systemctl", "enable", "coffee-tag.service"], check=True)
        subprocess.run(["systemctl", "start", "coffee-tag.service"], check=True)
        logging.info("Service was installed, the app should start soon.")
        exit(0)

    if args.uninstall_service:
        subprocess.run(["systemctl", "stop", "coffee-tag.service"], check=True)
        subprocess.run(["systemctl", "disable", "coffee-tag.service"], check=True)
        if os.path.exists("/etc/systemd/system/coffee-tag.service"):
            os.remove("/etc/systemd/system/coffee-tag.service")
        subprocess.run(["systemctl", "daemon-reload"], check=True)
        logging.info("Service was uninstalled.")
        exit(0)

    if args.debug_gui:
        asyncio.run(show_gui(args.path, args.price))
        exit(0)

    fmt = logging.Formatter("%(levelname)s:%(asctime)s:%(name)s:%(message)s", datefmt='%Y-%m-%d %H:%M:%S')
    rotating_handler = RotatingFileHandler("debug.log", maxBytes=10485760, backupCount=3)
    rotating_handler.setFormatter(fmt)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(fmt)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        handlers=[rotating_handler, console_handler])

    db = Database(args.path, args.read_only, args.price)
    rfid = RFIDReader(args.dev)
    website = Website(db)

    async def asyncio_main():
        CoffeeManager(db, rfid, args)
        await website.app.run_task(host="0.0.0.0", port=8080)

    asyncio.run(asyncio_main())
    rfid.stop()


if __name__ == "__main__":
    main()
