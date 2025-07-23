import argparse
import asyncio
import logging
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
    parser.add_argument('--read-only', '-ro', action='store_true', help='Enable read only mode for the database')
    args = parser.parse_args()

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
        CoffeeManager(db, rfid)
        await website.app.run_task(host="0.0.0.0", port=8080)

    asyncio.run(asyncio_main())
    rfid.stop()


if __name__ == "__main__":
    main()
