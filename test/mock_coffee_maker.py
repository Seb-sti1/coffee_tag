import logging
import time
from datetime import datetime
from threading import Lock, Thread
from typing import Callable, Optional, Tuple

from juracoffeemachine import CoffeeMaker, FullStatus, JuraCommand, Response, MakerStatus, JuraProtocol

logger = logging.getLogger(__name__)


class MockCoffeeMaker(CoffeeMaker):

    def __init__(self):
        self.__status__: FullStatus = FullStatus(None, datetime.now(), MakerStatus.IDLE, -1)
        self.__brew_thread__ = None
        self.__jura_lock__ = Lock()

    def __update_maker_status__(self, new_status: MakerStatus, version_checked: bool = False):
        if self.get_last_status().maker_status == MakerStatus.NOT_CONNECTED and not version_checked:
            return
        if new_status != self.get_last_status().maker_status:
            dt = str(datetime.now() - self.get_last_status().last_maker_status_change).split('.')[0]
            logger.info(f"Status: {self.get_last_status().maker_status} -> {new_status}."
                        f"It was in the previous status for {dt}")
            self.__status__.maker_status = new_status

    def __update_brewing__(self, water_volume: float):
        self.__status__.water_volume = water_volume

    def __update_last_contact__(self):
        self.__status__.last_valid_contact = datetime.now()

    @staticmethod
    def create_from_uart(_: str) -> CoffeeMaker:
        return MockCoffeeMaker()

    def get_last_status(self) -> FullStatus:
        return self.__status__

    def test_connection(self, cb: Callable[[bool], None]):
        self.__update_maker_status__(MakerStatus.CHECKING_CONNECTION)
        self.__jura_lock__.acquire()
        if self.__brew_thread__ is not None:
            self.__brew_thread__.join()
            self.__brew_thread__ = None

        def __exec__():
            time.sleep(1)
            cb(True)
            self.__jura_lock__.release()

        self.__brew_thread__ = Thread(target=__exec__)
        self.__brew_thread__.start()

    def ping(self, command: JuraCommand, cb: Callable[[Optional[Response]], None]):
        self.__jura_lock__.acquire()
        if self.__brew_thread__ is not None:
            self.__brew_thread__.join()
            self.__brew_thread__ = None

        def __exec__():
            # TODO can also fail with cb(None)
            time.sleep(1)
            if command == JuraCommand.HZ:
                hz = JuraProtocol.get_and_parse_message(None,
                                                      command,
                                                      "hz:01010110000000,0288,00ED,0107,03E8,0000,0,0017,000000,12")
                cb(hz)
            elif command == JuraCommand.CS:
                cb(JuraProtocol.get_and_parse_message(None,
                                                      command,
                                                      "cs:0377000FF00ED000000000000006000011C00000000"))
            self.__jura_lock__.release()

        self.__brew_thread__ = Thread(target=__exec__)
        self.__brew_thread__.start()

    def brew_coffee(self, coffee_bean: int, water_volume: int, cb: Callable[[bool], None]):

        self.__jura_lock__.acquire()
        if self.__brew_thread__ is not None:
            self.__brew_thread__.join()
            self.__brew_thread__ = None

        def __exec__():
            # TODO can also fail with cb(False)
            time.sleep(0.5)
            self.__update_maker_status__(MakerStatus.BREWING)
            time.sleep(0.5)
            self.__update_last_contact__()
            time.sleep(0.5)
            self.__update_last_contact__()
            time.sleep(3)

            wv_list = [120, 120, 120, 0, 0, 0, 0, 8, 10, 15] + list(range(0, water_volume, 10))
            for wv in wv_list:
                time.sleep(1)
                self.__update_last_contact__()
                self.__update_brewing__(wv)
            self.__update_maker_status__(MakerStatus.IDLE)
            cb(True)
            self.__update_brewing__(0)
            self.__jura_lock__.release()

        self.__brew_thread__ = Thread(target=__exec__)
        self.__brew_thread__.start()

    def reset_coffee_param(self, cb: Callable[[bool], None]):
        pass

    def stop(self, cb: Callable[[bool], None]):
        pass

    def get_totals_statistics(self, cb: Callable[[Optional[Tuple[int, int, int, int, int, int, int]]], None]):
        pass
