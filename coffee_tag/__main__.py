import argparse
import asyncio
import logging

from coffee_tag.coffee import CoffeeManager
from coffee_tag.database import Database
from coffee_tag.rfid import RFIDReader
from coffee_tag.website.app import Website

logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--verbose', '-v', action='store_true', help='Enable debug output')
    parser.add_argument('--dev', action='store_true', help='Enable development mode')
    parser.add_argument('--read-only', '-ro', action='store_true', help='Enable read only mode for the database')
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG)

    db = Database("coffee_test.db", args.read_only)
    rfid = RFIDReader(args.dev)
    website = Website(db)

    async def asyncio_main():
        CoffeeManager(db, rfid)
        await website.app.run_task(host="0.0.0.0", port=8080)

    asyncio.run(asyncio_main())
    rfid.stop()


if __name__ == "__main__":
    main()
