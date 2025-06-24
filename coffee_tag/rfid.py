import asyncio
import logging
import threading
from asyncio import Future
from typing import Optional

logger = logging.getLogger(__name__)


class RFIDReader:

    def __init__(self, dev_mode: bool):
        self.dev_mode = dev_mode
        if not self.dev_mode:
            from coffee_tag.pn532 import PN532_I2C
            self.pn532 = PN532_I2C(debug=False, reset=20, req=16)
            ic, ver, rev, support = self.pn532.get_firmware_version()
            logger.info(f"Found PN532 with firmware version: {ver, rev}")
            self.pn532.SAM_configuration()
            logger.info(f"Ready to read RFID/NFC card...")
        else:
            logger.info("Running in development mode, NFC reader not available. Use the console to simulate RFID tags.")

        self.run = True
        self.future: Optional[Future] = None
        self.timeout = 10
        self.thread = threading.Thread(target=self.read_tag_thread)
        self.thread.start()

    def read_tag_thread(self):
        while self.run:
            if self.dev_mode:
                card = input("card tag:")
            else:
                try:
                    card = self.pn532.read_passive_target(timeout=self.timeout)
                except Exception as e:
                    logger.exception(f"Error while reading tag {e}")
                    card = None
            if self.future is not None and not self.future.done() and card is not None:
                self.future.set_result(str(card))

    def get_rfid(self) -> Future[str]:
        if self.future is not None and not self.future.done():
            self.future.set_result(None)
        self.future = asyncio.get_event_loop().create_future()
        return self.future

    def stop(self):
        if self.future is not None and not self.future.done():
            self.future.set_result(None)
        self.run = False
        self.thread.join()
