from __future__ import annotations

import csv
import io
import logging
import sqlite3
from datetime import datetime as dt, timezone
from typing import Callable, Optional, Tuple, Any

import bcrypt
from quart_auth import AuthUser

logger = logging.getLogger(__name__)


class User(AuthUser):

    def __init__(self, db: Database, user_id: int, name: str, surname: str, nickname: str, cascad_username: str,
                 initial_balance: float, passcode: str, permissions: str, banned: int, date_of_departure: str,
                 mail: str, id_badge: str):
        super().__init__(str(user_id))
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
                                                      FROM repayment
                                                      WHERE user_id = :user
                                                        AND in_balance <> 0
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
                 credit: float, label: str, is_cash: int, in_balance: int):
        self.db = db
        self.repayment_id = repayment_id
        self.user_id = user_id
        self.date = date
        self.credit = credit
        self.label = label
        self.is_cash = is_cash
        self.in_balance = in_balance

    @staticmethod
    def create_table(db: Database):
        def create(db: sqlite3.Cursor):
            db.execute("""
                       create table repayment
                       (
                           id         INTEGER,
                           user_id    INTEGER,
                           date       TEXT,
                           credit     REAL,
                           label      TEXT,
                           is_cash    INTEGER,
                           in_balance INTEGER,
                           FOREIGN KEY (user_id) REFERENCES users (id)
                       );
                       """)

        db.exec_safely_at_once(create)


class Database:

    def __init__(self, path: str, read_only: bool, coffee_price: float):
        self.connector = sqlite3.connect(path)
        self.read_only = read_only
        self.coffee_price = coffee_price

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
                                "price": self.coffee_price * coffee_bought})

    def get_user_by_rfid(self, card: str):
        result = self.select_one("SELECT id, name, surname, nickname, "
                                 "cascad_username, initial_balance, passcode,"
                                 "permissions, banned, date_of_departure, mail,"
                                 "id_badge FROM users "
                                 "WHERE id_badge <> '' AND id_badge LIKE :card;",
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

    def get_user_by_id(self, user_id) -> Optional[User]:
        result = self.select_one("SELECT id, name, surname, nickname, "
                                 "cascad_username, initial_balance, passcode,"
                                 "permissions, banned, date_of_departure, mail,"
                                 "id_badge FROM users "
                                 "WHERE id = :user_id",
                                 {"user_id": user_id})
        return None if result is None else User(self, *result)

    def get_total_number_of_coffees(self) -> Optional[int]:
        result = self.select_one("SELECT sum(nb_coffee) FROM purchase;", {})
        return None if result is None else result[0]

    async def auth_user(self, mail: str, password: str) -> Optional[User]:
        result = self.select_one("SELECT id, name, surname, nickname, "
                                 "cascad_username, initial_balance, passcode,"
                                 "permissions, banned, date_of_departure, mail,"
                                 "id_badge FROM users "
                                 "WHERE mail = :mail AND mail IS NOT NULL AND passcode IS NOT NULL",
                                 {"mail": mail})
        if result is None:
            return None
        u = User(self, *result)
        return u if bcrypt.checkpw(password.encode(), u.passcode.encode()) else None

    def get_users_balance(self) -> Optional[list]:
        r = self.connector.execute("""
                                   SELECT id,
                                          name,
                                          surname,
                                          nickname,
                                          cascad_username,
                                          initial_balance,
                                          passcode,
                                          permissions,
                                          banned <> 0,
                                          date_of_departure,
                                          mail,
                                          id_badge,
                                          IFNULL(bought, 0)                                               as 'purchased',
                                          IFNULL(paid, 0)                                                 as 'paid',
                                          ROUND(initial_balance + IFNULL(bought, 0) - IFNULL(paid, 0), 2) as "current balance"
                                   FROM users
                                            LEFT JOIN (SELECT user_id, SUM(price) AS bought
                                                       FROM purchase
                                                       GROUP BY user_id) as p ON p.user_id = users.id
                                            LEFT JOIN (SELECT user_id, SUM(credit) AS paid
                                                       FROM repayment
                                                       WHERE in_balance <> 0
                                                       GROUP BY user_id) as r ON r.user_id = users.id
                                   GROUP BY users.id
                                   """)
        if r is None:
            return []
        return list(r)

    def register_new_repayment(self, userid: int, date: dt, credit: float, label: str,
                               is_cash: bool, in_balance: bool) -> bool:
        return self.edit_query("INSERT INTO repayment (user_id, date, credit, label, is_cash,"
                               "in_balance) VALUES"
                               "(:userid, :date, :credit, :label, :re, :al)",
                               {"userid": userid, "date": date.strftime("%Y-%m-%d %H:%M:%S"),
                                "credit": credit, "label": label,
                                "re": int(is_cash), "al": int(in_balance)})

    def get_repayments(self) -> Optional[list]:
        r = self.connector.execute("""
                                   SELECT repayment.id,
                                          CONCAT(name, ' ', surname) as fullname,
                                          date,
                                          credit,
                                          label,
                                          is_cash,
                                          in_balance
                                   FROM repayment
                                            JOIN users ON repayment.user_id = users.id;
                                   """)
        if r is None:
            return []
        return list(r)

    def delete_repayment(self, repayment_id: int) -> bool:
        return self.edit_query("DELETE FROM repayment "
                               "WHERE id = :id",
                               {"id": repayment_id})

    def export(self) -> str:
        logger.info(f"Creating a sql dump file")
        exported_sql = "\n".join(self.connector.iterdump())
        logger.info(f"Finish creating a sql dump file")
        return exported_sql

    def export_csv(self) -> str:
        logger.info(f"Creating a csv dump file")
        csv_file = io.StringIO()
        writer = csv.writer(csv_file, delimiter=',',
                            quotechar='"', quoting=csv.QUOTE_MINIMAL)
        r = self.get_users_balance()
        writer.writerow(["id", "name", "surname", "nickname", "cascad_username",
                         "initial_balance", "passcode", "permissions",
                         "banned", "date_of_departure", "mail", "id_badge", "purchased",
                         "paid", "current_balance"])
        writer.writerows(r)
        writer.writerows([[], [], []])
        r = self.connector.execute("SELECT id, user_id, date, nb_coffee, price FROM purchase")
        writer.writerow(["id", "user_id", "date", "nb_coffee", "price"])
        writer.writerows(list(r))
        writer.writerows([[], [], []])
        r = self.connector.execute(
            "SELECT id, user_id, date, credit, label, is_cash <> 0, in_balance <> 0 FROM repayment")
        writer.writerow(["id", "user_id", "date", "credit", "label", "is_cash", "in_balance"])
        writer.writerows(list(r))
        logger.info(f"Finish creating a csv dump file")
        return csv_file.getvalue()
