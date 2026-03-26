import asyncio
import logging

from coffee_tag.__main__ import setup
from coffee_tag.coffee import CoffeeManager
from test.mock_coffee_maker import MockCoffeeMaker

logger = logging.getLogger(__name__)


def main():
    args, db, rfid, website = setup()

    async def asyncio_main():
        CoffeeManager(db, rfid, MockCoffeeMaker.create_from_uart(args.tty), args)
        await website.app.run_task(host="0.0.0.0", port=8080)

    asyncio.run(asyncio_main())
    rfid.stop()


if __name__ == "__main__":
    main()
