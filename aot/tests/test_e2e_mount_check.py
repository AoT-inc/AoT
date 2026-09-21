# -*- coding: utf-8 -*-
"""E2E 스택의 워크트리 확인이 Docker Desktop 경로 표기를 같은 곳으로 보는지.

배경 — 2026-09-21. 컨테이너가 보고하는 바인드 원본이 `/host_mnt/Users/...` 로
나오는 경우(Docker Desktop, 끝이 `/` 인 바인드)를 남의 워크트리로 오판해 E2E 를
멈췄다. 비교 전에 그 접두어를 벗긴다.
"""
import importlib.util
import os

_CONFTEST = os.path.join(os.path.dirname(__file__), 'e2e', 'conftest.py')


def _load():
    spec = importlib.util.spec_from_file_location('_e2e_conftest', _CONFTEST)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_docker_desktop_prefix_is_the_same_place(tmp_path):
    c = _load()
    here = os.path.realpath(str(tmp_path))
    assert c._normalize_mount('/host_mnt' + here) == here
    assert c._normalize_mount('/host_mnt' + here + '/') == here
    assert c._normalize_mount(here) == here


def test_a_different_worktree_is_still_different(tmp_path):
    c = _load()
    other = tmp_path / 'other'
    other.mkdir()
    assert c._normalize_mount('/host_mnt' + str(other)) != os.path.realpath(str(tmp_path))
    # 접두어처럼 생겼지만 경로 구분자가 없는 것은 벗기지 않는다.
    assert c._normalize_mount('/host_mntx/a') == os.path.realpath('/host_mntx/a')
