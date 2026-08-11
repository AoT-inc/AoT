# coding=utf-8
"""원격 AoT 등록이 자격증명을 **검증된 연결로만** 보낸다는 전제를 고정한다.

`remote_host_add()` 는 관리자 계정의 **비밀번호 원문**을 원격으로 보내는
유일한 경로다. 예전에는 그것을 `requests.post(..., verify=False)` 로 먼저
보내고, 응답 본문에 담겨 온 `certificate` 값을 고정했다. 순서가 뒤집혀 있어서
두 가지가 동시에 무너진다.

1. 비밀번호가 **아무 검증도 없는 연결**로 나간다 — 중간자가 그대로 읽는다.
2. 중간자가 자기 인증서를 본문에 담아 돌려주면 그것이 고정돼, 이후 모든
   연결이 그 가짜 인증서로 "검증" 된다. 한 번 자리잡으면 정상처럼 보인다.

지금은 자격증명 없이 인증서를 먼저 관측·고정하고, 비밀번호는 그 고정된
인증서로 검증되는 연결로만 보낸다.

**이 회귀는 조용하다.** `verify=False` 로 되돌려도 기능은 멀쩡히 동작하고,
등록도 성공하며, 화면에 아무 차이가 없다. 사라지는 것은 보호뿐이다. 그래서
사람 대신 이 테스트가 본다.

의존성 없이 소스만 읽는다(`aot/scripts/check_route_auth.py` 와 같은 이유) —
설치가 깨져도 이 검사는 가려지지 않아야 한다.

    python3 aot/tests/test_remote_host_enrollment.py
"""
import ast
import hashlib
import os
import re
import unittest

_MODULE = os.path.join(os.path.dirname(__file__), '..',
                       'aot_flask', 'utils', 'utils_remote_host.py')

#: 검증 없는 TLS 를 만드는 표현들. 어느 하나라도 자격증명을 보내는 경로에
#: 들어오면 이 파일의 전제가 통째로 무너진다.
_UNVERIFIED_MARKERS = ('CERT_NONE', 'verify_mode')


def _source():
    with open(os.path.abspath(_MODULE), encoding='utf-8') as handle:
        return handle.read()


def _functions(tree):
    return {node.name: node for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _load_pure_helpers(names, extra=None):
    """순수 헬퍼만 떼어 실행한다 — flask/sqlalchemy 를 끌어오지 않기 위해서.

    상수(`_SAFE_HOST` 등)도 소스에서 그대로 가져온다. 테스트가 같은 값을 다시
    적어 두면 소스와 조용히 갈라진다.
    """
    tree = ast.parse(_source())
    wanted = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in names:
            wanted.append(node)
        elif isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id in names
                for target in node.targets):
            wanted.append(node)
    namespace = {'hashlib': hashlib, 're': re}
    namespace.update(extra or {})
    exec(compile(ast.Module(body=wanted, type_ignores=[]),
                 '<utils_remote_host helpers>', 'exec'), namespace)
    return namespace


class CredentialsNeverLeaveUnverifiedTest(unittest.TestCase):
    """비밀번호가 검증되지 않은 연결로 나가지 않는다."""

    def setUp(self):
        self.source = _source()
        self.tree = ast.parse(self.source)
        self.functions = _functions(self.tree)

    def test_the_enrollment_function_still_exists(self):
        """이름이 바뀌었는데 검사만 남아 통과하는 상황을 막는다."""
        for name in ('remote_host_add', 'fetch_certificate',
                     'pin_certificate', 'pinned_fingerprint'):
            self.assertIn(
                name, self.functions,
                "{} 가 없습니다 — 이름이 바뀌었다면 이 테스트도 함께 "
                "고치십시오.".format(name))

    def test_requests_is_not_imported(self):
        """`requests` 는 `verify=False` 를 들여온 통로였다.

        urllib3 로 직접 붙으면 `cert_reqs` 를 빠뜨렸을 때 조용히 통과하는
        기본값이 없다(`CERT_REQUIRED` 를 명시해야 검증한다). requests 를
        다시 들이면 `verify=` 기본값 뒤로 검증 여부가 숨는다.
        """
        imported = [
            alias.name
            for node in ast.walk(self.tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        ]
        self.assertNotIn('requests', imported)

    def test_no_call_disables_verification(self):
        hits = [
            "{}행".format(node.lineno)
            for node in ast.walk(self.tree)
            if isinstance(node, ast.Call)
            for keyword in node.keywords
            if keyword.arg == 'verify'
            and isinstance(keyword.value, ast.Constant)
            and keyword.value.value is False
        ]
        self.assertFalse(
            hits,
            "verify=False 가 되살아났습니다: {} — 이 파일에서 검증을 끄면 "
            "관리자 비밀번호가 중간자에게 그대로 노출됩니다.".format(hits))

    def test_every_pool_manager_verifies_against_a_pinned_certificate(self):
        pools = [node for node in ast.walk(self.tree)
                 if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Attribute)
                 and node.func.attr == 'PoolManager']
        self.assertTrue(pools, "PoolManager 호출이 하나도 없습니다.")

        for node in pools:
            keywords = {kw.arg: kw.value for kw in node.keywords}
            self.assertEqual(
                'CERT_REQUIRED',
                getattr(keywords.get('cert_reqs'), 'value', None),
                "{}행 PoolManager 가 인증서를 검증하지 않습니다.".format(
                    node.lineno))
            self.assertIn(
                'ca_certs', keywords,
                "{}행 PoolManager 에 고정 인증서가 없습니다 — CERT_REQUIRED "
                "만으로는 자체서명 인증서를 검증할 기점이 없습니다.".format(
                    node.lineno))

    def test_verification_is_disabled_only_where_nothing_is_sent(self):
        """검증을 끄는 곳은 `fetch_certificate` 하나뿐이어야 한다.

        거기서는 정당하다 — 신뢰 기점이 아직 없고, **자격증명을 하나도
        보내지 않는다.** 다른 함수로 번지는 순간 그 근거가 사라진다.
        """
        allowed = self.functions['fetch_certificate']
        allowed_lines = set(range(allowed.lineno, allowed.end_lineno + 1))

        strays = [
            "{}행".format(number)
            for number, line in enumerate(self.source.splitlines(), start=1)
            if number not in allowed_lines
            and any(marker in line for marker in _UNVERIFIED_MARKERS)
        ]
        self.assertFalse(
            strays,
            "fetch_certificate() 밖에서 TLS 검증을 끄고 있습니다: {}".format(
                strays))

    def test_certificate_is_pinned_before_the_password_is_read(self):
        """순서가 전부다 — 고정이 비밀번호보다 **먼저** 와야 한다."""
        add = self.functions['remote_host_add']

        pins = [node.lineno for node in ast.walk(add)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in ('fetch_certificate', 'pin_certificate')]
        passwords = [node.lineno for node in ast.walk(add)
                     if isinstance(node, ast.Attribute)
                     and node.attr == 'password']

        self.assertTrue(pins, "인증서를 고정하는 호출이 없습니다.")
        self.assertTrue(passwords, "비밀번호를 읽는 곳이 없습니다.")
        self.assertLess(
            max(pins), min(passwords),
            "비밀번호를 인증서 고정보다 먼저 읽고 있습니다 — 등록 순서가 "
            "다시 뒤집혔습니다.")

    def test_the_response_body_is_never_trusted_as_the_certificate(self):
        """본문의 `certificate` 는 상대의 *주장*일 뿐이다.

        우리가 고정한 것은 실제 핸드셰이크에서 관측한 인증서다. 본문 값으로
        덮어쓰면 방금 검증에 쓴 인증서를 상대가 마음대로 갈아치울 수 있다
        (예전 코드가 정확히 그렇게 했다).
        """
        hits = [
            "{}행".format(node.lineno)
            for node in ast.walk(self.tree)
            if isinstance(node, ast.Subscript)
            and isinstance(node.slice, ast.Constant)
            and node.slice.value == 'certificate'
        ]
        self.assertFalse(
            hits,
            "응답 본문의 certificate 를 다시 쓰고 있습니다: {}".format(hits))


class PinIsNotSilentlyReplacedTest(unittest.TestCase):
    """고정된 인증서가 소리 없이 갈리지 않는다."""

    def setUp(self):
        self.source = _source()
        self.functions = _functions(ast.parse(self.source))

    def _segment(self, name):
        return ast.get_source_segment(self.source, self.functions[name])

    def test_add_compares_against_the_existing_pin(self):
        self.assertIn('pinned_fingerprint(', self._segment('remote_host_add'),
                      "기존 고정과 대조하지 않으면 재등록 한 번으로 중간자의 "
                      "인증서가 조용히 자리를 차지합니다.")

    def test_delete_drops_the_pin_so_re_enrollment_stays_possible(self):
        """지문 대조로 막기만 하고 풀 방법을 안 주면 사람이 갇힌다.

        원격이 인증서를 정상적으로 교체한 경우의 정상 경로는 "등록을 지웠다가
        다시 추가" 다. 삭제가 옛 고정을 안 지우면 그 경로가 막히고, 남는
        방법은 서버의 pem 파일을 직접 지우는 것뿐이다.
        """
        segment = self._segment('remote_host_del')
        self.assertIn('os.remove(_certificate_path(', segment)
        self.assertIn('Remote.host == host', segment,
                      "같은 호스트를 쓰는 다른 등록이 남아 있는지 보지 않으면 "
                      "그 등록의 고정까지 끊습니다.")

    def test_all_paths_read_the_same_pinned_file(self):
        """경로 포맷이 흩어지면 한 곳만 고쳤을 때 조용히 갈라진다."""
        for name in ('remote_log_in', 'remote_host_page'):
            self.assertIn('_certificate_path(', self._segment(name))
        self.assertEqual(
            1, self.source.count("file='{add}_cert.pem'.format"),
            "인증서 경로 포맷이 두 군데 이상입니다 — _certificate_path() 하나로 "
            "모으십시오.")


class HelperBehaviourTest(unittest.TestCase):
    """의존성 없이 순수 헬퍼의 실제 동작을 본다."""

    @classmethod
    def setUpClass(cls):
        cls.helpers = _load_pure_helpers({'_split_host_port', '_fingerprint'})
        cls.helpers.update(_load_pure_helpers(
            {'_certificate_path', '_SAFE_HOST'},
            extra={'STORED_SSL_CERTIFICATE_PATH': '/pin'}))

    def test_certificate_path_refuses_traversal(self):
        """호스트 이름이 그대로 파일명이 된다 — 경로가 새어 나가면 안 된다."""
        path = self.helpers['_certificate_path']
        self.assertEqual('/pin/farm.example.com_cert.pem',
                         path('farm.example.com'))
        self.assertEqual('/pin/farm.example.com:8443_cert.pem',
                         path('farm.example.com:8443'))
        for bad in ('../../etc/passwd', '.hidden', 'a/b', '', None,
                    'host\nname'):
            with self.assertRaises(ValueError, msg=repr(bad)):
                path(bad)

    def test_split_host_port(self):
        split = self.helpers['_split_host_port']
        self.assertEqual(('farm.example.com', 443), split('farm.example.com'))
        self.assertEqual(('farm.example.com', 8443),
                         split('farm.example.com:8443'))
        self.assertEqual(('192.0.2.10', 8443), split('192.0.2.10:8443'))
        self.assertEqual(('2001:db8::1', 443), split('[2001:db8::1]'))
        self.assertEqual(('2001:db8::1', 8443), split('[2001:db8::1]:8443'))
        self.assertEqual(('farm.example.com', 443),
                         split('  farm.example.com  '))

    def test_split_host_port_keeps_bare_ipv6_intact(self):
        """대괄호 없는 IPv6 를 포트 구분자로 오해해 잘라내면 안 된다.

        잘린 주소('2001:db8:')로 붙으면 엉뚱한 호스트의 인증서를 고정한다.
        """
        split = self.helpers['_split_host_port']
        self.assertEqual(('2001:db8::1', 443), split('2001:db8::1'))
        self.assertEqual(('fe80::1', 443), split('fe80::1'))

    def test_fingerprint_is_the_sha256_of_the_der(self):
        fingerprint = self.helpers['_fingerprint'](b'aot')
        expected = hashlib.sha256(b'aot').hexdigest().upper()
        self.assertEqual(expected,
                         fingerprint.replace(':', ''))
        self.assertEqual(64 + 31, len(fingerprint))  # 32바이트 + 구분자 31개


if __name__ == '__main__':
    unittest.main()
