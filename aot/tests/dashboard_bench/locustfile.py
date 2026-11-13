# coding=utf-8
"""locust 사용자 한 명 = 대시보드를 연 브라우저 한 개.

HAR 에서 뽑은 요청 패턴(`loadgen.py extract`)을 재생한다:
  1. 로그인한다.
  2. 첫 로드: 패턴의 `first` 요청을 순서대로 보낸다(브라우저처럼 문서 → 정적 파일 → 데이터).
  3. 켜 둔 동안: `polls` 각각을 자기 주기로 보낸다(시작 시점은 흩뜨린다 — 20명이 같은
     초에 모두 요청하면 실제와 다른 톱니 부하가 된다).

환경변수:  AOT_BENCH_PATTERN(필수)  AOT_BENCH_USER / AOT_BENCH_PASSWORD
          AOT_BENCH_COOKIE_POOL — 미리 로그인한 세션 쿠키 목록(JSON, `[{이름: 값}, …]`). 있으면 사용자는 로그인하지 않고
          풀의 쿠키를 나눠 쓴다(`loadgen run --cookie-pool N` 이 만든다). 로그인 속도 제한(IP당 시간당 300요청)과
          로그인 비용(비밀번호 해시)을 정상 부하 측정에서 떼어 낸다. 환경변수로만 넘기고 디스크에 쓰지 않는다.
이 파일은 locust 가 `-f` 로 직접 읽는다 — 앱 코드를 import 하지 않는다.
"""
import itertools
import json
import os
import random
import re
import time

from locust import HttpUser, between, task

PATTERN = json.load(open(os.environ['AOT_BENCH_PATTERN'], encoding='utf-8'))
USER = os.environ.get('AOT_BENCH_USER', 'e2eadmin')
PASSWORD = os.environ.get('AOT_BENCH_PASSWORD', 'e2epass1234')
_CSRF = re.compile(r'name="csrf_token"[^>]*value="([^"]+)"|value="([^"]+)"[^>]*name="csrf_token"')
_POOL = json.loads(os.environ.get('AOT_BENCH_COOKIE_POOL') or '[]')
_SEQ = itertools.count()
_UUID = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')


class DashboardViewer(HttpUser):
    wait_time = between(0.05, 0.05)

    def on_start(self):
        if _POOL:
            self.client.cookies.update(_POOL[next(_SEQ) % len(_POOL)])
        else:
            self._login()
        self.csrf = self.client.get('/csrf-token', name='csrf').json().get('csrf_token', '')
        self.first_done = False
        now = time.time()
        # 폴링마다 다음 시각 — 첫 시각은 주기 안에서 무작위로
        self.due = [now + random.uniform(0, max(g['period_s'], 0.5)) for g in PATTERN['polls']]

    def _login(self):
        page = self.client.get('/login_password', name='login page')
        m = _CSRF.search(page.text)
        token = (m.group(1) or m.group(2)) if m else ''
        self.client.post('/login_password', name='login', data={
            'csrf_token': token, 'aot_username': USER, 'aot_password': PASSWORD,
            'form_login': 'Login'})

    def _send(self, item):
        headers = {}
        if item['method'] != 'GET':
            headers['X-CSRFToken'] = self.csrf
            if item.get('content_type'):
                headers['Content-Type'] = item['content_type']
        # 경로에 uuid 가 섞여 통계가 쪼개지지 않게 묶는다
        name = _UUID.sub('<id>', item['url'].split('?')[0])
        self.client.request(item['method'], item['url'], name=f"{item['method']} {name}",
                            data=item.get('body'), headers=headers)

    @task
    def view(self):
        if not self.first_done:
            for item in PATTERN['first']:
                self._send(item)
            self.first_done = True
            return
        now = time.time()
        sent = False
        for i, g in enumerate(PATTERN['polls']):
            if now >= self.due[i]:
                for _ in range(int(g.get('burst', 1))):
                    self._send(g)
                self.due[i] += g['period_s']
                if self.due[i] < now:                     # 밀렸으면 따라잡지 않고 건너뛴다
                    self.due[i] = now + g['period_s']
                sent = True
        if not sent:
            nxt = min(self.due) - now if self.due else 1.0
            time.sleep(min(max(nxt, 0.01), 1.0))
