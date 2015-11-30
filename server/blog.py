#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright 2009 Facebook
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import datetime
import bcrypt
import concurrent.futures
import MySQLdb
import markdown
import os.path
import re
import subprocess
import torndb
import tornado.escape
from tornado import gen
import tornado.httpserver
import tornado.ioloop
import tornado.options
import tornado.web
import unicodedata

from log import DEBUG_LOG, ERROR_LOG
from tornado.options import define, options

define("port", default=8080, help="run on the given port", type=int)
define("mysql_host", default="127.0.0.1:3306", help="blog database host")
define("mysql_database", default="grownshare", help="blog database name")
define("mysql_user", default="root", help="blog database user")
define("mysql_password", default="nbgrown", help="blog database password")


# A thread pool to be used for password hashing with bcrypt.
executor = concurrent.futures.ThreadPoolExecutor(2)

theme_map = {"1":"名人传记", "2": "个人成长", "3": "深度君", "4": "其他"}

class Application(tornado.web.Application):
    def __init__(self):
        handlers = [
                (r"/", HomeHandler),
                (r"/archive", ArchiveHandler),
                (r"/feed", FeedHandler),
                (r"/entry/([^/]+)", EntryHandler),
                (r"/compose", ComposeHandler),
                (r"/auth/create", AuthCreateHandler),
                (r"/auth/login", AuthLoginHandler),
                (r"/auth/logout", AuthLogoutHandler),
                (r"/blog", BlogHandler),
                (r"/theme/([^/]+)", ThemeHandler),
                (r"/author/([^/]+)", AuthorHandler),
                ]
        settings = dict(
                blog_title=u"Grown Share",
                template_path=os.path.join(os.path.dirname(__file__), "templates"),
                static_path=os.path.join(os.path.dirname(__file__), "static"),
                ui_modules={"Entry": EntryModule, "EntryHome": EntryHomeModule},
                xsrf_cookies=True,
                cookie_secret="__TODO:_GENERATE_YOUR_OWN_RANDOM_VALUE_HERE__",
                login_url="/auth/login",
                debug=True,
                )
        super(Application, self).__init__(handlers, **settings)
        # Have one global connection to the blog DB across all handlers
        self.db = torndb.Connection(
                host=options.mysql_host, database=options.mysql_database,
                user=options.mysql_user, password=options.mysql_password, time_zone="+08:00")

        self.db_conn_user = torndb.Connection(
                host=options.mysql_host, database=options.mysql_database,
                user=options.mysql_user, password=options.mysql_password, time_zone="+08:00")
        self.db_conn_view = torndb.Connection(
                host=options.mysql_host, database=options.mysql_database,
                user=options.mysql_user, password=options.mysql_password, time_zone="+08:00")
        self.maybe_create_tables()

    def maybe_create_tables(self):
        try:
            self.db.get("SELECT COUNT(*) from entries;")
        except MySQLdb.ProgrammingError:
            subprocess.check_call(['mysql',
                '--host=' + options.mysql_host,
                '--database=' + options.mysql_database,
                '--user=' + options.mysql_user,
                '--password=' + options.mysql_password],
                stdin=open('schema.sql'))

class BaseHandler(tornado.web.RequestHandler):
    @property
    def db(self):
        return self.application.db

    @property
    def db_conn_user(self):
        return self.application.db_conn_user

    @property
    def db_conn_view(self):
        return self.application.db_conn_view

    def get_current_user(self):
        user_id = self.get_secure_cookie("blogdemo_user")
        if not user_id: return None
        return self.db_conn_user.get("SELECT id,email,name,hashed_password FROM authors WHERE id = %s", int(user_id))

    def any_author_exists(self):
        return bool(self.db_conn_user.get("SELECT id FROM authors LIMIT 1"))

    def get_user_name(self, user_id):
        if user_id:
            result = self.db_conn_user.get("SELECT name FROM authors WHERE id = %s", int(user_id))
            return result['name']

    def get_view_count(self, entry_id):
        if entry_id:
            result = self.db_conn_view.get("SELECT SUM(view_count) FROM entry_view WHERE entry_id = %s", int(entry_id))
            if not result['SUM(view_count)']:
                return 0;
            return result['SUM(view_count)']

    def set_view_count(self, entry_id):
        if entry_id:
            try:
                self.db_conn_view.execute(
                        "INSERT INTO entry_view (entry_id, pond, view_count) VALUES (%s,FLOOR(0+(RAND()*4)),1)"
                        "ON DUPLICATE KEY UPDATE `view_count`=`view_count`+1"
                        , entry_id)
            except Exception as e:
                DEBUG_LOG('update entry_view failed:%s' % (str(e)))

class HomeHandler(BaseHandler):
    def get(self):
        order = self.get_argument('order', 1)
        entries = self.db.query("SELECT id,author_id,theme,title,markdown,html,published FROM entries "
                                "ORDER BY published DESC LIMIT 50")

        if not entries:
            self.redirect("/compose")
            return
        for entry in entries:
            entry['published'] = datetime.datetime.strftime(entry['published'], '%Y-%m-%d %H:%M')
            entry['author'] = self.get_user_name(entry['author_id'])
            entry['view_count'] = self.get_view_count(entry['id'])
            entry['theme_name'] = theme_map.get(entry['theme'])
            entry['abstract'] = entry['markdown'][:150]
        if 2 == int(order):
            entries.sort(key=lambda x:x['view_count'], reverse=True)
        self.render("home.html", entries=entries)

class ThemeHandler(BaseHandler):
    def get(self, theme=None):
        if theme:
            entries = self.db.query("SELECT id,author_id,theme,title,markdown,html,published FROM entries WHERE theme=%s ORDER BY published DESC LIMIT 50", int(theme))
        else:
            entries = self.db.query("SELECT id,author_id,theme,title,markdown,html,published FROM entries ORDER BY published DESC LIMIT 50")

        if not entries:
            self.redirect("/compose")
            return
        for entry in entries:
            entry['published'] = datetime.datetime.strftime(entry['published'], '%Y-%m-%d %H:%M')
            entry['author'] = self.get_user_name(entry['author_id'])
            entry['view_count'] = self.get_view_count(entry['id'])
            entry['theme_name'] = theme_map.get(entry['theme'])
            entry['abstract'] = entry['markdown'][:150]

        self.render("home.html", entries=entries)

class AuthorHandler(BaseHandler):
    def get(self, author_id=None):
        if author_id:
            entries = self.db.query("SELECT id,author_id,theme,title,markdown,html,published FROM entries "
                                "WHERE author_id=%s ORDER BY published DESC LIMIT 50", int(author_id))
        else:
            entries = self.db.query("SELECT id,author_id,theme,title,markdown,html,published FROM entries "
                                "ORDER BY published DESC LIMIT 50")

        if not entries:
            self.redirect("/compose")
            return
        for entry in entries:
            entry['published'] = datetime.datetime.strftime(entry['published'], '%Y-%m-%d %H:%M')
            entry['author'] = self.get_user_name(entry['author_id'])
            entry['view_count'] = self.get_view_count(entry['id'])
            entry['theme_name'] = theme_map.get(entry['theme'])
            entry['abstract'] = entry['markdown'][:150]

        self.render("home.html", entries=entries)

class BlogHandler(BaseHandler):
    def get(self):
        self.render("blog.htm")

class EntryHandler(BaseHandler):
    def get(self, story_id):
        entry = self.db.get("SELECT id,author_id,theme,title,markdown,html,published FROM entries "
                            "WHERE id = %s", int(story_id))
        if not entry:
            raise tornado.web.HTTPError(404)
        entry['theme_name'] = theme_map.get(entry['theme'])
        entry['author'] = self.get_user_name(entry['author_id'])
        entry['view_count'] = self.get_view_count(int(story_id)) + 1
        entry['published'] = datetime.datetime.strftime(entry['published'], '%Y-%m-%d %H:%M')
        self.set_view_count(int(story_id))
        self.render("entry.html", entry=entry)

class ArchiveHandler(BaseHandler):
    def get(self):
        entries = self.db.query("SELECT id, author_id, theme, title, published FROM entries ORDER BY published "
                "DESC")
        for entry in entries:
            entry['published'] = datetime.datetime.strftime(entry['published'], '%Y-%m-%d %H:%M')
            entry['author'] = self.get_user_name(entry['author_id'])
            entry['view_count'] = self.get_view_count(entry['id'])
            entry['theme_name'] = theme_map.get(entry['theme'])
        self.render("archive.html", entries=entries)


class FeedHandler(BaseHandler):
    def get(self):
        entries = self.db.query("SELECT id,author_id,theme,title,markdown,html,published FROM entries ORDER BY published "
                "DESC LIMIT 10")
        self.set_header("Content-Type", "application/atom+xml")
        self.render("feed.xml", entries=entries)


class ComposeHandler(BaseHandler):
    @tornado.web.authenticated
    def get(self):
        id = self.get_argument("id", None)
        entry = None
        if id:
            entry = self.db.get("SELECT id,author_id,theme,title,markdown,html,published FROM entries WHERE id = %s", int(id))
        self.render("compose.html", entry=entry)

    @tornado.web.authenticated
    def post(self):
        id = self.get_argument("id", None)
        title = self.get_argument("title")
        text = self.get_argument("markdown")
        theme = self.get_argument("theme", "4")
        html = markdown.markdown(text)
        if id:
            self.db.execute(
                    "UPDATE entries SET title = %s, theme = %s, markdown = %s, html = %s "
                    "WHERE id = %s", title, theme, text, html, int(id))
        else:
            id = self.db.execute(
                    "INSERT INTO entries (author_id,title,theme,markdown,html,"
                    "published) VALUES (%s,%s,%s,%s,%s,NOW())",
                    self.current_user.id, title, theme, text, html)

        self.redirect("/entry/" + str(id))


class AuthCreateHandler(BaseHandler):
    def get(self):
        self.render("create_author.html", error_text='')

    @gen.coroutine
    def post(self):
        #if self.any_author_exists():
        #    raise tornado.web.HTTPError(400, "author already created")
        hashed_password = yield executor.submit(
                bcrypt.hashpw, tornado.escape.utf8(self.get_argument("password")),
                bcrypt.gensalt())
        author_id = None
        try:
            author_id = self.db_conn_user.execute(
                    "INSERT INTO authors (email, name, hashed_password) "
                    "VALUES (%s, %s, %s)",
                    self.get_argument("email"), self.get_argument("name"),
                    hashed_password)
        except Exception as e:#should be Duplicate key error, but no this exception
            self.render("create_author.html", error_text="该邮箱已注册")

        if author_id:
            self.set_secure_cookie("blogdemo_user", str(author_id))
            self.redirect(self.get_argument("next", "/"))

class AuthLoginHandler(BaseHandler):
    def get(self):
        # If there are no authors, redirect to the account creation page.
        if not self.any_author_exists():
            self.redirect("/auth/create")
        else:
            self.render("login.html", error=None, next=self.get_argument('next', '/'))

    @gen.coroutine
    def post(self):
        author = self.db_conn_user.get("SELECT id,name,email,hashed_password FROM authors WHERE email = %s",
                self.get_argument("email"))
        if not author:
            self.render("login.html", error="邮箱地址不匹配，请确认是否注册")
            return
        hashed_password = yield executor.submit(
                bcrypt.hashpw, tornado.escape.utf8(self.get_argument("password")),
                tornado.escape.utf8(author.hashed_password))
        if hashed_password == author.hashed_password:
            self.set_secure_cookie("blogdemo_user", str(author.id))
            self.redirect(self.get_argument("next", "/"))
        else:
            self.render("login.html", error="密码错误，请重试")


class AuthLogoutHandler(BaseHandler):
    def get(self):
        self.clear_cookie("blogdemo_user")
        self.redirect(self.get_argument("next", "/"))


class EntryModule(tornado.web.UIModule):
    def render(self, entry):
        return self.render_string("modules/entry.html", entry=entry)

class EntryHomeModule(tornado.web.UIModule):
    def render(self, entry):
        return self.render_string("modules/entry_home.html", entry=entry)


def main():
    tornado.options.parse_command_line()
    http_server = tornado.httpserver.HTTPServer(Application())
    http_server.listen(options.port)
    tornado.ioloop.IOLoop.current().start()


if __name__ == "__main__":
    main()
