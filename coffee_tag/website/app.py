import asyncio
import logging
import os
from datetime import datetime as dt, timezone, timedelta
from typing import List, Tuple, Optional

from jinja2 import select_autoescape
from quart import Quart, render_template, redirect, url_for, request, Response
from quart_auth import logout_user, login_required, current_user, QuartAuth, login_user, Unauthorized

from coffee_tag.database import Database, User, SPECIAL_USER
from coffee_tag.mail.email import EmailManager

logger = logging.getLogger(__name__)


def parse_date_params(r) -> Tuple[Optional[dt], Optional[dt]]:
    from_str = r.args.get("from")
    to_str = r.args.get("to")
    try:
        from_date = dt.strptime(from_str, "%Y-%m-%d").replace(tzinfo=timezone.utc) if from_str else None
    except ValueError:
        from_date = None
    try:
        to_date = dt.strptime(to_str, "%Y-%m-%d").replace(tzinfo=timezone.utc) if to_str else None
    except ValueError:
        to_date = None
    return from_date, to_date


class Website:
    def __init__(self, db: Database, email: EmailManager):
        self.db = db
        self.email = email
        self.app = Quart(__name__)
        self.app.secret_key = os.urandom(24)

        # autoescape files by default
        self.app.jinja_env.autoescape = select_autoescape(
            enabled_extensions=('html', 'xml', 'jinja'),
        )
        # cookie_secure=False allow authentication to work on non local ips
        self.auth_manager = QuartAuth(self.app, cookie_secure=False)

        self.app.add_url_rule("/", view_func=self.index)
        self.app.add_url_rule("/login", view_func=self.login, methods=["GET", "POST"])
        self.app.add_url_rule("/logout", view_func=self.logout)
        self.app.add_url_rule("/admin", view_func=login_required(self.admin), methods=["GET", "POST"])
        self.app.add_url_rule("/user", view_func=login_required(self.user))
        self.app.add_url_rule("/api/user_data/<int:user_id>", view_func=self.api_user_data)
        self.app.add_url_rule("/api/last_coffee/<badge>", view_func=self.api_last_coffee)
        self.app.add_url_rule("/export_sql", view_func=login_required(self.export_sql))
        self.app.add_url_rule("/export_csv", view_func=login_required(self.export_csv))
        self.app.register_error_handler(Unauthorized, f=lambda _: redirect(url_for("login")))

    def check_is_admin(self):
        if current_user is None:
            return redirect(url_for("login"))
        user = self.db.get_user_by_id(int(current_user.auth_id))
        if user is None:
            return redirect(url_for("login"))
        if user.permissions != "owner":
            return "Forbidden", 403
        return user

    async def index(self):
        total_coffees = self.db.get_total_number_of_coffees()
        last_coffee_totals = self.db.get_last_ten_weeks_coffees()
        return await render_template("index.html.jinja",
                                     total_coffees=total_coffees,
                                     last_coffee_totals=last_coffee_totals)

    async def login(self):
        if request.method == "POST":
            form = await request.form
            username = form.get("mail")
            password = form.get("password")
            user = await self.db.auth_user(username, password)
            if user is not None:
                login_user(user)
                return redirect(url_for("admin" if user.permissions == "owner" else "user"))
        return await render_template("login.html")

    async def logout(self):
        logout_user()
        return redirect(url_for("index"))

    async def admin(self):
        user = self.check_is_admin()
        if type(user) != User:
            return user
        returned_form_values = {}
        if request.method == "POST":
            form = await request.form
            form_type = form.get("type")
            if form_type == "add_transfer":
                form_userid = form.get("user", type=int)
                form_date = form.get("date", default=dt.now(timezone.utc), type=dt.fromisoformat)
                form_credit = form.get("credit", type=float)
                form_type_userid = form.get("transfer_type", type=lambda v: int(SPECIAL_USER[v]))
                form_dir = form.get("direction", default=False,
                                    type=lambda v: v if v in ["u2is_to_client", "client_to_u2is"] else None)
                if form_userid is not None and form_credit is not None \
                        and form_type_userid is not None and form_dir is not None:
                    logger.info(f"Adding new transfer {form_userid} {form_date} {form_credit} {form_type} {form_dir}.")
                    from_id = form_type_userid if form_dir == "u2is_to_client" else form_userid
                    to_id = form_userid if form_dir == "u2is_to_client" else form_type_userid
                    returned_form_values["add_transfer"] = self.db.register_new_transfer(from_id, to_id,
                                                                                         form_date, form_credit)
            elif form_type == "remove_transfer":
                form_transfer_id = form.get("transfer", type=int)
                if form_transfer_id is None:
                    returned_form_values["remove_transfer"] = False
                else:
                    logger.info(f"Removing new transfer {form_transfer_id}")
                    returned_form_values["remove_transfer"] = self.db.delete_transfer(form_transfer_id)
            elif form_type == "resend_email":
                form_email_id = form.get("email", type=int)
                returned_form_values["resend_email"] = form_email_id is None
                if form_email_id is not None:
                    returned_form_values["resend_email"] = True
                    asyncio.get_event_loop().create_task(self.email.resend_email(self.db, form_email_id))
            elif form_type == "send_email":
                form_subject = form.get("subject", type=str)
                form_content = form.get("content", type=str)
                form_ids: List[int] = form.getlist("ids", int)
                if form_subject is None or form_content is None or len(form_ids) == 0:
                    returned_form_values["send_email"] = False
                else:
                    async def _send_all():
                        for user_id in form_ids:
                            recipient = self.db.get_user_by_id(user_id)
                            if recipient is None:
                                logger.error("Recipient does not exists anymore.")
                            else:
                                self.email.generic_notification(recipient, form_subject, form_content)

                    asyncio.get_event_loop().create_task(_send_all())
                    returned_form_values["send_email"] = True

        # get the selected period
        from_date, to_date = parse_date_params(request)
        from_date = (from_date or dt.now(timezone.utc) - timedelta(weeks=4))
        to_date = (to_date or dt.now(timezone.utc))
        return await render_template("admin.html.jinja",
                                     user=current_user,
                                     users=self.db.get_users_balance(),
                                     transfers=self.db.get_transfers(from_date, to_date),
                                     emails=self.db.get_email_logs(from_date, to_date),
                                     daily_counts=self.db.get_daily_counts(from_date, to_date),
                                     error_counts=self.db.get_error_counts(from_date, to_date),
                                     purchases=self.db.get_purchases(from_date, to_date),
                                     filter_from=from_date.strftime("%Y-%m-%d"),
                                     filter_to=to_date.strftime("%Y-%m-%d"),
                                     returned_form_values=returned_form_values)

    async def export_sql(self):
        user = self.check_is_admin()
        if type(user) != User:
            return user
        return Response(
            self.db.export(),
            mimetype='text/plain',
            headers={"Content-Disposition": f"attachment;filename=coffee{dt.now(timezone.utc).date().isoformat()}.sql"}
        )

    async def export_csv(self):
        user = self.check_is_admin()
        if type(user) != User:
            return user
        return Response(
            self.db.export_csv(),
            mimetype='text/plain',
            headers={"Content-Disposition": f"attachment;filename=coffee{dt.now(timezone.utc).date().isoformat()}.csv"}
        )

    async def user(self):
        return "Not Implemented", 501
        # return await render_template("user.html", user=current_user)

    async def api_user_data(self, user_id):
        if request.authorization:
            user = await self.db.auth_user(request.authorization.username, request.authorization.password)
            if user is not None:
                if user.user_id == user_id or user.permissions == "owner":
                    query = self.db.get_user_by_id(user_id)
                    if query is not None:
                        last_coffee = query.get_last_coffee()
                        return {
                            "user_id": user_id,
                            "name": query.name,
                            "surname": query.surname,
                            "last_coffee_date": None if last_coffee is None else last_coffee.date,
                            "balance": -query.get_user_balance()
                        }, 200
                    else:
                        return "Not found", 404
                else:
                    return "Wrong username or password", 403
            else:
                return "Wrong username or password", 401
        return "You need to authenticate your request", 401

    async def api_last_coffee(self, badge):
        if request.authorization:
            user = await self.db.auth_user(request.authorization.username, request.authorization.password)
            if user is not None:
                if user.permissions == "owner":
                    query = self.db.get_user_by_rfid(badge)
                    if query is not None:
                        last_coffee = query.get_last_coffee()
                        return {
                            "user_id": query.user_id,
                            "name": query.name,
                            "surname": query.surname,
                            "last_coffee_date": None if last_coffee is None else last_coffee.date,
                            "balance": -query.get_user_balance()
                        }, 200
                    else:
                        return "Not found", 404
                else:
                    return "Wrong username or password", 403
            else:
                return "Wrong username or password", 401
        return "You need to authenticate your request", 401

    def start(self):
        asyncio.run(self.app.run_task(host="0.0.0.0", port=8080))
