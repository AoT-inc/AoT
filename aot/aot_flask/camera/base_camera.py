# -*- coding: utf-8 -*-
# From https://github.com/miguelgrinberg/flask-video-streaming
import logging
import threading
import time

try:
    from greenlet import getcurrent as get_ident
except ImportError:
    try:
        from thread import get_ident
    except ImportError:
        from _thread import get_ident

logger = logging.getLogger(__name__)


def load_camera_settings(unique_id, fallback=None):
    """카메라 설정을 DB 에서 다시 읽어 평범한 객체로 돌려준다.

    백그라운드 스레드는 요청 컨텍스트가 없고 오래 살아남으므로, 시작할 때 읽은
    값을 붙들고 있으면 설정을 고쳐도 반영되지 않는다. 재접속 때마다 부른다.
    읽기에 실패하면 fallback 을 쓴다.
    """
    from types import SimpleNamespace
    try:
        from aot.databases.models import Camera
        from aot.utils.database import db_retrieve_table_daemon
        row = db_retrieve_table_daemon(Camera, unique_id=unique_id)
        if row is None or isinstance(row, list):
            return fallback
        return SimpleNamespace(**{
            col.name: getattr(row, col.name) for col in row.__table__.columns})
    except Exception:
        logger.exception('[{id}] Could not reload camera settings'.format(id=unique_id))
        return fallback


class CameraEvent(object):
    """An Event-like class that signals all active clients when a new frame is
    available.
    """
    def __init__(self):
        self.events = {}

    def wait(self, timeout=None):
        """Invoked from each client's thread to wait for the next frame."""
        ident = get_ident()
        if ident not in self.events:
            # this is a new client
            # add an entry for it in the self.events dict
            # each entry has two elements, a threading.Event() and a timestamp
            self.events[ident] = [threading.Event(), time.time()]
        return self.events[ident][0].wait(timeout=timeout)

    def set(self):
        """Invoked by the camera thread when a new frame is available."""
        now = time.time()
        remove = None
        for ident, event in self.events.items():
            if not event[0].isSet():
                # if this client's event is not set, then set it
                # also update the last set timestamp to now
                event[0].set()
                event[1] = now
            else:
                # if the client's event is already set, it means the client
                # did not process a previous frame
                # if the event stays set for more than 5 seconds, then assume
                # the client is gone and remove it
                if now - event[1] > 5:
                    remove = ident
        if remove:
            del self.events[remove]

    def clear(self):
        """Invoked from each client's thread after a frame was processed."""
        self.events[get_ident()][0].clear()


class BaseCamera(object):
    thread = {}  # background thread that reads frames from camera
    frame = {}  # current frame is stored here by background thread
    last_access = {}  # time of last client access to the camera
    event = {}
    running = {}

    # 카메라가 연결/인증에 실패해 프레임을 전혀 만들지 못하면 백그라운드 스레드는
    # 계속 재시도하지만, 이 값을 넘기면 요청 스레드는 포기하고 예외를 던진다.
    # (없으면 gunicorn 스레드가 영구히 블로킹되어 스레드 풀이 고갈된다.)
    FRAME_WAIT_TIMEOUT = 15

    def __init__(self, unique_id=None):
        """Start the background camera thread if it isn't running yet."""
        self.unique_id = unique_id
        BaseCamera.event[self.unique_id] = CameraEvent()
        BaseCamera.running[self.unique_id] = True

        if self.unique_id not in BaseCamera.thread:
            BaseCamera.thread[self.unique_id] = None

        if BaseCamera.thread[self.unique_id] is None:
            BaseCamera.last_access[self.unique_id] = time.time()

            # start background frame thread
            BaseCamera.thread[self.unique_id] = threading.Thread(
                target=self._thread, args=(self.unique_id,))
            BaseCamera.thread[self.unique_id].start()

            # wait until frames are available, but not forever
            deadline = time.time() + self.FRAME_WAIT_TIMEOUT
            while self.get_frame(timeout=1) is None:
                if time.time() > deadline:
                    raise TimeoutError(
                        'Camera {id} produced no frame within {timeout}s '
                        '(connection or authentication failure?)'.format(
                            id=self.unique_id, timeout=self.FRAME_WAIT_TIMEOUT))

    def get_frame(self, timeout=None):
        """Return the current camera frame, or None if none arrived within timeout."""
        BaseCamera.last_access[self.unique_id] = time.time()

        # wait for a signal from the camera thread
        if not BaseCamera.event[self.unique_id].wait(timeout=timeout):
            return None
        BaseCamera.event[self.unique_id].clear()

        return BaseCamera.frame.get(self.unique_id)

    @staticmethod
    def frames():
        """"Generator that returns frames from the camera."""
        raise RuntimeError('Must be implemented by subclasses')

    # 시청자가 없다고 보고 스레드를 끝내는 시간(초)
    IDLE_TIMEOUT = 10
    # 카메라별 유예(초). 서브클래스가 "연결이 살아 있는 동안만" 늘리고 끊기면 지운다 —
    # 접속에 실패하는 동안에는 기본값(IDLE_TIMEOUT)이 적용되어 재시도가 길어지지 않는다.
    idle_grace = {}

    @classmethod
    def should_stop(cls, unique_id):
        """스레드를 끝내야 하는가 — 종료 판정은 이 한 곳에서만 한다.

        프레임을 받은 뒤뿐 아니라 접속 실패·재시도 대기 중에도 서브클래스가
        이 함수를 불러야 한다. 안 그러면 한 번도 열리지 않는 카메라의 스레드는
        비활성화해도 영원히 재시도한다.
        """
        if not BaseCamera.running.get(unique_id, False):
            return True
        last = BaseCamera.last_access.get(unique_id)
        limit = BaseCamera.idle_grace.get(unique_id, cls.IDLE_TIMEOUT)
        return last is not None and time.time() - last > limit

    @classmethod
    def sleep_unless_stopped(cls, unique_id, seconds):
        """seconds 동안 1초 단위로 쉬되 종료 조건이 되면 True 를 돌려주고 중단."""
        end = time.time() + seconds
        while time.time() < end:
            if cls.should_stop(unique_id):
                return True
            time.sleep(min(1.0, max(0.0, end - time.time())))
        return cls.should_stop(unique_id)

    @classmethod
    def _frames_iterator(cls, unique_id):
        import inspect
        try:
            takes_id = len(inspect.signature(cls.frames).parameters) > 0
        except (TypeError, ValueError):
            takes_id = False
        return cls.frames(unique_id) if takes_id else cls.frames()

    @classmethod
    def _thread(cls, unique_id):
        """Camera background thread."""
        logger.info('[{id}] Starting camera thread'.format(id=unique_id))
        frames_iterator = None
        try:
            frames_iterator = cls._frames_iterator(unique_id)
            for frame in frames_iterator:
                # None 은 "살아 있음" 신호(접속 재시도 중) — 저장하지 않고 검사만 한다
                if frame is not None:
                    BaseCamera.frame[unique_id] = frame
                    BaseCamera.event[unique_id].set()  # send signal to clients
                time.sleep(0)

                # if there haven't been any clients asking for frames in
                # the last IDLE_TIMEOUT seconds then stop the thread
                if cls.should_stop(unique_id) and BaseCamera.running.get(unique_id):
                    logger.info('[{id}] Stopping camera thread due to '
                                'inactivity'.format(id=unique_id))
                    break
                if not BaseCamera.running.get(unique_id):
                    logger.info('[{id}] Camera thread instructed to '
                                'shut down'.format(id=unique_id))
                    break
        except Exception:
            logger.exception('[{id}] Camera thread crashed'.format(id=unique_id))
        finally:
            if frames_iterator is not None:
                try:
                    frames_iterator.close()
                except Exception:
                    pass
            BaseCamera.thread[unique_id] = None
            BaseCamera.running[unique_id] = False
            BaseCamera.idle_grace.pop(unique_id, None)

    @staticmethod
    def stop(unique_id):
        BaseCamera.running[unique_id] = False

    @staticmethod
    def is_running(unique_id):
        return BaseCamera.running[unique_id]
