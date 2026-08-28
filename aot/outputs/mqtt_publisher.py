# coding=utf-8
#
# mqtt_publisher.py - Persistent MQTT publish client shared by the MQTT outputs.
#
"""paho 의 publish.single() 을 대신하는 지속 연결 발행기.

publish.single() 은 접속·발행·종료를 한 번에 해 주는 편의 함수지만 자체
타임아웃이 없다. TCP 는 붙었는데 CONNACK 가 오지 않는 상황 — 평문 설정으로
TLS 포트(8883)에 붙는 오설정이 대표적이다 — 에서는 영원히 매달린다(로컬에서
15분 넘게 실측). 이 호출은 output_switch() 경로, 즉 출력 컨트롤러 스레드에서
일어나므로 그 출력이 통째로 먹통이 된다.

여기서는 클라이언트 하나를 loop_start() 로 백그라운드에 띄워 두고 publish()
만 부른다. paho 의 publish() 는 논블로킹이라 연결이 없으면 즉시
MQTT_ERR_NO_CONN 을 돌려준다 — 매달리는 경로 자체가 없다. 끊긴 뒤의 재연결도
백그라운드 루프가 알아서 계속 시도한다.
"""

import threading


class PersistentMqttPublisher:
    """MQTT 발행 전용 지속 연결 클라이언트.

    @phase active
    @stability stable
    @dependency paho-mqtt
    """

    def __init__(self, logger, hostname, port, client_id,
                 keepalive=60, auth=None, tls=None, transport='tcp'):
        self.logger = logger
        self.hostname = hostname
        self.port = int(port) if port else 1883
        self.client_id = client_id
        self.keepalive = int(keepalive) if keepalive else 60
        self.auth = auth
        self.tls = tls
        self.transport = transport or 'tcp'

        self.client = None
        self._connected = threading.Event()
        self._started = False

    # ── 수명 주기 ──────────────────────────────────────────────────────────
    def start(self, wait_s=5.0):
        """백그라운드 연결을 시작하고, 최대 wait_s 만큼만 연결을 기다린다.

        기다리는 이유는 초기화 직후의 startup state 발행이 곧바로 나가야 하기
        때문이다. 상한이 있으므로 브로커가 응답하지 않아도 여기서 멈추지 않는다.
        연결이 늦어지면 False 를 돌려주지만, 백그라운드 루프는 계속 재시도한다."""
        import paho.mqtt.client as mqtt_client

        try:
            self.client = mqtt_client.Client(
                client_id=self.client_id, transport=self.transport)

            if self.auth:
                self.client.username_pw_set(
                    self.auth.get('username'), self.auth.get('password'))

            if self.tls:
                self.client.tls_set(ca_certs=self.tls.get('ca_certs') or None)

            self.client.on_connect = self._on_connect
            self.client.on_disconnect = self._on_disconnect

            # connect_async + loop_start: 연결 수립도 백그라운드에서 일어나므로
            # 호출자는 어떤 경우에도 여기서 블로킹되지 않는다.
            self.client.connect_async(self.hostname, self.port, self.keepalive)
            self.client.loop_start()
            self._started = True
        except Exception as err:
            self.logger.error("MQTT publisher could not start: {}".format(err))
            self.client = None
            return False

        if not self._connected.wait(timeout=wait_s):
            self.logger.warning(
                "MQTT publisher not connected to {}:{} within {}s; "
                "will keep retrying in the background".format(
                    self.hostname, self.port, wait_s))
            return False
        return True

    def stop(self):
        if not self.client:
            return
        try:
            self.client.loop_stop()
            self.client.disconnect()
        except Exception as err:
            self.logger.warning("MQTT publisher stop error: {}".format(err))
        finally:
            self.client = None
            self._started = False
            self._connected.clear()

    # ── 발행 ───────────────────────────────────────────────────────────────
    def publish(self, topic, payload, qos=0, retain=False):
        """발행을 시도하고 성공 여부를 돌려준다. 절대 블로킹하지 않는다."""
        if not self.client:
            self.logger.error("MQTT publisher is not set up; cannot publish")
            return False

        try:
            info = self.client.publish(topic, payload, qos=qos, retain=retain)
        except Exception as err:
            self.logger.error("MQTT publish error: {}".format(err))
            return False

        if info.rc != 0:
            # 대개 MQTT_ERR_NO_CONN(4) — 브로커와 끊긴 상태다. 상위(확인 루프)가
            # dispatched_ok=False 로 받아 재전송/실패 처리를 하게 둔다.
            self.logger.error(
                "MQTT publish to '{}' failed (rc={}, connected={})".format(
                    topic, info.rc, self.is_connected()))
            return False
        return True

    def is_connected(self):
        try:
            return bool(self.client and self.client.is_connected())
        except Exception:
            return False

    # ── 콜백 ───────────────────────────────────────────────────────────────
    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self._connected.set()
            self.logger.info("MQTT publisher connected to {}:{}".format(
                self.hostname, self.port))
        else:
            self._connected.clear()
            self.logger.error(
                "MQTT publisher connect failed (rc={})".format(rc))

    def _on_disconnect(self, client, userdata, rc):
        self._connected.clear()
        if rc != 0:
            self.logger.warning(
                "MQTT publisher unexpectedly disconnected (rc={})".format(rc))
