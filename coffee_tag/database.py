from __future__ import annotations

import logging
import sqlite3
from datetime import datetime as dt, timezone
from typing import Callable, Optional, Tuple, Any

logger = logging.getLogger(__name__)
COFFEE_PRICE = 0.25


class User:

    def __init__(self, db: Database, user_id: int,
                 name: str, surname: str, nickname: str,
                 cascad_username: str, initial_balance: float, passcode: str,
                 permissions: str, banned: int, date_of_departure: str, mail: str,
                 id_badge: str):
        self.db = db
        self.user_id = user_id
        self.name = name
        self.surname = surname
        self.nickname = nickname
        self.cascad_username = cascad_username
        self.initial_balance = initial_balance
        self.passcode = passcode
        self.permissions = permissions
        self.banned = banned != 0
        self.date_of_departure = date_of_departure,
        self.mail = mail
        self.id_badge = id_badge

    @staticmethod
    def create_table(db: Database):
        def create(db: sqlite3.Cursor):
            db.execute("""
                       create table users
                       (
                           id                INTEGER primary key,
                           name              TEXT,
                           surname           TEXT,
                           nickname          TEXT,
                           cascad_username   TEXT,
                           initial_balance   real default 0,
                           passcode          TEXT,
                           permissions       TEXT,
                           banned            INTEGER,
                           date_of_departure TEXT,
                           mail              TEXT,
                           id_badge          TEXT,
                           CHECK (permissions IN ('user', 'maintainer', 'owner'))
                       );
                       """)

        db.exec_safely_at_once(create)

    def get_user_balance(self) -> float:
        return self.db.select_one("""
                                  SELECT ROUND(initial_balance + IFNULL(bought, 0) - IFNULL(paid, 0), 2) as "balance"
                                  FROM users
                                           LEFT JOIN (SELECT user_id, SUM(price) AS bought
                                                      FROM purchase
                                                      WHERE user_id = :user
                                                      GROUP BY user_id) as p ON p.user_id = users.id
                                           LEFT JOIN (SELECT user_id, SUM(credit) AS paid
                                                      FROM repayement
                                                      WHERE user_id = :user
                                                      GROUP BY user_id) as r ON r.user_id = users.id
                                  WHERE users.id = :user
                                  """, {"user": self.user_id})[0]

    def get_last_coffee(self) -> Optional[Purchase]:
        r = self.db.select_one("""
                               SELECT id, user_id, date, nb_coffee, price
                               FROM purchase
                               WHERE user_id = :user
                               ORDER BY date DESC
                               LIMIT 1
                               """,
                               {"user": self.user_id})
        if r is None:
            return None
        return Purchase(self.db, *list(r))

    def __str__(self):
        return f"{self.name} {self.surname}"

    def __repr__(self):
        return str(self)


class Purchase:

    def __init__(self, db: Database, purchase_id: int, user_id: int, date: str,
                 nb_coffee: int, price: float):
        self.db = db
        self.purchase_id = purchase_id
        self.user_id = user_id
        self.date = dt.strptime(date, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        self.nb_coffee = nb_coffee
        self.price = price

    @staticmethod
    def create_table(db: Database):
        def create(db: sqlite3.Cursor):
            db.execute("""
                       create table purchase
                       (
                           id        INTEGER primary key,
                           user_id   INTEGER,
                           date      TEXT,
                           nb_coffee INTEGER,
                           price     REAL,
                           FOREIGN KEY (user_id) REFERENCES users (id)
                       );
                       """)

        db.exec_safely_at_once(create)


class Repayment:

    def __init__(self, db: Database, repayment_id: int, user_id: int, date: str,
                 credit: float, label: str, repayment_type: int, already_taken: int):
        self.db = db
        self.repayment_id = repayment_id
        self.user_id = user_id
        self.date = date
        self.credit = credit
        self.label = label
        self.repayment_type = repayment_type  # TODO what is this
        self.already_taken = already_taken  # TODO what is this

    @staticmethod
    def create_table(db: Database):
        def create(db: sqlite3.Cursor):
            db.execute("""
                       create table repayment
                       (
                           id             INTEGER,
                           user_id        INTEGER,
                           date           TEXT,
                           credit         REAL,
                           label          TEXT,
                           repayment_type INTEGER,
                           already_taken  INTEGER,
                           FOREIGN KEY (user_id) REFERENCES users (id)
                       );
                       """)

        db.exec_safely_at_once(create)


class Database:

    def __init__(self, path: str, read_only: bool):
        self.connector = sqlite3.connect(path)
        self.read_only = read_only

    def select_one(self, query, option) -> Optional[Any]:
        def func(c: sqlite3.Cursor):
            c.execute(query, option)

        r = self.exec_safely_at_once(func)
        if r[0]:
            r = list(r[1])
            return None if len(r) == 0 else r[0]
        return None

    def edit_query(self, query, option) -> bool:
        def func(c: sqlite3.Cursor):
            c.execute(query, option)

        return self.exec_safely_at_once(func)[0]

    def exec_safely_at_once(self, func: Callable[[sqlite3.Cursor], None]) -> Tuple[bool, sqlite3.Cursor]:
        c = self.connector.cursor()
        try:
            func(c)
            if self.read_only:
                self.connector.rollback()
            else:
                self.connector.commit()
            return True, c
        except self.connector.Error as e:
            logger.error(f"An error occurred will writing to the db:", e)  # TODO check this
            self.connector.rollback()
        return False, c

    def search_by_name(self, name) -> list[User]:
        result = self.connector.execute("SELECT id, name, surname, nickname, "
                                        "cascad_username, initial_balance, passcode,"
                                        "permissions, banned, date_of_departure, mail,"
                                        "id_badge FROM users "
                                        "WHERE name LIKE :name "
                                        "OR surname LIKE :name "
                                        "OR nickname LIKE :name;",
                                        {"name": f"%{name}%"})
        return [User(self, *r) for r in result] if result is not None else []

    def buy_coffees(self, user: User, coffee_bought: int) -> bool:
        return self.edit_query("INSERT INTO purchase (user_id, date, nb_coffee, price) VALUES"
                               "(:user, DATETIME('now'), :coffee_bought, :price)",
                               {"user": user.user_id,
                                "coffee_bought": coffee_bought,
                                "price": COFFEE_PRICE})

    def get_user_by_rfid(self, card: str):
        result = self.select_one("SELECT id, name, surname, nickname, "
                                 "cascad_username, initial_balance, passcode,"
                                 "permissions, banned, date_of_departure, mail,"
                                 "id_badge FROM users "
                                 "WHERE id_badge LIKE :card;",
                                 {"card": card})
        return None if result is None else User(self, *result)

    def sync_badge(self, user, card):
        return self.edit_query("UPDATE users SET id_badge = :card "
                               "WHERE id = :user_id;",
                               {"card": card, "user_id": user.user_id})

    def check_duplicate(self, name: str, surname: str, mail: str, badge: str):
        """
        Returns if any user has the same (name, surname) or mail or badge
        """
        r = self.select_one("SELECT id FROM users "
                            "WHERE (name = :name AND surname = :surname) OR  mail = :mail OR id_badge = :badge",
                            {"name": name, "surname": surname, "mail": mail, "badge": badge})
        return r is None

    def register_new_user(self, name: str, surname: str, nickname: str, mail: str, badge: str):
        return self.edit_query("INSERT INTO users (name, surname, nickname, "
                               "cascad_username, initial_balance, passcode, permissions,"
                               "banned, date_of_departure, mail, id_badge) VALUES"
                               "(:name, :surname, :nickname, null, 0, null, 'user', 0,"
                               "null, :mail, :badge)",
                               {"name": name, "surname": surname, "nickname": nickname, "mail": mail, "badge": badge})

    def get_user_by_mail(self, mail: str) -> Optional[User]:
        result = self.select_one("SELECT id, name, surname, nickname, "
                                 "cascad_username, initial_balance, passcode,"
                                 "permissions, banned, date_of_departure, mail,"
                                 "id_badge FROM users "
                                 "WHERE mail = :mail",
                                 {"mail": mail})
        return None if result is None else User(self, *result)
