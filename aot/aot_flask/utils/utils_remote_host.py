# -*- coding: utf-8 -*-
import hashlib
import ipaddress
import json
import logging
import os
import re
import socket
import ssl

import sqlalchemy
import urllib3
from flask import flash
from flask import redirect
from flask import url_for
from flask_babel import gettext

from aot.config import STORED_SSL_CERTIFICATE_PATH
from aot.databases.models import DisplayOrder
from aot.databases.models import Remote
from aot.aot_flask.extensions import db
from aot.aot_flask.utils import utils_general
from aot.aot_flask.utils.utils_general import add_display_order
from aot.aot_flask.utils.utils_general import delete_entry_with_id
from aot.aot_flask.utils.utils_general import flash_form_errors
from aot.utils.system_pi import assure_path_exists
from aot.utils.system_pi import csv_to_list_of_str
from aot.utils.system_pi import list_to_csv

logger = logging.getLogger(__name__)

#
# Remote host commands executed on AoT with Remote Admin Dashboard
#

#: 호스트 이름에 쓸 수 있는 문자. 이 값이 파일명이 되므로 경로 구분자나
#: 상위 디렉터리 참조가 들어오면 안 된다. 지금은 도달할 수 없는 경로이기는
#: 하다 — '/' 가 든 이름은 애초에 DNS 로 풀리지 않아 등록이 실패하므로 DB 에
#: 들어갈 수 없다. 그 안전이 DNS 동작에 기대고 있다는 것이 문제라 여기서
#: 직접 못박는다.
_SAFE_HOST = re.compile(r'^[A-Za-z0-9._:\[\]-]+$')


def _certificate_path(address):
    """이 호스트에 대해 고정한 인증서 파일 경로.

    등록·로그인·페이지 조회 세 경로가 **같은 파일**을 봐야 한다. 예전에는
    같은 포맷 문자열이 세 군데에 흩어져 있어 한 곳만 고치면 조용히 갈라졌다.
    """
    if not address or address.startswith('.') or not _SAFE_HOST.match(address):
        raise ValueError(
            'Refusing to build a certificate path for host {!r}'.format(address))
    return '{path}/{file}'.format(
        path=STORED_SSL_CERTIFICATE_PATH,
        file='{add}_cert.pem'.format(add=address))


def remote_log_in(address, user, token):
    """
    Log in to AoT and return the cookie header for subsequent requests

    :param address: host name or IP address of remote AoT
    :param user: User name of an admin on the remote AoT
    :param token: Remote-access token previously issued by that AoT's
       /newremote/ endpoint (see RemoteAccessToken) — not a password hash
    :return: header with session cookie (used by remote_host_page())
    """
    try:
        # Require all certificate data matches stored certificate, except hostname
        http = urllib3.PoolManager(cert_reqs='CERT_REQUIRED',
                                   ca_certs=_certificate_path(address),
                                   assert_hostname=False)

        # Perform the login with the user name and issued remote-access token
        login_url = 'https://{add}/remote_login'.format(add=address)
        login_page = http.request('POST', login_url,
                                  fields={"username": user,
                                          "token": token})

        # Use cookie set by the login page to verify our session and keep us logged in
        headers = {'cookie': login_page.getheader('set-cookie')}
        return headers
    except Exception:
        return None


def remote_host_page(address, headers, page):
    """
    Make request, receive response, and authenticate a remote AoT
    connection. This checks if the HTTPS certificate matches the stored
    certificate and the user and password hash matches

    :param address: host name or IP address of remote AoT
    :param headers: the header object returned from remote_log_in()
    :param page: The page to return information from
    :return: (1, None) for error, (0, json_data) on success
    """
    if not headers:
        return 1, None

    try:
        # Require certificate data matches stored certificate, except hostname
        http = urllib3.PoolManager(cert_reqs='CERT_REQUIRED',
                                   ca_certs=_certificate_path(address),
                                   assert_hostname=False)

        # Test getting a page requiring to be logged in
        logged_in_url = 'https://{add}/{page}/'.format(add=address, page=page)
        logged_in_page = http.request('GET', logged_in_url, headers=headers)

        return 0, logged_in_page.data.decode('utf-8')
    except Exception as e:
        logger.exception(
            "'remote_host_auth_page' raised an exception: {err}".format(err=e))
        return 1, None


def _split_host_port(host, default_port=443):
    """'farm.example.com:8443' -> ('farm.example.com', 8443)."""
    value = (host or '').strip()
    if value.startswith('['):                       # IPv6 리터럴
        close = value.find(']')
        if close != -1:
            rest = value[close + 1:]
            port = int(rest[1:]) if rest.startswith(':') and rest[1:].isdigit() else default_port
            return value[1:close], port
    if value.count(':') > 1:
        # 대괄호 없는 IPv6. 마지막 ':' 를 포트 구분자로 보면 주소가 잘린다
        # ('2001:db8::1' -> '2001:db8:' + 1). 잘린 주소로 붙으면 엉뚱한
        # 호스트의 인증서를 고정하게 되므로 통째로 호스트로 본다.
        return value, default_port
    if ':' in value:
        name, _sep, port = value.rpartition(':')
        if port.isdigit():
            return name, int(port)
    return value, default_port


def _fingerprint(der):
    """DER 인증서의 SHA-256 지문. 사람이 눈으로 대조할 형식(AA:BB:...)."""
    digest = hashlib.sha256(der).hexdigest().upper()
    return ':'.join(digest[i:i + 2] for i in range(0, len(digest), 2))


def fetch_certificate(host, timeout=10):
    """원격이 TLS 핸드셰이크에서 실제로 제시하는 인증서를 관측한다.

    검증하지 않는다 — 자체서명이 정상인 설치가 대부분이라 아직 신뢰 기점이
    없다. 그래도 의미가 있는 이유는 **자격증명을 하나도 보내지 않기 때문**
    이다. 여기서 얻은 인증서를 고정하고, 그 다음에야 비밀번호를 보낸다.

    :return: (PEM 문자열, SHA-256 지문)
    """
    name, port = _split_host_port(host)

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE

    # SNI 에는 IP 리터럴을 넣을 수 없다(이름 기반 가상호스트용 확장이다).
    try:
        ipaddress.ip_address(name)
        server_hostname = None
    except ValueError:
        server_hostname = name

    with socket.create_connection((name, port), timeout=timeout) as sock:
        with context.wrap_socket(
                sock, server_hostname=server_hostname) as tls_sock:
            der = tls_sock.getpeercert(binary_form=True)

    return ssl.DER_cert_to_PEM_cert(der), _fingerprint(der)


def pinned_fingerprint(host):
    """이미 고정해 둔 인증서가 있으면 그 지문, 없거나 못 읽으면 None."""
    try:
        with open(_certificate_path(host), 'r') as handle:
            return _fingerprint(ssl.PEM_cert_to_DER_cert(handle.read()))
    except Exception:
        return None


def pin_certificate(host, pem):
    """관측한 인증서를 이 호스트의 고정 인증서로 저장한다."""
    assure_path_exists(STORED_SSL_CERTIFICATE_PATH)
    cert_path = _certificate_path(host)
    with open(cert_path, 'w') as handle:
        handle.write(pem)
    return cert_path


def remote_host_add(form_setup, display_order):
    """
    Add a remote AoT to the Remote Admin Dashboard

    Authenticate a remote AoT install that will be used on this system's
    Remote Admin dashboard.
    The user name and password is sent once (POST, not the query string)
    and, if verified, the remote issues a dedicated remote-access token
    (see RemoteAccessToken on the remote side). The token — never the
    account's password or its hash — is what authenticates all subsequent
    connections, and the remote's certificate is pinned for a verified SSL.

    **등록 순서가 뒤집혀 있었다.** 예전에는 비밀번호를 `verify=False` 로 먼저
    보내고, 그 응답에 담겨 온 인증서를 고정했다. 즉 계정 비밀번호가 **아무
    검증도 없는 연결**로 나갔고, 중간자는 그것을 그대로 읽은 뒤 자기 인증서를
    돌려주기만 하면 이후 모든 연결이 그 가짜 인증서로 고정돼(=중간자가 영구히
    자리잡아) 다음부터는 정상처럼 보였다. 첫 접속 한 번에 계정과 원격 접근이
    통째로 넘어가는 경로다.

    이제 순서를 바꾼다: 자격증명 없이 인증서를 먼저 받아 고정하고, 비밀번호는
    **그 고정된 인증서로 검증되는 연결**로만 보낸다. 나머지 요청
    (`remote_log_in`/`remote_host_page`)이 이미 쓰던 방식과 같아졌다.

    첫 접속의 신뢰(TOFU)는 남는다 — 처음 본 인증서가 진짜인지는 알 수 없다.
    그래서 지문을 사용자에게 보여 준다. 다른 경로로 확인해 달라는 뜻이다.
    """
    if not utils_general.user_has_permission('edit_settings'):
        return redirect(url_for('routes_general.home'))

    if form_setup.validate():
        try:
            host = form_setup.host.data

            # 1) 자격증명 없이 인증서를 먼저 관측한다.
            try:
                pem, fingerprint = fetch_certificate(host)
            except Exception as err:
                flash(gettext(
                    "Could not retrieve the TLS certificate from %(host)s: %(err)s",
                    host=host, err=err), "error")
                return 1

            # 이미 고정된 인증서가 있는데 지문이 다르면 여기서 멈춘다. 조용히
            # 덮어쓰면 순서를 바꾼 의미가 사라진다 — 중간자가 새 인증서를
            # 심고 그 뒤 모든 연결이 그것으로 검증되기 때문이다. 원격이 실제로
            # 인증서를 교체한 경우의 정상 경로는 "등록을 지웠다가 다시 추가"
            # 이고, 그때 remote_host_del() 이 옛 고정을 함께 지운다.
            previous = pinned_fingerprint(host)
            if previous and previous != fingerprint:
                flash(gettext(
                    "The TLS certificate of %(host)s does not match the one "
                    "pinned earlier (pinned %(old)s, now %(new)s). Nothing was "
                    "sent. If the remote genuinely replaced its certificate, "
                    "delete this remote host and add it again; otherwise the "
                    "connection is being intercepted.",
                    host=host, old=previous, new=fingerprint), "error")
                return 1

            cert_path = pin_certificate(host, pem)

            # 2) 고정한 인증서로 검증되는 연결로만 비밀번호를 보낸다.
            #    assert_hostname=False 는 이 파일의 다른 요청과 같은 이유 —
            #    자체서명 인증서의 CN 이 호스트와 다른 설치가 흔하다. 인증서
            #    자체는 CERT_REQUIRED 로 검증된다.
            credentials = {
                'user': form_setup.username.data,
                'passw': form_setup.password.data
            }
            url = 'https://{}/newremote/'.format(host)
            try:
                http = urllib3.PoolManager(cert_reqs='CERT_REQUIRED',
                                           ca_certs=cert_path,
                                           assert_hostname=False)
                response = http.request('POST', url, fields=credentials)
                pw_check = json.loads(response.data.decode('utf-8'))
            except Exception as err:
                logger.error("Remote host enrollment failed for %s: %s",
                             host, err)
                flash(gettext(
                    "Could not enroll with %(host)s: %(err)s",
                    host=host, err=err), "error")
                return 1

            flash(gettext(
                "Pinned the certificate of %(host)s. Verify this fingerprint "
                "out of band before trusting the connection: %(fp)s",
                host=host, fp=fingerprint), "info")

            if 'status' not in pw_check:
                flash(gettext("Unknown response: %(res)s", res=pw_check), "error")
                return 1
            elif pw_check['status']:
                flash(pw_check['error_msg'], "error")
                return 1

            # 응답 본문의 `certificate` 는 **쓰지 않는다.** 우리가 고정한 것은
            # 실제 TLS 핸드셰이크에서 관측한 인증서이고, 본문 값은 상대가
            # "내 인증서는 이것" 이라고 주장하는 문자열일 뿐이다. 그것으로
            # 덮어쓰면 방금 검증에 쓴 인증서를 상대가 마음대로 갈아치울 수 있어
            # 순서를 바꾼 의미가 사라진다(예전 코드가 정확히 그렇게 했다).

            new_remote_host = Remote()
            new_remote_host.host = form_setup.host.data
            new_remote_host.username = form_setup.username.data
            new_remote_host.access_token = pw_check['token']
            try:
                db.session.add(new_remote_host)
                db.session.commit()
                flash(gettext("Remote Host %(host)s with ID %(id)s "
                              "(%(uuid)s) successfully added",
                              host=form_setup.host.data,
                              id=new_remote_host.id,
                              uuid=new_remote_host.unique_id),
                      "success")

                DisplayOrder.query.first().remote_host = add_display_order(
                    display_order, new_remote_host.unique_id)
                db.session.commit()
            except sqlalchemy.exc.OperationalError as except_msg:
                flash(gettext("Error: %(err)s",
                              err='Remote Host Add: {msg}'.format(msg=except_msg)),
                      "error")
            except sqlalchemy.exc.IntegrityError as except_msg:
                flash(gettext("Error: %(err)s",
                              err='Remote Host Add: {msg}'.format(msg=except_msg)),
                      "error")
        except Exception as except_msg:
            flash(gettext("Error: %(err)s",
                          err='Remote Host Add: {msg}'.format(msg=except_msg)),
                  "error")
    else:
        flash_form_errors(form_setup)


def remote_host_del(form_setup):
    """Delete a remote AoT from the Remote Admin Dashboard.

    고정해 둔 인증서도 함께 지운다. 남겨 두면 `remote_host_add()` 의 지문
    대조가 옛 인증서를 기준으로 판정해, 인증서를 정상적으로 교체한 원격을
    다시 등록할 수 없다 — 사용자에게는 서버의 pem 파일을 직접 지우는 것
    말고 풀 방법이 없다. 같은 호스트를 쓰는 다른 등록이 남아 있으면 그
    등록의 고정을 끊게 되므로 지우지 않는다.
    """
    if not utils_general.user_has_permission('edit_settings'):
        return redirect(url_for('routes_general.home'))

    try:
        remote = Remote.query.filter(
            Remote.unique_id == form_setup.remote_id.data).first()
        host = remote.host if remote else None

        delete_entry_with_id(Remote,
                             form_setup.remote_id.data)
        display_order = csv_to_list_of_str(
            DisplayOrder.query.first().remote_host)
        display_order.remove(form_setup.remote_id.data)
        DisplayOrder.query.first().remote_host = list_to_csv(display_order)
        db.session.commit()

        if host and not Remote.query.filter(Remote.host == host).first():
            try:
                os.remove(_certificate_path(host))
            except OSError:
                pass
    except Exception as except_msg:
        flash(gettext("Error: %(err)s",
                      err='Remote Host Delete: {msg}'.format(msg=except_msg)),
              "error")
