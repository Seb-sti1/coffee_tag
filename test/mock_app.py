import argparse
import asyncio
import logging
import sys
from pathlib import Path

from coffee_tag.coffee import CoffeeManager
from coffee_tag.database import Database
from coffee_tag.gui import show_gui
from coffee_tag.rfid import RFIDReader
from coffee_tag.website.app import Website
from test.mock_coffee_maker import MockCoffeeMaker

logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(prog="coffee_tag")
    parser.add_argument('price', default=0.25, type=float, help='Price of each coffee')
    parser.add_argument('path', default="coffee.db", type=Path, help='Path to the db')
    parser.add_argument('--tty', default="/dev/ttyUSB0", type=str,
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
    parser.add_argument('--beta', '-b', action="append", type=int,
                        help="List of account that are beta testers")
    args = parser.parse_args()
    path = Path(args.path).expanduser()

    if args.install_autoboot or args.uninstall_autoboot:
        exit(0)

    if args.debug_gui:
        show_gui(str(path), args.price)
        exit(0)

    fmt = logging.Formatter("%(levelname)s:%(asctime)s:%(name)s:%(message)s", datefmt='%Y-%m-%d %H:%M:%S')
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(fmt)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        handlers=[console_handler])

    db = Database(str(path), args.read_only, args.price)
    rfid = RFIDReader(args.dev)
    website = Website(db)

    async def asyncio_main():
        CoffeeManager(db, rfid, MockCoffeeMaker.create_from_uart(args.tty), args)
        await website.app.run_task(host="0.0.0.0", port=8080)

    asyncio.run(asyncio_main())
    rfid.stop()


if __name__ == "__main__":
    main()
