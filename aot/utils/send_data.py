# coding=utf-8
import logging
import os
import smtplib
import socket
import sys
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.header import Header
import ssl

logger = logging.getLogger("aot.notification")


#
# Email notification
#

def send_email(smtp_host, smtp_protocol, smtp_port, smtp_user, smtp_pass,
               smtp_email_from, email_to, message_body, subject=None,
               attachment_file=None, attachment_type=False):
    """
    Email a specific recipient or recipients a message.

    :param smtp_host: Email server hostname
    :type smtp_host: str
    :param smtp_protocol: encryption protocol
    :type smtp_protocol: str
    :param smtp_port: Email server port
    :type smtp_port: int
    :param smtp_user: Email server user name
    :type smtp_user: str
    :param smtp_pass: Email server password
    :type smtp_pass: str
    :param smtp_email_from: From email address
    :type smtp_email_from: str
    :param email_to: To email address(s)
    :type email_to: str or list
    :param message_body: Message in the body of the email
    :type message_body: unicode
    :param subject: Message subject of the email
    :type subject: str
    :param attachment_file: location of file attachment
    :type attachment_file: str
    :param attachment_type: type of attachment ('still' or 'video')
    :type attachment_type: str

    :return: success (0) or failure (1)
    :rtype: bool
    """
    try:
        recipients = email_to if isinstance(email_to, list) else [email_to]

        # Create the enclosing (outer) message
        outer = MIMEMultipart()
        if not subject:
            subject = "AoT Notification ({})".format(
                socket.gethostname())
        outer['Subject'] = Header(subject, 'utf-8')
        outer['To'] = ', '.join(recipients)
        outer['From'] = smtp_email_from
        outer.preamble = 'You will not see this in a MIME-aware mail reader.\n'

        # Add message body
        outer.attach(MIMEText(message_body, 'plain', 'utf-8'))  # or 'html'

        # Add the attachments to the message
        if attachment_file:
            attachments = [attachment_file]
            for file in attachments:
                try:
                    with open(file, 'rb') as fp:
                        msg = MIMEBase('application', "octet-stream")
                        msg.set_payload(fp.read())
                    encoders.encode_base64(msg)
                    msg.add_header(
                        'Content-Disposition',
                        'attachment',
                        filename=os.path.basename(file))
                    outer.attach(msg)
                except Exception:
                    logger.error("Unable to open one of the attachments. "
                                 "Error: {}".format(sys.exc_info()[0]))

        composed = outer.as_string()

        # determine port
        if smtp_port:
            port = smtp_port
        elif smtp_protocol == 'ssl':
            port = 465
        elif smtp_protocol == 'tls':
            port = 587
        elif smtp_protocol in ['unencrypted', 'unencrypted_no_login']:
            port = 25
        else:
            logger.error("Could not determine port to use to send email. Not sending.")
            return 1

        # select encryption protocol
        response_login = None
        context = ssl.create_default_context()
        if smtp_protocol in ['unencrypted', 'unencrypted_no_login']:
            logger.warning("Sending email without encryption (protocol=%s). This is not recommended.", smtp_protocol)
        try:
            if smtp_protocol == 'ssl':
                server = smtplib.SMTP_SSL(smtp_host, port, timeout=15, context=context)
                server.ehlo()
                response_login = server.login(smtp_user, smtp_pass)
            elif smtp_protocol == 'tls':
                server = smtplib.SMTP(smtp_host, port, timeout=15)
                server.ehlo()
                server.starttls(context=context)
                server.ehlo()
                response_login = server.login(smtp_user, smtp_pass)
            elif smtp_protocol == 'unencrypted':
                server = smtplib.SMTP(smtp_host, port, timeout=15)
                server.ehlo()
                response_login = server.login(smtp_user, smtp_pass)
            elif smtp_protocol == 'unencrypted_no_login':
                server = smtplib.SMTP(smtp_host, port, timeout=15)
                server.ehlo()
            else:
                logger.error("Unrecognized protocol: {}".format(smtp_protocol))
                return 1
        except Exception as exc:
            logger.error("Failed to connect/login SMTP (%s:%s, protocol=%s): %s",
                         smtp_host, port, smtp_protocol, exc)
            return 1

        if response_login:
            logger.debug("Email login response: {}".format(response_login))

        # Send the email
        try:
            envelope_from = smtp_email_from or smtp_user
            response_send = server.sendmail(envelope_from, recipients, composed)
            logger.info("Email sent via %s:%s protocol=%s to=%s",
                        smtp_host, port, smtp_protocol, recipients)
            logger.debug("Email send response: {}".format(response_send))
            return 0
        except Exception as exc:
            logger.error("Failed to send email via %s:%s to %s: %s",
                         smtp_host, port, recipients, exc)
            return 1
        finally:
            try:
                server.quit()
            except Exception:
                try:
                    server.close()
                except Exception:
                    pass

        # Old code. It remains here to demonstrate how to encoding video for emailing
        # from aot.utils.system_pi import cmd_output
        # from aot.utils.system_pi import set_user_grp
        # if smtp_ssl:
        #     server = smtplib.SMTP_SSL(smtp_host, smtp_port)
        #     server.ehlo()
        # else:
        #     server = smtplib.SMTP(smtp_host, smtp_port)
        #     server.ehlo()
        #     server.starttls()
        # server.login(smtp_user, smtp_pass)
        # msg = email.mime.multipart.MIMEMultipart()
        # msg['Subject'] = "AoT Notification ({})".format(
        #     socket.gethostname())
        # msg['From'] = smtp_email_from
        # msg['To'] = email_to
        # msg_body = email.mime.text.MIMEText(message_body.encode('utf-8'), 'plain', 'utf-8')
        # msg.attach(msg_body)
        #
        # if attachment_file and attachment_type == 'still':
        #     img_data = open(attachment_file, 'rb').read()
        #     image = email.mime.image.MIMEImage(img_data,
        #                       name=os.path.basename(attachment_file))
        #     msg.attach(image)
        # elif attachment_file and attachment_type == 'video':
        #     out_filename = '{}-compressed.h264'.format(attachment_file)
        #     cmd_output(
        #         'avconv -i "{}" -vf scale=-1:768 -c:v libx264 -preset '
        #         'veryfast -crf 22 -c:a copy "{}"'.format(
        #             attachment_file, out_filename))
        #     set_user_grp(out_filename, 'aot', 'aot')
        #     f = open(attachment_file, 'rb').read()
        #     video = email.mime.base.MIMEBase('application', 'octet-stream')
        #     video.set_payload(f)
        #     email.encoders.encode_base64(video)
        #     video.add_header('Content-Disposition',
        #                      'attachment; filename="{}"'.format(
        #                          os.path.basename(attachment_file)))
        #     msg.attach(video)
        #
        # server.sendmail(msg['From'], msg['To'].split(","), msg.as_string())
        # server.quit()

    except Exception:
        logger.exception(
            "Could not send email to {add} with subject {sub}".format(
                add=email_to, sub=subject))
        return 1
