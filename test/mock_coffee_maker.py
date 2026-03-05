import logging
import time
from datetime import datetime
from threading import Lock, Thread
from typing import Optional, List

from juracoffeemachine import CoffeeMaker, JuraCommand, Response, JuraProtocol, HZ, CS

logger = logging.getLogger(__name__)


class MockJura(JuraProtocol):
    def __init__(self):
        self.cs_list = [CS("cs:03770000000ED000000000000006000017000000000"),
                        CS("cs:03770000000ED000000000000006000017000000000"),
                        CS("cs:03770000000ED000000000000006000017000000000"),
                        CS("cs:03770000000ED000000000000006000000000000000"),
                        CS("cs:03770000000ED000000000000006000000000000000"),
                        CS("cs:03770000000ED000000000000006000000000000000"),
                        CS("cs:03770000000ED000000000000006000000000000000"),
                        CS("cs:03770000000ED000000000000006000000000000000"),
                        CS("cs:03770000000ED000000000000006000000800000000"),
                        CS("cs:03770000000ED000000000000006000000A00000000"),
                        CS("cs:03770000000ED000000000000006000000F00000000"),
                        CS("cs:03770000000ED000000000000006000011C00000000"),
                        CS("cs:03770000000ED000000000000006000011C00000000"),
                        CS("cs:03770000000ED000000000000006000011C00000000")]
        self.cs_idx = 0

        self.first_hz = True

    def set_coffee_param(self, coffee_bean: int, water_volume: int) -> bool:
        logger.info(f"setting param {coffee_bean} beans {water_volume}mL.")
        return True

    def write_with_response(self, data: str, timeout: float = 3) -> Optional[str]:
        time.sleep(1)
        logger.info(f"Writing '{data}', response will be 'ok:'")
        return "ok:"

    def get_and_parse_message(self, command: JuraCommand, raw: Optional[str] = None) -> Optional[Response]:
        time.sleep(1)
        if command == JuraCommand.CS:
            logger.info(f"Returning cs value")
            cs = self.cs_list[self.cs_idx]
            self.cs_idx = (self.cs_idx + 1) % len(self.cs_list)
            return cs
        elif command == JuraCommand.HZ:
            hz = HZ("hz:01010110000000,0288,00ED,0107,03E8,0000,0,0017,000100,12")
            if self.first_hz:
                self.first_hz = False
                hz.is_draining_tray_present = True
            else:
                hz.is_draining_tray_present = False
            return hz
        return None

    def read_eeprom(self, address: int, use_rt: bool = False) -> Optional[int]:
        return 1000


class MockCoffeeMaker(CoffeeMaker):

    def __init__(self):
        self.jura = MockJura()
        self.last_valid_contact: Optional[datetime] = None
        self.jura_version_verified: bool = True

        self.__comm_lock__ = Lock()
        self.__brew_threads__: List[Thread] = []

        self.__brewing_status__ = None

    @staticmethod
    def create_from_uart(_: str) -> CoffeeMaker:
        return MockCoffeeMaker()

    def __check_connection__(self, is_invalid: bool = False, _tries_left: int = 3) -> bool:
        time.sleep(1)
        self.__update_last_contact__()
        return True
