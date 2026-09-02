from __future__ import annotations

import csv
import io
import json
import logging
import re
import sqlite3
from datetime import datetime as dt, timezone, datetime
from typing import Callable, Optional, Tuple, Any, Literal, List, Dict

import bcrypt
from juracoffeemachine import CoffeeStatistics
from quart_auth import AuthUser

from coffee_tag.config import Config

logger = logging.getLogger(__name__)

LOSS_USER_ID = 121


class User(AuthUser):

    def __init__(self, db: Database, user_id: int, name: str, surname: str,
                 nickname: Optional[str], cascad_username: Optional[str],
                 initial_balance: float, passcode: Optional[str], permissions: str, status: str,
                 date_of_departure: Optional[str],
                 mail: str, id_badge: Optional[str],
                 beans_q: int, water_v: int, creation_date: Optional[str]):
        super().__init__(str(user_id))
        self.db: Database = db
        self.user_id: int = user_id
        self.name: str = name
        self.surname: str = surname
        self.nickname: Optional[str] = nickname
        self.cascad_username: Optional[str] = cascad_username
        self.initial_balance: Optional[float] = initial_balance
        self.passcode: Optional[str] = passcode
        self.permissions: str = permissions
        self.status: str = status
        self.date_of_departure: Optional[datetime] = (dt.strptime(date_of_departure, "%Y-%m-%d %H:%M:%S")
        .replace(
            tzinfo=timezone.utc)) if date_of_departure is not None else None
        self.mail: str = mail
        self.id_badge: Optional[str] = id_badge
        self.beans_q: int = beans_q
        self.water_v: int = water_v
        self.creation_date: datetime = dt.strptime(creation_date, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc) \
            if creation_date is not None else dt.now(tz=timezone.utc)

    @staticmethod
    def create_table(db: Database):
        def create(db: sqlite3.Cursor):
            db.execute("""
                       CREATE TABLE IF NOT EXISTS users
                       (
                           id                INTEGER primary key,
                           name              TEXT                     not null,
                           surname           TEXT                     not null,
                           nickname          TEXT,
                           cascad_username   TEXT,
                           initial_balance   real    default 0        not null,
                           passcode          TEXT,
                           permissions       TEXT    default 'user'   not null,
                           status            TEXT    default 'active' not null,
                           date_of_departure TEXT,
                           mail              TEXT                     not null,
                           id_badge          TEXT,
                           beans_q           integer default 4        not null,
                           water_v           integer default 100      not null,
                           creation_date     DATE                     not null,
                           check (permissions IN ('user', 'maintainer', 'owner')),
                           check (status IN ('active', 'banned', 'shadow_banned'))
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

    def get_coffees(self) -> Optional[List[Purchase]]:
        r = self.db.connector.execute("""
                                      SELECT id, user_id, date, nb_coffee, price
                                      FROM purchase
                                      WHERE user_id = :user
                                      ORDER BY date DESC
                                      """,
                                      {"user": self.user_id})
        if r is None:
            return None
        return [Purchase(self.db, *row[:5]) for row in r]

    def __str__(self):
        return f"{self.name} {self.surname}"

    def __repr__(self):
        return str(self)

    def is_valid(self) -> Literal[True, 'missing_name', 'missing_surname', 'missing_mail', 'missing_password',
    'missing_date_of_departure', 'date_of_departure_in_the_past', 'mail_format', 'duplicate']:
        if self.name == "":
            return "missing_name"
        if self.surname == "":
            return "missing_surname"
        if self.mail == "":
            return "missing_mail"
        if self.passcode is None:
            return "missing_password"
        if self.date_of_departure is None:
            return "missing_date_of_departure"
        if self.date_of_departure <= datetime.now(tz=timezone.utc):
            return "date_of_departure_in_the_past"
        if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', self.mail):
            return "mail_format"
        if self.db.check_duplicate(self.name, self.surname, self.mail, self.id_badge, self.user_id):
            return "duplicate"
        return True

    def register(self) -> bool:
        if self.is_valid() is not True:
            return False

        if not self.db.edit_query("INSERT INTO users (name, surname, nickname, "
                                  "cascad_username, initial_balance, passcode, permissions,"
                                  "status, date_of_departure, mail, id_badge,"
                                  "beans_q, water_v, creation_date) VALUES (:name, :surname, :nickname, :cascad,"
                                  ":initial_balance, :passcode, :permissions, :status, :date_of_departure,"
                                  ":mail, :badge, :beans_q, :water_v, DATETIME())",
                                  {"name": self.name, "surname": self.surname, "nickname": self.nickname,
                                   "cascad": self.cascad_username, "initial_balance": self.initial_balance,
                                   "passcode": self.passcode, "permissions": self.permissions, "status": self.status,
                                   "date_of_departure": self.date_of_departure.strftime("%Y-%m-%d %H:%M:%S"),
                                   "mail": self.mail, "badge": self.id_badge,
                                   "beans_q": self.beans_q, "water_v": self.water_v}):
            return False

        user = self.db.get_user_by_mail(self.mail)
        if user is None:
            return False
        self.user_id = user.user_id
        return True

    def update(self, force: bool = False) -> bool:
        if not force and self.is_valid() is not True:
            return False

        if not self.db.edit_query("UPDATE users SET "
                                  "name=:name, surname=:surname, nickname=:nickname, "
                                  "cascad_username=:cascad, initial_balance=:initial_balance, "
                                  "passcode=:passcode, permissions=:permissions,"
                                  "status=:status, date_of_departure=:date_of_departure,"
                                  "mail=:mail, id_badge=:badge, beans_q=:beans_q, water_v=:water_v "
                                  "WHERE id=:user_id",
                                  {"user_id": self.user_id,
                                   "name": self.name, "surname": self.surname, "nickname": self.nickname,
                                   "cascad": self.cascad_username, "initial_balance": self.initial_balance,
                                   "passcode": self.passcode, "permissions": self.permissions, "status": self.status,
                                   "date_of_departure": None if self.date_of_departure is None else self.date_of_departure.strftime(
                                       "%Y-%m-%d %H:%M:%S"),
                                   "mail": self.mail, "badge": self.id_badge,
                                   "beans_q": self.beans_q, "water_v": self.water_v}):
            return False
        return True

    def buy_coffees(self, coffee_bought: int, date: Optional[datetime] = None) -> bool:
        if date is None:
            return self.db.edit_query("INSERT INTO purchase (user_id, date, nb_coffee, price) VALUES"
                                      "(:user, DATETIME('now'), :coffee_bought, :price)",
                                      {"user": self.user_id,
                                       "coffee_bought": coffee_bought,
                                       "price": self.db.config.price * coffee_bought})
        else:
            return self.db.edit_query("INSERT INTO purchase (user_id, date, nb_coffee, price) VALUES"
                                      "(:user, :date, :coffee_bought, :price)",
                                      {"user": self.user_id,
                                       "coffee_bought": coffee_bought,
                                       "date": date.strftime("%Y-%m-%d %H:%M:%S"),
                                       "price": self.db.config.price * coffee_bought})

    def log_email(self, date: datetime, subject: str, template_name: str, template_args: Dict,
                  bcc: List[str], success: bool) -> bool:
        return self.db.edit_query("INSERT INTO emaillog (user_id, date, subject, template_name, template_args,"
                                  " bcc, success) VALUES (:user, :date, :subject, :template_name, :template_args,"
                                  ":bcc, :success)",
                                  {
                                      "user": self.user_id,
                                      "date": date.strftime("%Y-%m-%d %H:%M:%S"),
                                      "subject": subject,
                                      "template_name": template_name,
                                      "template_args": json.dumps(template_args),
                                      "bcc": ";".join(bcc),
                                      "success": success,
                                  })

    def delete_coffee(self, purchase_id: int) -> bool:
        return self.db.edit_query("DELETE FROM purchase WHERE id=:uid",
                                  {"uid": purchase_id})

    def is_maintainer(self) -> bool:
        return self.permissions in ["maintainer", "owner"]

    def is_owner(self) -> bool:
        return self.permissions in ["owner"]

    def is_authorized(self, is_password: bool, login: str) -> Tuple[bool, bool]:
        if is_password:
            if self.passcode is not None:
                return bcrypt.checkpw(login.encode(), self.passcode.encode()), False
            return False, False
        else:
            u = self.db.get_user_by_rfid(login)
            if u is not None:
                return self.user_id == u.user_id or u.is_maintainer(), u.is_maintainer()
        return False, False


class Purchase:

    def __init__(self, db: Database, purchase_id: int, user_id: int, date: str,
                 nb_coffee: int, price: float):
        self.db: Database = db
        self.purchase_id: int = purchase_id
        self.user_id: int = user_id
        self.date: datetime = dt.strptime(date, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        self.nb_coffee: int = nb_coffee
        self.price: float = price

    @staticmethod
    def create_table(db: Database):
        def create(db: sqlite3.Cursor):
            db.execute("""
                       CREATE TABLE IF NOT EXISTS purchase
                       (
                           id        INTEGER primary key,
                           user_id   INTEGER references users,
                           date      TEXT,
                           nb_coffee INTEGER,
                           price     REAL
                       );
                       """)

        db.exec_safely_at_once(create)

    def __str__(self):
        return f"[{self.user_id}#{self.nb_coffee}@{self.date.strftime('%Y-%m-%d %H:%M:%S')}={self.price}]"

    def __repr__(self):
        return str(self)

    def delete(self) -> bool:
        return self.db.edit_query("DELETE FROM purchase WHERE id=:uid",
                                  {"uid": self.purchase_id})

    def to_loss(self, loss_user_id: int = LOSS_USER_ID) -> bool:
        return self.db.edit_query("UPDATE purchase SET user_id = :user_id WHERE id=:uid",
                                  {"user_id": loss_user_id, "uid": self.purchase_id})


class Repayment:

    def __init__(self, db: Database, repayment_id: int, user_id: int, date: str,
                 credit: float, label: str, is_cash: int, in_balance: int):
        self.db: Database = db
        self.repayment_id: int = repayment_id
        self.user_id: int = user_id
        self.date: str = date
        self.credit: float = credit
        self.label: str = label
        self.is_cash: int = is_cash
        self.in_balance: int = in_balance

    @staticmethod
    def create_table(db: Database):
        def create(db: sqlite3.Cursor):
            db.execute("""
                       CREATE TABLE IF NOT EXISTS repayment
                       (
                           id         INTEGER primary key,
                           user_id    INTEGER references users,
                           date       TEXT,
                           credit     REAL,
                           label      TEXT,
                           is_cash    INTEGER,
                           in_balance INTEGER
                       );
                       """)

        db.exec_safely_at_once(create)


class EmailLog:

    def __init__(self, db: Database, emaillog_id: int, user_id: int, date: str,
                 subject: str, template_name: str, template_args: str, bcc: str, success: bool):
        self.db: Database = db
        self.emaillog_id: int = emaillog_id
        self.user_id: int = user_id
        self.date: str = date
        self.subject: str = subject
        self.template_name: str = template_name
        self.template_args: Dict[str, str] = json.loads(template_args)
        self.bcc: List[str] = bcc.split(";")
        self.success: bool = success

    @staticmethod
    def create_table(db: Database):
        def create(db: sqlite3.Cursor):
            db.execute("""
                       CREATE TABLE IF NOT EXISTS emaillog
                       (
                           id            INTEGER primary key,
                           user_id       INTEGER,
                           date          TEXT,
                           subject       TEXT,
                           template_name TEXT,
                           template_args TEXT,
                           bcc           TEXT,
                           success       boolean,
                           FOREIGN KEY (user_id) REFERENCES users (id)
                       );
                       """)

        db.exec_safely_at_once(create)


class Database:

    def __init__(self, config: Config):
        self.connector = sqlite3.connect(config.database)
        self.config = config

        self.create_tables()

    def create_tables(self):
        User.create_table(self)
        Purchase.create_table(self)
        Repayment.create_table(self)
        EmailLog.create_table(self)

        def create(db: sqlite3.Cursor):
            db.execute("""
                       CREATE TABLE IF NOT EXISTS jura_count
                       (
                           id              integer not null
                               constraint jura_count_pk
                                   primary key autoincrement,
                           date            date    not null,
                           tot_espresso    integer,
                           tot_2_espresso  integer,
                           tot_ristretto   integer,
                           tot_2_ristretto integer,
                           tot_coffee      integer,
                           tot_2_coffee    integer,
                           tot_special     integer
                       );
                       """)

        self.exec_safely_at_once(create)

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
            if self.config.read_only:
                self.connector.rollback()
            else:
                self.connector.commit()
            return True, c
        except self.connector.Error as e:
            logger.error(f"An error occurred will writing to the db: {e}")  # TODO check this
            self.connector.rollback()
        return False, c

    def search_by_name(self, name) -> list[User]:
        result = self.connector.execute("SELECT * FROM users "
                                        "WHERE name LIKE :name "
                                        "OR surname LIKE :name "
                                        "OR nickname LIKE :name;",
                                        {"name": f"%{name}%"})
        return [User(self, *r[:15]) for r in result] if result is not None else []

    def save_statistics(self, date: datetime, stat: CoffeeStatistics) -> bool:
        return self.edit_query("INSERT INTO jura_count (date, tot_espresso, tot_2_espresso,"
                               "tot_ristretto, tot_2_ristretto, tot_coffee, tot_2_coffee, tot_special) VALUES"
                               "(:date, :tot_espresso, :tot_2_espresso, :tot_ristretto,"
                               ":tot_2_ristretto, :tot_coffee, :tot_2_coffee, :tot_special)",
                               {"date": date.strftime("%Y-%m-%d %H:%M:%S"),
                                "tot_espresso": stat.tot_espresso, "tot_2_espresso": stat.tot_2_espresso,
                                "tot_ristretto": stat.tot_ristretto, "tot_2_ristretto": stat.tot_2_ristretto,
                                "tot_coffee": stat.tot_coffee, "tot_2_coffee": stat.tot_2_coffee,
                                "tot_special": stat.tot_special})

    def get_user_by_rfid(self, card: str):
        result = self.select_one("SELECT * FROM users "
                                 "WHERE id_badge IS NOT NULL AND id_badge LIKE :card;",
                                 {"card": card})
        return None if result is None else User(self, *list(result)[:15])

    def sync_badge(self, user, card):
        return self.edit_query("UPDATE users SET id_badge = :card "
                               "WHERE id = :user_id;",
                               {"card": card, "user_id": user.user_id})

    def check_duplicate(self, name: str, surname: str, mail: str, badge: Optional[str],
                        user_id_to_ignore: Optional[int] = None) -> bool:
        """
        Returns if any user has the same (name, surname) or mail or badge
        """
        r = self.select_one(f"SELECT id FROM users "
                            "WHERE ((name = :name AND surname = :surname) "
                            "OR  mail = :mail "
                            "OR (id_badge = :badge AND id_badge IS NOT NULL)) "
                            "AND id <> :user_id",
                            {"name": name, "surname": surname, "mail": mail, "badge": badge,
                             "user_id": user_id_to_ignore})
        return r is not None

    def get_user_by_mail(self, mail: str) -> Optional[User]:
        result = self.select_one("SELECT * FROM users "
                                 "WHERE mail = :mail",
                                 {"mail": mail})
        return None if result is None else User(self, *list(result)[:15])

    def get_user_by_id(self, user_id) -> Optional[User]:
        result = self.select_one("SELECT * FROM users "
                                 "WHERE id = :user_id",
                                 {"user_id": user_id})
        return None if result is None else User(self, *list(result)[:15])

    def get_owners(self) -> Optional[List[User]]:
        rows = self.connector.execute("SELECT * FROM users "
                                      'WHERE permissions = "owner"')
        return None if rows is None else [User(self, *list(row)[:15]) for row in rows]

    def get_user_leaving_in(self, days: int) -> Optional[List[User]]:
        rows = self.connector.execute("SELECT * FROM users "
                                      " WHERE date_of_departure - DATE() == :days",
                                      {"days": days})
        return None if rows is None else [User(self, *list(row)[:15]) for row in rows]

    def get_total_number_of_coffees(self) -> Optional[int]:
        result = self.select_one("SELECT sum(nb_coffee) FROM purchase;", {})
        return None if result is None else result[0]

    def get_last_ten_weeks_coffees(self) -> Optional[list[Tuple[str, int]]]:
        result = self.connector.execute("""SELECT strftime('Week %W - %Y', date) as week,
                                                  sum(nb_coffee)
                                           FROM purchase
                                           WHERE date >= DATE(DATE(), '-70 day')
                                           GROUP BY week;""")
        return None if result is None else list(result)

    def get_daily_counts(self, loss_user_id: int = LOSS_USER_ID) -> Optional[list[Tuple[str, str, int, int, int]]]:
        result = self.connector.execute("""
                                        WITH intervals AS (WITH counts
                                                                    AS (SELECT row_number() OVER (ORDER BY date) as rowid, *
                                                                        FROM jura_count
                                                                        WHERE TIME(date) >= "21:00:00"
                                                                          AND date > "2026-04-07 09:00:30")
                                                           SELECT j1.date                           AS start_date,
                                                                  j2.date                           AS end_date,
                                                                  (j2.tot_coffee - j1.tot_coffee) +
                                                                  2 * (j2.tot_2_coffee - j1.tot_2_coffee) +
                                                                  (j2.tot_espresso - j1.tot_espresso) +
                                                                  2 * (j2.tot_2_espresso - j1.tot_2_espresso) +
                                                                  (j2.tot_ristretto - j1.tot_ristretto) +
                                                                  2 * (j2.tot_2_ristretto - j1.tot_2_ristretto) +
                                                                  (j2.tot_special - j1.tot_special) AS delta_juracount
                                                           FROM counts AS j1
                                                                    JOIN counts AS j2 ON j1.rowid = j2.rowid - 1)
                                        SELECT i.start_date,
                                               i.end_date,
                                               COALESCE(i.delta_juracount, 0) AS brewed,
                                               COALESCE(SUM(CASE WHEN p.user_id != :loss_user_id THEN p.nb_coffee END),
                                                        0)                    AS purchased,
                                               COALESCE(SUM(CASE WHEN p.user_id = :loss_user_id THEN p.nb_coffee END),
                                                        0)                    AS loss
                                        FROM intervals i
                                                 LEFT JOIN purchase p
                                                           ON p.date > i.start_date
                                                               AND p.date <= i.end_date
                                        GROUP BY i.start_date, i.end_date
                                        ORDER BY i.start_date;
                                        """, {"loss_user_id": loss_user_id})
        return None if result is None else list(result)

    def get_error_counts(self) -> Optional[list[Tuple[str, str, int, int]]]:
        result = self.connector.execute("""
                                        WITH intervals AS (SELECT j1.date                           AS start_date,
                                                                  j2.date                           AS end_date,
                                                                  (j2.tot_coffee - j1.tot_coffee) +
                                                                  2 * (j2.tot_2_coffee - j1.tot_2_coffee) +
                                                                  (j2.tot_espresso - j1.tot_espresso) +
                                                                  2 * (j2.tot_2_espresso - j1.tot_2_espresso) +
                                                                  (j2.tot_ristretto - j1.tot_ristretto) +
                                                                  2 * (j2.tot_2_ristretto - j1.tot_2_ristretto) +
                                                                  (j2.tot_special - j1.tot_special) AS delta_juracount
                                                           FROM jura_count j1
                                                                    JOIN jura_count j2
                                                                         ON j2.id = (SELECT MIN(id)
                                                                                     FROM jura_count
                                                                                     WHERE j1.date < date
                                                                                       AND j1.date > "2026-04-07 09:00:30"))
                                        SELECT i.start_date,
                                               i.end_date,
                                               i.delta_juracount             as brewed,
                                               COALESCE(SUM(p.nb_coffee), 0) AS purchased
                                        FROM intervals i
                                                 LEFT JOIN purchase p
                                                           ON p.date > i.start_date
                                                               AND p.date <= i.end_date
                                        GROUP BY i.start_date, i.end_date
                                        HAVING purchased != delta_juracount
                                        ORDER BY i.start_date;
                                        """)
        return None if result is None else list(result)

    def get_email_logs(self) -> list[Tuple[int, int, str, str, str, str, str, bool, str]]:
        result = self.connector.execute("""
                                        SELECT emaillog.id,
                                               emaillog.user_id,
                                               CONCAT(u.name, " ", u.surname),
                                               date,
                                               subject,
                                               template_name,
                                               template_args,
                                               bcc,
                                               success
                                        FROM emaillog
                                                 JOIN users u ON u.id = emaillog.user_id
                                        ORDER BY date DESC;
                                        """)
        return list(result)

    def get_email_log(self, email_id) -> Optional[EmailLog]:
        result = self.select_one("""
                                 SELECT emaillog.id,
                                        emaillog.user_id,
                                        date,
                                        subject,
                                        template_name,
                                        template_args,
                                        bcc,
                                        success
                                 FROM emaillog
                                 WHERE emaillog.id = :email_id;
                                 """, {"email_id": email_id})
        return None if result is None else EmailLog(self, *list(result))

    def succeeded_to_resend_email(self, email_id) -> bool:
        return self.edit_query("UPDATE emaillog SET success = true "
                               "WHERE id = :email_id;",
                               {"email_id": email_id})

    async def auth_user(self, mail: str, password: str) -> Optional[User]:
        result = self.select_one("SELECT * FROM users "
                                 "WHERE mail = :mail AND mail IS NOT NULL AND passcode IS NOT NULL",
                                 {"mail": mail})
        if result is None:
            return None
        u = User(self, *list(result)[:15])
        return u if bcrypt.checkpw(password.encode(), u.passcode.encode()) else None

    def get_users_balance(self) -> list:
        r = self.connector.execute("""
                                   SELECT id,
                                          name,
                                          surname,
                                          nickname,
                                          cascad_username,
                                          initial_balance,
                                          passcode,
                                          permissions,
                                          status,
                                          creation_date,
                                          date_of_departure,
                                          mail,
                                          id_badge,
                                          beans_q,
                                          water_v,
                                          IFNULL(bought, 0)                                               as 'purchased',
                                          IFNULL(paid, 0)                                                 as 'paid',
                                          ROUND(initial_balance + IFNULL(bought, 0) - IFNULL(paid, 0), 2) as "current balance",
                                          p.last_coffee
                                   FROM users
                                            LEFT JOIN (SELECT user_id, SUM(price) AS bought, MAX(date) AS last_coffee
                                                       FROM purchase
                                                       GROUP BY user_id) as p ON p.user_id = users.id
                                            LEFT JOIN (SELECT user_id, SUM(credit) AS paid
                                                       FROM repayment
                                                       WHERE in_balance <> 0
                                                       GROUP BY user_id) as r ON r.user_id = users.id
                                   GROUP BY users.id
                                   """)
        return list(r)

    def register_new_repayment(self, userid: int, date: dt, credit: float, label: str,
                               is_cash: bool, in_balance: bool) -> bool:
        return self.edit_query("INSERT INTO repayment (user_id, date, credit, label, is_cash,"
                               "in_balance) VALUES"
                               "(:userid, :date, :credit, :label, :re, :al)",
                               {"userid": userid, "date": date.strftime("%Y-%m-%d %H:%M:%S"),
                                "credit": credit, "label": label,
                                "re": int(is_cash), "al": int(in_balance)})

    def get_repayments(self) -> list:
        r = self.connector.execute("""
                                   SELECT repayment.id,
                                          name || ' ' || surname as fullname,
                                          date,
                                          credit,
                                          label,
                                          is_cash,
                                          in_balance
                                   FROM repayment
                                            JOIN users ON repayment.user_id = users.id;
                                   """)
        return list(r)

    def delete_repayment(self, repayment_id: int) -> bool:
        return self.edit_query("DELETE FROM repayment "
                               "WHERE id = :id",
                               {"id": repayment_id})

    def get_users(self) -> Optional[List[User]]:
        r = self.connector.execute("""SELECT *
                                      FROM users;""")
        if r is None:
            return None
        return [User(self, *row[:15]) for row in r]

    def get_recent_users(self) -> Optional[List[User]]:
        r = self.connector.execute("""SELECT *
                                      FROM users
                                      ORDER BY creation_date DESC;""")
        if r is None:
            return None
        return [User(self, *row[:15]) for row in r]

    def get_recent_coffees(self) -> Optional[List[Purchase]]:
        r = self.connector.execute("""
                                   SELECT id, user_id, date, nb_coffee, price
                                   FROM purchase
                                   ORDER BY date DESC
                                   LIMIT 100;
                                   """)
        if r is None:
            return None
        return [Purchase(self, *row[:5]) for row in r]

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
                         "status", "date_of_departure", "mail", "id_badge", "purchased",
                         "paid", "current_balance", "last coffee"])
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
