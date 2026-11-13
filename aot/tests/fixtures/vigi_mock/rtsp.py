# coding=utf-8
"""인증이 걸린 최소 RTSP 모의 서버 — DESCRIBE 만 답한다(시험 전용, 127.0.0.1).

Digest(MD5)로 인증하고, 자격 증명이 제시된 횟수(`credential_attempts`)와 틀린 횟수를 센다.
"""
import hashlib
import re
import socketserver
import threading


class MockRtspServer:
    def __init__(self, username='admin', password='correct-horse-battery', realm='VIGI-RTSP',
                 digest=True, host='127.0.0.1', port=0):
        self.username, self.password, self.realm, self.digest = username, password, realm, digest
        self.credential_attempts = 0
        self.failed_attempts = 0
        self.unauth_requests = 0
        self.lock = threading.Lock()
        self.port = None
        self._bind = (host, port)
        self._srv = None

    def start(self):
        mock = self

        class H(socketserver.StreamRequestHandler):
            def handle(self):
                while True:
                    head = b''
                    while b'\r\n\r\n' not in head:
                        c = self.request.recv(4096)
                        if not c:
                            return
                        head += c
                    text = head.decode('latin-1')
                    line = text.split('\r\n')[0]
                    method, uri = line.split()[0], line.split()[1]
                    cseq = (re.search(r'CSeq:\s*(\d+)', text) or [0, 1])[1]
                    m = re.search(r'Authorization:\s*(.+)', text)
                    if not m:
                        with mock.lock:
                            mock.unauth_requests += 1
                        ch = ('Digest realm="%s", nonce="abc123nonce", algorithm=MD5' % mock.realm
                              if mock.digest else 'Basic realm="%s"' % mock.realm)
                        self.request.sendall(
                            ('RTSP/1.0 401 Unauthorized\r\nCSeq: %s\r\nWWW-Authenticate: %s\r\n\r\n'
                             % (cseq, ch)).encode())
                        continue
                    ok = mock._check(m.group(1), method, uri)
                    with mock.lock:
                        mock.credential_attempts += 1
                        if not ok:
                            mock.failed_attempts += 1
                    if ok:
                        body = 'v=0\r\n'
                        self.request.sendall(('RTSP/1.0 200 OK\r\nCSeq: %s\r\nContent-Type: '
                                              'application/sdp\r\nContent-Length: %d\r\n\r\n%s'
                                              % (cseq, len(body), body)).encode())
                    else:
                        self.request.sendall(
                            ('RTSP/1.0 401 Unauthorized\r\nCSeq: %s\r\n\r\n' % cseq).encode())

        class S(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True

        self._srv = S(self._bind, H)
        self.port = self._srv.server_address[1]
        threading.Thread(target=self._srv.serve_forever, daemon=True).start()
        return self

    def _check(self, auth, method, uri):
        if auth.lower().startswith('basic'):
            import base64
            try:
                u, p = base64.b64decode(auth.split(None, 1)[1]).decode().split(':', 1)
            except Exception:
                return False
            return u == self.username and p == self.password
        p = dict((k.lower(), a or b) for k, a, b in re.findall(r'(\w+)=(?:"([^"]*)"|([^,\s]*))', auth))
        md5 = lambda t: hashlib.md5(t.encode()).hexdigest()  # noqa: E731
        ha1 = md5('%s:%s:%s' % (self.username, self.realm, self.password))
        ha2 = md5('%s:%s' % (method, p.get('uri', uri)))
        return p.get('username') == self.username and \
            p.get('response') == md5('%s:%s:%s' % (ha1, p.get('nonce', ''), ha2))

    def stop(self):
        if self._srv:
            self._srv.shutdown()
            self._srv.server_close()

    def __enter__(self):
        return self.start()

    def __exit__(self, *a):
        self.stop()
