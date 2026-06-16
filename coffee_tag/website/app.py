import asyncio
import logging
import os
from datetime import datetime as dt, timezone

from quart import Quart, render_template, redirect, url_for, request, Response
from quart_auth import logout_user, login_required, current_user, QuartAuth, login_user, Unauthorized

from coffee_tag.database import Database, User

logger = logging.getLogger(__name__)


class Website:
    def __init__(self, db: Database):
        self.db = db
        self.app = Quart(__name__)
        self.app.secret_key = os.urandom(24)

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
            if form_type == "add_repayment":
                form_userid = form.get("user")
                form_date = dt.fromisoformat(form.get("date")) if form.get("date") != "" else dt.now(timezone.utc)
                form_credit = float(form.get("credit"))
                form_label = form.get("label")
                form_is_cash = form.get("is_cash") == "on"
                form_in_balance = form.get("in_balance") == "on"
                logger.info(f"Adding new repayment {form_userid} {form_date}"
                            f" {form_credit} {form_label} {form_is_cash} {form_in_balance}")
                returned_form_values["add_repayment"] = self.db.register_new_repayment(form_userid, form_date,
                                                                                       form_credit, form_label,
                                                                                       form_is_cash,
                                                                                       form_in_balance)
            elif form_type == "remove_repayment":
                form_repayment_id = int(form.get("repayment"))
                logger.info(f"Removing new repayment {form_repayment_id}")
                returned_form_values["remove_repayment"] = self.db.delete_repayment(form_repayment_id)

        return await render_template("admin.html.jinja",
                                     user=current_user,
                                     users=self.db.get_users_balance(),
                                     repayments=self.db.get_repayments(),
                                     daily_counts=self.db.get_daily_counts(),
                                     error_counts=self.db.get_error_counts(),
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
