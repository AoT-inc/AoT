# coding=utf-8
import time

from flask_babel import lazy_gettext

from aot.databases.models import Actions
from aot.databases.models import SMTP
from aot.actions.base_action import AbstractFunctionAction
from aot.utils.database import db_retrieve_table_daemon
from aot.utils.actions import check_allowed_to_email
from aot.utils.send_data import send_email

ACTION_INFORMATION = {
    'name_unique': 'email',
    'name': lazy_gettext('Send Email'),
    'library': None,
    'manufacturer': 'AoT',
    'application': ['functions'],

    'url_manufacturer': None,
    'url_datasheet': None,
    'url_product_purchase': None,
    'url_additional': None,

    'message': 'Send an email.',

    'usage': 'Executing <strong>self.run_action("ACTION_ID")</strong> will email the specified recipient(s) using the SMTP credentials in the system configuration. Separate multiple recipients with commas. The body of the email will be the self-generated message. '
             'Executing <strong>self.run_action("ACTION_ID", value={"email_address": ["email1@email.com", "email2@email.com"], "message": "My message"})</strong> will send an email to the specified recipient(s) with the specified message.',

    'custom_options': [
        {
            'id': 'email',
            'type': 'text',
            'default_value': 'email@domain.com',
            'required': True,
            'name': lazy_gettext('E-Mail Address'),
            'phrase': lazy_gettext('E-mail recipient(s) (separate multiple addresses with commas)')
        }
    ]
}


class ActionModule(AbstractFunctionAction):
    """Send an email to specified recipients via SMTP.

    @phase active
    @stability stable
    @dependency AbstractFunctionAction
    """
    def __init__(self, action_dev, testing=False):
        super().__init__(action_dev, testing=testing, name=__name__)

        self.email = None

        action = db_retrieve_table_daemon(
            Actions, unique_id=self.unique_id)
        self.setup_custom_options(
            ACTION_INFORMATION['custom_options'], action)

        if not testing:
            self.try_initialize()

    def initialize(self):
        self.action_setup = True

    def run_action(self, dict_vars):
        """Send an email to configured or provided recipients."""
        try:
            email_recipients = dict_vars["value"]["email_address"]
        except:
            if "," in self.email:
                email_recipients = self.email.split(",")
            else:
                email_recipients = [self.email]

        if not email_recipients:
            msg = f" Error: No recipients specified."
            self.logger.error(msg)
            dict_vars['message'] += msg
            return dict_vars

        try:
            message_send = dict_vars["value"]["message"]
        except:
            message_send = False

        # If the emails per hour limit has not been exceeded
        smtp_wait_timer, allowed_to_send_notice = check_allowed_to_email()
        if allowed_to_send_notice:
            # 수신자 꼬리표는 조건 로그용이라 메일 본문에는 싣지 않는다 —
            # 받는 사람에게 자기 주소를 되읽어 주는 문장이고 내부 표기다.
            if not message_send:
                message_send = dict_vars['message']
            smtp = db_retrieve_table_daemon(SMTP, entry='first')
            if smtp is None:
                msg = " Error: Email not sent (SMTP settings could not be read)."
                self.logger.error(msg)
                dict_vars['message'] += msg
                return dict_vars
            rc = send_email(smtp.host, smtp.protocol, smtp.port,
                            smtp.user, smtp.passw, smtp.email_from,
                            email_recipients, message_send, logger=self.logger)
            if rc == 0:
                dict_vars['message'] += f" Email '{self.email}'."
            else:
                msg = (f" Error: Email to '{self.email}' failed to send "
                       "(check SMTP settings and the daemon log).")
                self.logger.error(msg)
                dict_vars['message'] += msg
        else:
            msg = (f" Error: Email not sent (hourly limit reached); wait "
                   f"{max(smtp_wait_timer - time.time(), 0):.0f} seconds to email again.")
            self.logger.error(msg)
            dict_vars['message'] += msg

        self.logger.debug(f"Message: {dict_vars['message']}")

        return dict_vars

    def is_setup(self):
        return self.action_setup
