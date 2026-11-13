# coding=utf-8
"""python -m aot.twin [--once] [--overrides PATH]          배포형 서비스(기본) — compose `aot_twin`·`aottwin.service`
   python -m aot.twin --config PATH [--once]              개발용 JSON 노드(원격 REST·수신 API, NAS 시험)

배포형은 이 기기의 DB 설정(설정 > 일반 > 디지털트윈)을 따른다: 꺼져 있으면 일하지 않고, 낮은 사양이면 잠긴다.
개발용은 `--config`(또는 `$AOT_TWIN_CONFIG`) JSON 의 `servers[]` 를 그대로 돈다 — 기본 배포 경로에는 쓰지 않는다.
"""
import argparse
import json
import logging
import os
import sys

from . import settings


def _print_reports(reps) -> None:
    for r in reps:
        print(f"{r.server_id} {r.target_key[1:]} status={r.status.name if r.status is not None else None}"
              f" points={r.points} written={r.written} rejected={r.rejected} err={r.error}"
              f" elapsed={r.elapsed_s:.1f}s {r.reason}")
        if r.info:
            print("  info " + json.dumps(r.info, ensure_ascii=False, default=str))


def _dev_node(path, once: bool) -> int:
    from .node import TwinNode
    cfg = settings.load(path)
    if not cfg.enabled:
        logging.getLogger("aot.twin").warning("트윈이 꺼져 있다(enabled=false) — 아무것도 하지 않고 종료")
        return 0
    for n in cfg.notices():                       # 예: 원격 쓰기 비활성 — 실행해도 결과를 되돌려 쓰지 못한다
        print("NOTICE " + n)
    node = TwinNode(cfg)
    if once:
        node.startup_bench()
        reps = node.run_once()
        _print_reports(reps)
        return 0 if all(r.error is None and r.rejected == 0 for r in reps) else 1
    node.serve()
    return 0


def park_if_locked(svc, exec_fn=os.execvp, docker=None) -> None:
    """잠긴 서비스가 Docker 안이면 프로세스를 `sleep infinity` 로 바꿔 메모리를 거의 안 쓰고 남는다.

    배포 compose 의 `aot_twin` 은 `restart: unless-stopped` 다. Docker 의 `on-failure` 는 "데몬이 재시작하면
    컨테이너를 다시 띄우지 않는다" 라서(Docker 공식 문서) 정전·재부팅 뒤 트윈이 돌아오지 못한다 —
    `on-failure` 로 되돌리지 말 것. 그런데 `unless-stopped` 는 exit 0 도 되살리므로, 잠긴 기기가 종료하면
    잠금 판정과 시작을 무한히 되풀이한다. 그래서 잠겼으면 하트비트 `locked` 를 쓴 뒤 종료하지 않고 `sleep`
    으로 바꿔 대기한다(잠금은 기기 고정값이라 다시 떠도 같은 결과). 직접 설치(systemd)는 exit 0 이고
    `Restart=on-failure` 가 되살리지 않는다 — 부팅 때는 enable 된 유닛이 다시 뜬다.
    """
    if not getattr(svc, "locked_reason", None):
        return
    if docker is None:
        from aot.utils.system_environment import is_docker
        docker = is_docker()
    if docker:
        logging.getLogger("aot.twin").warning("트윈: 잠긴 기기 — 종료하지 않고 대기한다(sleep infinity)")
        exec_fn("sleep", ["sleep", "infinity"])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="aot_twin")
    ap.add_argument("--config", help="개발용 JSON 노드 설정 (기본: $AOT_TWIN_CONFIG). 없으면 배포형 서비스")
    ap.add_argument("--overrides", help="배포형(개발용): DB 의 대지·구획 트윈 설정 위에 겹칠 JSON "
                                        "(기본: $AOT_TWIN_OVERRIDES — 없으면 DB 설정만)")
    ap.add_argument("--once", action="store_true", help="한 번만 돌고 종료")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    dev = a.config or os.environ.get("AOT_TWIN_CONFIG", "")
    if dev:
        return _dev_node(dev, a.once)
    from .service import build_db_service
    svc = build_db_service(a.overrides)
    if a.once:
        reps = svc.run_all_once()
        _print_reports(reps)
        if svc.locked_reason:
            print(f"locked: {svc.locked_reason}")
        return 0 if all(r.error is None and r.rejected == 0 for r in reps) else 1
    try:
        svc.serve()
    except KeyboardInterrupt:
        svc.stop()
    park_if_locked(svc)                    # 잠긴 Docker 컨테이너만 — 아니면 그대로 exit 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
