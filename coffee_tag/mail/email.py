import datetime
import logging
import os
import smtplib
from email.mime.text import MIMEText
from typing import List, Optional

from jinja2 import Template

from coffee_tag.config import Config
from coffee_tag.database import User
from coffee_tag.mail import template

logger = logging.getLogger(__name__)


class EmailManager:

    def __init__(self, config: Config):
        self.config = config

    @staticmethod
    def __get_template__(name: str) -> Template:
        filepath = os.path.join(os.path.dirname(template.__file__), f"{name}.html.jinja")
        with open(filepath) as f:
            return Template(f.read())

    def __send_email__(self, subject: str, template_name: str, recipient: User,
                       bcc: Optional[List[str]] = None, **kwargs) -> bool:
        if self.config.dev:
            logger.warning(f"Dev mode activated. Mail {subject}, {template_name}, {kwargs} not sent to {recipient}")
            return True
        all_bcc = []
        if self.config.email_bcc is not None:
            all_bcc += self.config.email_bcc
        if bcc is not None:
            all_bcc += bcc
        with smtplib.SMTP(self.config.email_host, self.config.email_port) as server:
            server.starttls()
            if self.config.email_username is not None and self.config.email_password is not None:
                server.login(self.config.email_username, self.config.email_password)
            try:
                html_content = self.__get_template__(template_name).render(**kwargs)
                msg = MIMEText(html_content, "html")
                msg["Subject"] = subject
                msg["From"] = self.config.email_sender
                msg["To"] = recipient.mail
                if self.config.email_reply_to is not None:
                    msg["Reply-To"] = self.config.email_reply_to
                if len(all_bcc) > 0:
                    msg['Bcc'] = all_bcc
                server.send_message(msg)
                logger.info(f"Sending a mail to '{recipient.mail}' with template '{template_name}'.")
                result = True
            except:
                logger.warning(f"Error will sending to '{recipient.mail}'")
                result = False
            recipient.log_email(datetime.datetime.now(), subject, template_name, kwargs, all_bcc, result)
            return result

    def send_low_balance(self, user: User) -> bool:
        return self.__send_email__("Low balance on the U2IS coffee machine", "low_balance",
                                   user,
                                   name=f"{user.name} {user.surname}",
                                   balance=float(-user.get_user_balance()),
                                   default_ceiling=self.config.debt_default_ceiling,
                                   payment_methods=self.config.email_payment_methods)

    def registration_email(self, user: User, admins: List[User]) -> bool:
        return self.__send_email__("Your registration on the U2IS coffee machine", "registration",
                                   user,
                                   [u.mail for u in admins],
                                   name=f"{user.name} {user.surname}",
                                   balance=float(-user.get_user_balance()),
                                   grace_period=self.config.debt_grace_period,
                                   grace_ceiling=self.config.debt_grace_ceiling,
                                   default_ceiling=self.config.debt_default_ceiling,
                                   date_of_departure=user.date_of_departure.strftime("%Y-%m-%d"),
                                   payment_methods=self.config.email_payment_methods)

    def date_of_departure_remainder(self, user: User, admins: List[User]) -> bool:
        return self.__send_email__("Message from the U2IS Team before you leave", "departure",
                                   user,
                                   [u.mail for u in admins],
                                   name=f"{user.name} {user.surname}",
                                   date_of_departure=user.date_of_departure.strftime("%Y-%m-%d"),
                                   balance=float(-user.get_user_balance()),
                                   payment_methods=self.config.email_payment_methods)
