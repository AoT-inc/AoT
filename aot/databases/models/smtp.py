# -*- coding: utf-8 -*-
from aot.databases import CRUDMixin
from aot.aot_flask.extensions import db
from aot.utils.crypto import (SEALED_EMPTY, SEALED_LEGACY, SEALED_UNREADABLE,
                              open_sealed, seal_secret)


class SMTP(CRUDMixin, db.Model):
    """
    Stores SMTP server configuration for sending email notifications.

    SMTP holds host, port, protocol (ssl/starttls), credentials, sender address,
    and rate-limiting (hourly_max) for outbound email from the AoT system.

    The account password is stored encrypted (column `passw`, attribute
    `passw_enc`). `passw` is a property: assigning encrypts, reading decrypts, so
    call sites that send mail keep working and nothing else ever sees the raw
    column. The settings form never renders it back (blank = keep).

    @phase active
    """
    __tablename__ = "smtp"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, unique=True, primary_key=True)
    host = db.Column(db.Text, default='smtp.gmail.com')
    protocol = db.Column(db.Text, default='ssl')
    port = db.Column(db.Integer, default=None)
    user = db.Column(db.Text, default='email@gmail.com')
    passw_enc = db.Column('passw', db.Text, default=None)
    email_from = db.Column(db.Text, default='email@gmail.com')
    hourly_max = db.Column(db.Integer, default=5)
    email_count = db.Column(db.Integer, default=0)
    smtp_wait_timer = db.Column(db.Integer, default=0)

    # TODO: Remove unused columns, below
    # 사용하지 않음: 암호화 방식은 protocol 컬럼이 정한다(삭제하려면 마이그레이션 필요).
    ssl = db.Column(db.Boolean, default=None)

    @property
    def passw(self):
        """Decrypted password, or None when unset or not decryptable."""
        return open_sealed(self.passw_enc)[0]

    @passw.setter
    def passw(self, value):
        self.passw_enc = seal_secret(value)

    @property
    def password_state(self):
        return open_sealed(self.passw_enc)[1]

    @property
    def has_password(self):
        return self.password_state != SEALED_EMPTY

    @property
    def password_unreadable(self):
        """True when a password is stored but this install cannot decrypt it
        (settings restored from another install / rotated key)."""
        return self.password_state == SEALED_UNREADABLE

    @property
    def password_is_legacy_plaintext(self):
        return self.password_state == SEALED_LEGACY

    def __repr__(self):
        return "<{cls}(id={s.id})>".format(s=self, cls=self.__class__.__name__)
