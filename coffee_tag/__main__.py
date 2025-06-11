import argparse
import logging

from coffee_tag.coffee import CoffeeManager
from coffee_tag.database import Database
from coffee_tag.rfid import RFIDReader

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
    manager = CoffeeManager(db, rfid)
    manager.stop()


if __name__ == "__main__":
    main()
