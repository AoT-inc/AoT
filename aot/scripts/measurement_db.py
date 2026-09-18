# -*- coding: utf-8 -*-
"""Detect and report InfluxDB connection info."""
import argparse
import json
import logging
import os
import sys

import requests

sys.path.append(os.path.abspath(os.path.join(__file__, "../../..")))

logger = logging.getLogger("aot.measurement_db")


def get_influxdb_host(settings):
    """Resolve the reachable InfluxDB hostname from settings or known defaults.

    @phase runtime
    @dependency requests
    """
    try:
        if settings and settings.measurement_db_host:
            return settings.measurement_db_host
    except Exception as err:
        logger.debug(f"Could not determine influxdb host from table: {err}")

    list_hosts = [
        'localhost',
        '127.0.0.1',
        'aot_influxdb'
    ]
    for host in list_hosts:
        try:
            if requests.get(f"http://{host}:8086/ping").status_code == 204:
                return host
        except Exception as err:
            logger.debug(f"Could not determine localhost as influxdb host: {err}")

def _ping(host, port):
    """InfluxDB 에 버전을 묻는다 — **실제로 닿는 호스트**로.

    저장된 호스트(`localhost` 등)를 그대로 쓰면 컨테이너 안에서는 빗나간다.
    도커 구성은 `INFLUXDB_HOST` 로 사이드카(`influxdb`)를 가리키고, 실제 쓰기
    경로(`aot/utils/influx.py`)는 `resolve_measurement_db_host` 로 그것을 따른다.
    그런데 여기 버전 감지만 그 규칙을 따르지 않아, 신규 도커 설치에서
    `localhost:8086` 에 묻고 실패해 **버전이 빈 값으로 굳었다.** 버전이 비면 쓰기가
    "Unknown Influxdb version" 으로 전부 거부되므로, 센서 값이 조용히 한 점도
    저장되지 않았다(2026-09-18, 종단 검사의 새 스택에서 실측). 이미 버전이
    채워진 설치는 영향이 없다.

    저장되는 호스트 값은 바꾸지 않는다 — 묻는 순간에만 해석한다. 쓰기 경로와
    같은 방식이다.

    timeout 을 둔다: 이 함수는 모델 정의 시점(앱 부팅)에도 불리므로, 응답 없는
    호스트를 붙들고 있으면 부팅 자체가 멈춘다.
    """
    from aot.config import resolve_measurement_db_host
    return requests.get(
        f"http://{resolve_measurement_db_host(host)}:{port}/ping", timeout=5)


def get_influxdb_info():
    """Collect InfluxDB version, host, port, and retention policy into a dict.

    @phase runtime
    @dependency requests, aot.databases.models
    """
    settings = None
    dict_info = {
        'db_name': None,
        'db_version': None,
        'influxdb_installed': None,
        'influxdb_retention_policy': None,
        'influxdb_version': None,
        'influxdb_host': None,
        'influxdb_port': None
    }
    try:
        from aot.databases.models import Misc
        from aot.utils.database import db_retrieve_table_daemon
        settings = db_retrieve_table_daemon(Misc, entry='first')
    except Exception as err:
        logger.debug(f"Could not determine influxdb info from table: {err}")

    try:
        r = None
        if settings:
            # First check if user-set host:port is accessible
            dict_info['db_name'] = settings.measurement_db_name
            dict_info['db_version'] = settings.measurement_db_version
            dict_info['influxdb_host'] = settings.measurement_db_host
            dict_info['influxdb_port'] = settings.measurement_db_port
            dict_info['influxdb_retention_policy'] = settings.measurement_db_retention_policy
            r = _ping(dict_info['influxdb_host'], dict_info['influxdb_port'])

        if not r or not r.headers or "X-Influxdb-Version" not in r.headers:
            # Next, check if local host:port is accessible
            dict_info['influxdb_host'] = get_influxdb_host(settings)
            dict_info['influxdb_port'] = 8086
            r = _ping(dict_info['influxdb_host'], dict_info['influxdb_port'])

        if r.headers and "X-Influxdb-Version" in r.headers:
            dict_info['influxdb_installed'] = True
            dict_info['influxdb_version'] = r.headers["X-Influxdb-Version"]

            # Remove v from "v2.x" version string
            if dict_info['influxdb_version'].startswith("v"):
                dict_info['influxdb_version'] = dict_info['influxdb_version'][1:]
    except Exception as err:
        logger.debug(f"Could not determine influxdb info: {err}")
    
    logger.info(f"Influxdb info: {dict_info}")

    return dict_info


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Perform actions with the measurement database")

    options = parser.add_argument_group('Options')
    options.add_argument('-i', '--info', action='store_true',
                         help="Info about the measurement database")

    args = parser.parse_args()

    if args.info:
        dict_influx = get_influxdb_info()
        print(json.dumps(dict_influx))
