from dataclasses import dataclass
from pathlib import Path
from typing import List


@dataclass
class Config:
    authentication: bool
    authoritative: bool
    verbose: bool

    price: int
    database: Path
    tty: str

    power_gpio: int
    monitor_snap_delay: int

    email_host: str
    email_port: int
    email_username: str
    email_password: str
    email_sender: str
    email_reply_to: str
    email_bcc: List[str]

    dev: bool
    read_only: bool