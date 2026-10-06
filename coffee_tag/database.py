from __future__ import annotations

import csv
import io
import json
import logging
import re
import secrets
import sqlite3
from datetime import datetime as dt, timezone, datetime
from typing import Callable, Optional, Tuple, Any, Literal, List, Dict

import bcrypt
from juracoffeemachine import CoffeeStatistics
from quart_auth import AuthUser

from coffee_tag.config import Config

logger = logging.getLogger(__name__)

SPECIAL_USER = {
    "loss": 1000000000,
    "bank": 1000000001,
    "cash": 1000000002,
    "supply": 1000000003,
}

SPECIAL_USER_LOOKUP = {v: k for k, v in SPECIAL_USER.items()}


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
    def create_table() -> Callable[[sqlite3.Cursor], None]:
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

        return create

    def get_user_balance(self) -> float:
        return self.db.select_balances("balance", user_id=self.user_id)[0][0]

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

    def get_coffees(self) -> List[Purchase]:
        r = self.db.connector.execute("""
                                      SELECT id, user_id, date, nb_coffee, price
                                      FROM purchase
                                      WHERE user_id = :user
                                      ORDER BY date DESC
                                      """,
                                      {"user": self.user_id})
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
    def create_table() -> Callable[[sqlite3.Cursor], None]:
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
            db.execute("CREATE INDEX IF NOT EXISTS idx_purchase_date ON purchase (date);")
            db.execute("CREATE INDEX IF NOT EXISTS idx_purchase_user_id ON purchase (user_id);")
            db.execute("CREATE INDEX IF NOT EXISTS idx_purchase_date_cov ON purchase (date, nb_coffee, price);")

        return create

    def __str__(self):
        return f"[{self.user_id}#{self.nb_coffee}@{self.date.strftime('%Y-%m-%d %H:%M:%S')}={self.price}]"

    def __repr__(self):
        return str(self)

    def delete(self) -> bool:
        return self.db.edit_query("DELETE FROM purchase WHERE id=:uid",
                                  {"uid": self.purchase_id})

    def to_loss(self) -> bool:
        return self.db.edit_query("UPDATE purchase SET user_id = :user_id WHERE id=:uid",
                                  {"user_id": SPECIAL_USER["loss"], "uid": self.purchase_id})


class Transfer:

    def __init__(self, db: Database, transfer_id: int, from_id: int, to_id: int, date: str, credit: float):
        self.db = db
        self.transfer_id = transfer_id
        self.from_id = from_id
        self.to_id = to_id
        self.date = dt.strptime(date, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        self.credit = credit

    @staticmethod
    def create_table() -> Callable[[sqlite3.Cursor], None]:
        def create(db: sqlite3.Cursor):
            db.execute("""
                       CREATE TABLE IF NOT EXISTS transfer
                       (
                           id      INTEGER not null
                               constraint transfer_pk primary key autoincrement,
                           from_id INTEGER references users,
                           to_id   INTEGER references users,
                           date    TEXT,
                           credit  REAL
                       );
                       """)
            db.execute("CREATE INDEX IF NOT EXISTS idx_transfer_from_id ON transfer (from_id);")
            db.execute("CREATE INDEX IF NOT EXISTS idx_transfer_to_id ON transfer (to_id);")
            db.execute("CREATE INDEX IF NOT EXISTS idx_transfer_from_date_cov ON transfer (from_id, date, id, credit);")

        return create


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
    def create_table() -> Callable[[sqlite3.Cursor], None]:
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

        return create


class Database:

    def __init__(self, config: Config):
        self.connector = sqlite3.connect(config.database)
        self.config = config

        self.create_tables()

    def create_tables(self):
        def create(db: sqlite3.Cursor):
            User.create_table()(db)
            Purchase.create_table()(db)
            Transfer.create_table()(db)
            EmailLog.create_table()(db)
            # Create jura_count
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
            db.execute("CREATE INDEX IF NOT EXISTS idx_jura_count_date ON jura_count (date);")
            # Create jura_intervals with a trigger for insert on jura_count
            db.execute("""
                       CREATE TABLE IF NOT EXISTS jura_intervals
                       (
                           id          INTEGER PRIMARY KEY REFERENCES jura_count (id),
                           start_date  TEXT    NOT NULL,
                           end_date    TEXT    NOT NULL,
                           delta_total INTEGER NOT NULL DEFAULT 0
                       );
                       """)
            db.execute("CREATE INDEX IF NOT EXISTS idx_jura_intervals_start_date ON jura_intervals (start_date);")
            db.execute("""
                       CREATE TRIGGER IF NOT EXISTS trg_jura_intervals_insert
                           AFTER INSERT
                           ON jura_count
                       BEGIN
                           INSERT OR IGNORE INTO jura_intervals (id, start_date, end_date, delta_total)
                           SELECT prev.id,
                                  prev.date,
                                  NEW.date,
                                  (NEW.tot_espresso - prev.tot_espresso)
                                      + 2 * (NEW.tot_2_espresso - prev.tot_2_espresso)
                                      + (NEW.tot_ristretto - prev.tot_ristretto)
                                      + 2 * (NEW.tot_2_ristretto - prev.tot_2_ristretto)
                                      + (NEW.tot_coffee - prev.tot_coffee)
                                      + 2 * (NEW.tot_2_coffee - prev.tot_2_coffee)
                                      + (NEW.tot_special - prev.tot_special)
                           FROM jura_count AS prev
                           WHERE prev.id = (SELECT MAX(id) FROM jura_count WHERE id < NEW.id);
                       END;
                       """)
            # Create system users
            db.execute("INSERT OR IGNORE INTO users (id, name, surname, initial_balance, passcode, permissions,"
                       "status, date_of_departure, mail, creation_date) VALUES (:user_id, 'loss', 'special',"
                       "0, :passcode, 'user', 'banned', '9999-12-31 00:00:00',"
                       ":mail, DATETIME())",
                       {"user_id": SPECIAL_USER["loss"],
                        "passcode": bcrypt.hashpw(secrets.token_urlsafe(20).encode(),
                                                  bcrypt.gensalt()).decode(),
                        "mail": self.config.contact_email})
            db.execute("INSERT OR IGNORE INTO users (id, name, surname, initial_balance, passcode, permissions,"
                       "status, date_of_departure, mail, creation_date) VALUES (1000000001, 'bank', 'special',"
                       "0, :passcode, 'user', 'banned', '9999-12-31 00:00:00',"
                       ":mail, DATETIME())",
                       {
                           "user_id": SPECIAL_USER["bank"],
                           "passcode": bcrypt.hashpw(secrets.token_urlsafe(20).encode(),
                                                     bcrypt.gensalt()).decode(),
                           "mail": self.config.contact_email})
            db.execute("INSERT OR IGNORE INTO users (id, name, surname, initial_balance, passcode, permissions,"
                       "status, date_of_departure, mail, creation_date) VALUES (1000000002, 'cash', 'special',"
                       "0, :passcode, 'user', 'banned', '9999-12-31 00:00:00',"
                       ":mail, DATETIME())",
                       {
                           "user_id": SPECIAL_USER["cash"],
                           "passcode": bcrypt.hashpw(secrets.token_urlsafe(20).encode(),
                                                     bcrypt.gensalt()).decode(),
                           "mail": self.config.contact_email})
            db.execute("INSERT OR IGNORE INTO users (id, name, surname, initial_balance, passcode, permissions,"
                       "status, date_of_departure, mail, creation_date) VALUES (1000000003, 'supply', 'special',"
                       "0, :passcode, 'user', 'banned', '9999-12-31 00:00:00',"
                       ":mail, DATETIME())",
                       {
                           "user_id": SPECIAL_USER["supply"],
                           "passcode": bcrypt.hashpw(secrets.token_urlsafe(20).encode(),
                                                     bcrypt.gensalt()).decode(),
                           "mail": self.config.contact_email})

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
                                      "WHERE permissions = 'owner'")
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

    def get_daily_counts(self, from_date: dt, to_date: dt) -> Optional[list[Tuple[str, str, int, int, int]]]:
        result = self.connector.execute("""
                                        WITH nightly AS (SELECT start_date
                                                         FROM jura_intervals
                                                         WHERE TIME(start_date) >= '21:00:00'
                                                           AND start_date > '2026-04-07 09:00:30'
                                                         UNION ALL
                                                         SELECT end_date
                                                         FROM jura_intervals
                                                         WHERE id = (SELECT MAX(id) FROM jura_intervals)
                                                           AND TIME(start_date) < '21:00:00'),
                                             bounded AS (SELECT start_date,
                                                                LEAD(start_date) OVER (ORDER BY start_date) AS next_start
                                                         FROM nightly
                                                         WHERE start_date >= :from_date
                                                           AND start_date <= :to_date),
                                             day_brewed AS (SELECT b.start_date,
                                                                   b.next_start       AS end_date,
                                                                   SUM(i.delta_total) AS brewed
                                                            FROM bounded b
                                                                     JOIN jura_intervals i
                                                                          ON i.start_date >= b.start_date AND i.start_date < b.next_start
                                                            WHERE b.next_start IS NOT NULL
                                                            GROUP BY b.start_date, b.next_start)
                                        SELECT d.start_date,
                                               d.end_date,
                                               d.brewed,
                                               COALESCE(SUM(CASE WHEN p.user_id != :loss_user_id THEN p.nb_coffee END),
                                                        0) AS purchased,
                                               COALESCE(SUM(CASE WHEN p.user_id = :loss_user_id THEN p.nb_coffee END),
                                                        0) AS loss
                                        FROM day_brewed d
                                                 LEFT JOIN purchase p ON p.date > d.start_date AND p.date <= d.end_date
                                        GROUP BY d.start_date, d.end_date
                                        ORDER BY d.start_date;
                                        """, {"loss_user_id": SPECIAL_USER["loss"],
                                              "from_date": from_date.strftime("%Y-%m-%d %H:%M:%S"),
                                              "to_date": to_date.strftime("%Y-%m-%d %H:%M:%S")})
        return None if result is None else list(result)

    def get_error_counts(self, from_date: dt, to_date: dt) -> Optional[list[Tuple[str, str, int, int]]]:
        result = self.connector.execute("""
                                        SELECT i.start_date,
                                               i.end_date,
                                               i.delta_total                 AS brewed,
                                               COALESCE(SUM(p.nb_coffee), 0) AS purchased
                                        FROM jura_intervals i
                                                 LEFT JOIN purchase p
                                                           ON p.date > i.start_date
                                                               AND p.date <= i.end_date
                                        WHERE i.start_date > '2026-04-07 09:00:30'
                                          AND i.start_date >= :from_date
                                          AND i.start_date <= :to_date
                                        GROUP BY i.start_date, i.end_date
                                        HAVING purchased != brewed
                                        ORDER BY i.start_date;
                                        """, {
                                            "from_date": from_date.strftime("%Y-%m-%d %H:%M:%S"),
                                            "to_date": to_date.strftime("%Y-%m-%d %H:%M:%S")})
        return None if result is None else list(result)

    def get_last_machine_sync(self) -> Optional[str]:
        r = self.select_one("SELECT MAX(date) FROM jura_count;", {})
        return None if r is None else r[0]

    def get_special_account_balance(self, account: Literal["bank", "cash", "loss"]) -> float:
        """Money in the bank/cash account."""
        return self.select_balances("balance", user_id=SPECIAL_USER[account])[0][0]

    def get_expense_income_intervals(self) -> list[Tuple[str, str, float, float]]:
        """Expenses and revenue per interval between two supply reimbursements"""
        result = self.connector.execute("""
                                        WITH intervals AS (SELECT date                                                             AS start_date,
                                                                  COALESCE(LEAD(date) OVER (ORDER BY date, id), CURRENT_TIMESTAMP) AS end_date,
                                                                  credit
                                                           FROM transfer
                                                           WHERE from_id = :supply_user
                                                             AND date > '2026-02-10 00:00:00')
                                        SELECT i.start_date,
                                               i.end_date,
                                               i.credit                                     AS expenses,
                                               COALESCE((SELECT SUM(p.price)
                                                         FROM purchase p
                                                         WHERE p.date > i.start_date
                                                           AND p.date <= i.end_date
                                                           AND p.user_id != :loss_user), 0) AS revenue
                                        FROM intervals i
                                        ORDER BY i.start_date;
                                        """, {"supply_user": SPECIAL_USER["supply"], "loss_user": SPECIAL_USER["loss"]})
        return list(result)

    def get_stolen_miscount(self, from_date: dt, to_date: dt) -> Tuple[int, int]:
        """(stolen, miscount) coffees over the period, clipped per day (same day bounds as get_daily_counts)."""
        rows = self.get_daily_counts(from_date, to_date) or []
        stolen = miscount = 0
        for _, _, brewed, purchased, loss in rows:
            delta = brewed - (purchased + loss)
            stolen += max(delta, 0)
            miscount += max(-delta, 0)
        return stolen, miscount

    def get_client_balance_summary(self) -> Dict[str, float]:
        """Euros owed by/to the clients. {debt_total, debt_dormant, credit_total, credit_dormant}"""
        kinds = {"debt": ("balance > 0", "balance"), "credit": ("balance < 0", "balance")}
        scopes = {"total": "", "dormant": " AND (status != 'active' OR COALESCE(last_coffee, creation_date) < DATETIME('now', '-6 months'))"}
        columns = {f"{kind}_{scope}": f"COALESCE(SUM(CASE WHEN {condition}{extra} THEN {value} END), 0)"
                   for kind, (condition, value) in kinds.items()
                   for scope, extra in scopes.items()}
        row = self.select_balances(", ".join(columns.values()), clients_only=True)[0]
        return {name: round(value, 2) for name, value in zip(columns, row)}

    def get_email_logs(self, from_date: dt, to_date: dt,
                       limit: Optional[int] = None) -> list[Tuple[int, int, str, str, str, str, str, bool, str]]:
        result = self.connector.execute("""
                                        SELECT emaillog.id,
                                               emaillog.user_id,
                                               CONCAT(u.name, ' ', u.surname),
                                               date,
                                               subject,
                                               template_name,
                                               template_args,
                                               bcc,
                                               success
                                        FROM emaillog
                                                 JOIN users u ON u.id = emaillog.user_id
                                        WHERE date >= :from_date
                                          AND date <= :to_date
                                        ORDER BY date DESC, emaillog.id DESC
                                        LIMIT COALESCE(:limit, -1);
                                        """,
                                        {
                                            "from_date": from_date.strftime("%Y-%m-%d %H:%M:%S"),
                                            "to_date": to_date.strftime("%Y-%m-%d %H:%M:%S"),
                                            "limit": limit
                                        })
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

    def select_balances(self, select: str, where: str = "1", params: Optional[Dict[str, Any]] = None, *,
                        user_id: Optional[int] = None, clients_only: bool = False,
                        order_by: Optional[str] = None) -> list:
        """Generic query on the balance of the users"""
        conditions = [where]
        params = dict(params or {})
        if clients_only:
            conditions.append("id < 1000000000")
        if user_id is not None:
            conditions.append("id = :user_id")
            params["user_id"] = user_id
        query = f"""WITH bal AS (SELECT users.*,
                   ROUND(IFNULL(p.bought, 0), 2)                                AS purchased,
                   ROUND(IFNULL(t_in.total, 0) - IFNULL(t_out.total, 0), 2)     AS paid,
                   ROUND(users.initial_balance + IFNULL(p.bought, 0)
                             - (IFNULL(t_in.total, 0) - IFNULL(t_out.total, 0)), 2) AS balance,
                   p.last_coffee
            FROM users
                     LEFT JOIN (SELECT user_id, SUM(price) AS bought, MAX(date) AS last_coffee
                                FROM purchase {"" if user_id is None else "WHERE user_id = :user_id"}
                                GROUP BY user_id) AS p ON p.user_id = users.id
                     LEFT JOIN (SELECT to_id, SUM(credit) AS total
                                FROM transfer {"" if user_id is None else "WHERE to_id = :user_id"}
                                GROUP BY to_id) AS t_in ON t_in.to_id = users.id
                     LEFT JOIN (SELECT from_id, SUM(credit) AS total
                                FROM transfer {"" if user_id is None else "WHERE from_id = :user_id"}
                                GROUP BY from_id) AS t_out ON t_out.from_id = users.id)
                SELECT {select} FROM bal WHERE {' AND '.join(f'({c})' for c in conditions)}"""
        if order_by:
            query += f" ORDER BY {order_by}"
        return list(self.connector.execute(query, params))

    def get_users_balance(self) -> list:
        return self.select_balances(("id, name, surname, nickname, cascad_username, initial_balance, passcode, "
                                     "permissions, status, creation_date, date_of_departure, mail, id_badge, "
                                     "beans_q, water_v, purchased, paid, balance, last_coffee"))

    def register_new_transfer(self, from_id: int, to_id: int, date: dt, credit: float) -> bool:
        return self.edit_query("INSERT INTO transfer (from_id, to_id, date, credit) VALUES"
                               "(:from_id, :to_id, :date, :credit)",
                               {"from_id": from_id, "to_id": to_id,
                                "date": date.strftime("%Y-%m-%d %H:%M:%S"),
                                "credit": credit})

    def get_transfers(self, from_date: dt, to_date: dt) -> List:
        results = self.connector.execute("""
                                         SELECT *
                                         FROM (SELECT transfer.id,
                                                      name || ' ' || surname as fullname,
                                                      date,
                                                      -credit,
                                                      to_id                  AS type
                                               FROM transfer
                                                        JOIN users ON transfer.from_id = users.id
                                               WHERE date >= :from_date
                                                 AND date <= :to_date
                                                 AND to_id in (:bank_user, :cash_user, :supply_user)
                                               UNION ALL
                                               SELECT transfer.id,
                                                      name || ' ' || surname as fullname,
                                                      date,
                                                      credit,
                                                      from_id                AS type
                                               FROM transfer
                                                        JOIN users ON transfer.to_id = users.id
                                               WHERE date >= :from_date
                                                 AND date <= :to_date
                                                 AND from_id in (:bank_user, :cash_user, :supply_user))
                                         ORDER BY date DESC
                                         """, {
                                             "bank_user": SPECIAL_USER["bank"],
                                             "cash_user": SPECIAL_USER["cash"],
                                             "supply_user": SPECIAL_USER["supply"],
                                             "from_date": from_date.strftime("%Y-%m-%d %H:%M:%S"),
                                             "to_date": to_date.strftime("%Y-%m-%d %H:%M:%S")
                                         })
        return [(r[0], r[1], r[2], r[3], SPECIAL_USER_LOOKUP[r[4]]) for r in results]

    def delete_transfer(self, transfer_id: int) -> bool:
        return self.edit_query("DELETE FROM transfer "
                               "WHERE id = :id",
                               {"id": transfer_id})

    def get_users(self) -> List[User]:
        r = self.connector.execute("""SELECT *
                                      FROM users;""")
        return [User(self, *row[:15]) for row in r]

    def select_users(self, where: str = "1", params: Optional[Dict[str, Any]] = None,
                     order_by: Optional[str] = None) -> List[User]:
        """Generic `SELECT * FROM users WHERE {where} ORDER BY {order_by}`. The sql arguments are never from a request."""
        query = f"SELECT * FROM users WHERE {where}" + (f" ORDER BY {order_by}" if order_by else "")
        return [User(self, *row[:15]) for row in self.connector.execute(query, params or {})]

    def get_users_leaving(self, from_days: int = 0, to_days: int = 30) -> List[User]:
        """Users whose departure date is between today + from_days and today + to_days (both included)."""
        return self.select_users("DATE(date_of_departure) BETWEEN DATE('now', :start) AND DATE('now', :end)",
                                 {"start": f"{from_days:+d} days", "end": f"{to_days:+d} days"},
                                 order_by="date_of_departure")

    def get_recent_users(self, within_days: Optional[int] = None, clients_only: bool = False) -> List[User]:
        """Users, newest first. Optionally only the ones created in the last `within_days` days."""
        conditions, params = ["1"], {}
        if within_days is not None:
            conditions.append("creation_date >= DATETIME('now', :window)")
            params["window"] = f"-{within_days} days"
        if clients_only:
            conditions.append("id < 1000000000")
        return self.select_users(" AND ".join(conditions), params, order_by="creation_date DESC")

    def get_recent_coffees(self) -> List[Purchase]:
        r = self.connector.execute("""
                                   SELECT id, user_id, date, nb_coffee, price
                                   FROM purchase
                                   ORDER BY date DESC
                                   LIMIT 100;
                                   """)
        return [Purchase(self, *row[:5]) for row in r]

    def get_purchases(self, from_date: dt, to_date: dt) -> list:
        r = self.connector.execute("""
                                   SELECT p.id,
                                          u.name,
                                          u.surname,
                                          p.user_id,
                                          p.date,
                                          p.nb_coffee,
                                          p.price
                                   FROM purchase p
                                            JOIN users u ON u.id = p.user_id
                                   WHERE p.date >= :from_date
                                     AND p.date <= :to_date
                                   ORDER BY p.date DESC;
                                   """, {
                                       "from_date": from_date.strftime("%Y-%m-%d %H:%M:%S"),
                                       "to_date": to_date.strftime("%Y-%m-%d %H:%M:%S")
                                   })
        return list(r)

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
        # r = self.connector.execute(
        #     "SELECT id, user_id, date, credit, label, is_cash <> 0, in_balance <> 0 FROM repayment")
        # writer.writerow(["id", "user_id", "date", "credit", "label", "is_cash", "in_balance"])
        # writer.writerows(list(r))
        # TODO redo export_csv. if possible with automagic stuff.
        logger.info(f"Finish creating a csv dump file")
        return csv_file.getvalue()
