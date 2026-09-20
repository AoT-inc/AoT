# coding=utf-8
"""업그레이드가 사용자 업로드를 새 설치로 옮기는지 지키는 회귀 가드.

인앱 업그레이드(`aot/scripts/upgrade_install.sh`)는 릴리스 압축 파일로 새
폴더를 만들고 **고른 폴더만** 복사한 뒤 옛 설치를 /var/AoT-backups 로 밀어낸다.
복사 목록에 업로드 폴더가 없어서 네이티브 설치에서 노트 사진과 지도
오버레이 이미지가 업그레이드마다 404(엑박)가 됐다.

이 파일이 막는 것:
  1. 앱이 업로드를 쓰는 경로가 새로 생기거나 바뀌었는데 복사 목록이 그대로인 경우
  2. 복사 코드가 폴더를 한 겹 더 깊게 중첩하거나 하위 폴더(tiles/ 등)를 빠뜨리는 경우
  3. Docker 설치가 오버레이 이미지를 볼륨으로 잡지 않아 이미지 교체 때 사라지는 경우

네트워크·Docker·root 를 쓰지 않는다.
"""
import os
import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "aot" / "scripts" / "upgrade_install.sh"
COMPOSE_PROD = REPO / "docker" / "docker-compose.prod.yml"

# routes_geo_layer.py 의 _OVERLAY_SUBDIR / model_asset_io.py 의 UPLOAD_SUBDIR 는
# Flask static 폴더 아래 'uploads/...' 다. (import 하면 앱 전체가 딸려 와서 소스로 확인)
STATIC_UPLOADS = "aot/aot_flask/static/uploads"


def _copy_loop():
    """upgrade_install.sh 안의 `for USER_DATA_DIR in ... done` 블록."""
    text = SCRIPT.read_text()
    match = re.search(r"^  for USER_DATA_DIR in .*?^  done$", text,
                      re.MULTILINE | re.DOTALL)
    assert match, "upgrade_install.sh 에서 USER_DATA_DIR 복사 루프를 찾지 못했다"
    return match.group(0)


def _listed_dirs():
    header = _copy_loop().splitlines()[0]
    return re.search(r"USER_DATA_DIR in (.*?) ;", header).group(1).split()


def _covered(rel_path, listed):
    return any(rel_path == d or rel_path.startswith(d + "/") for d in listed)


def test_every_runtime_upload_dir_is_carried_over():
    from aot.config import (INSTALL_DIRECTORY, PATH_FACILITY_PHOTOS,
                            PATH_GEO_ZONE_PHOTOS, PATH_NOTE_ATTACHMENTS,
                            PATH_NOTICE_ATTACHMENTS)
    listed = _listed_dirs()
    written = {
        "PATH_NOTE_ATTACHMENTS": PATH_NOTE_ATTACHMENTS,
        "PATH_NOTICE_ATTACHMENTS": PATH_NOTICE_ATTACHMENTS,
        "PATH_FACILITY_PHOTOS": PATH_FACILITY_PHOTOS,
        "PATH_GEO_ZONE_PHOTOS": PATH_GEO_ZONE_PHOTOS,
    }
    for name, path in written.items():
        rel = os.path.relpath(path, INSTALL_DIRECTORY).replace(os.sep, "/")
        assert _covered(rel, listed), (
            f"{name}({rel}) 이 upgrade_install.sh 복사 목록 {listed} 에 없다 — "
            "업그레이드 때 이 폴더의 파일이 사라진다")

    # Flask static 아래 업로드: 오버레이 이미지·타일, 3D 모델 자산
    geo = (REPO / "aot" / "aot_flask" / "routes_geo_layer.py").read_text()
    assert "_OVERLAY_SUBDIR = os.path.join('uploads', 'geo_overlays')" in geo
    assert _covered(STATIC_UPLOADS + "/geo_overlays", listed)
    assert _covered(STATIC_UPLOADS + "/model_assets", listed)


def _run_loop(tmp_path, prepare):
    """복사 루프만 실제 bash 로 돌린다. (전체 스크립트는 root·/var/aot-root 가 필요)"""
    cur = tmp_path / "current"
    new = tmp_path / "new"
    cur.mkdir()
    new.mkdir()
    prepare(cur, new)
    harness = (
        'CURRENT_AOT_DIRECTORY="$1"\nTHIS_AOT_DIRECTORY="$2"\n'
        'error_found() { echo ERROR_FOUND; exit 1; }\n' + _copy_loop() + "\n"
    )
    return cur, new, subprocess.run(
        ["bash", "-c", harness, "bash", str(cur), str(new)],
        capture_output=True, text=True)


def _write(path, data=b"x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def test_uploads_are_copied_with_subfolders_and_not_nested(tmp_path):
    def prepare(cur, new):
        _write(cur / "uploads/notes/2026/06/a_IMG.jpeg", b"note")
        _write(cur / "uploads/facility_photos/p.jpg", b"fac")
        _write(cur / "note_attachments/legacy.png", b"legacy")
        _write(cur / STATIC_UPLOADS / "geo_overlays/fish.jpg", b"overlay")
        _write(cur / STATIC_UPLOADS / "geo_overlays/tiles/L1/5/3/2.png", b"tile")
        _write(cur / STATIC_UPLOADS / "model_assets/previews/m.png", b"model")
        # 새 트리에 같은 폴더가 이미 있어도 한 겹 더 깊게 들어가면 안 된다
        _write(new / "uploads/keep.txt", b"already in new tree")

    _cur, new, result = _run_loop(tmp_path, prepare)
    assert result.returncode == 0, result.stdout + result.stderr

    assert (new / "uploads/notes/2026/06/a_IMG.jpeg").read_bytes() == b"note"
    assert (new / "uploads/facility_photos/p.jpg").read_bytes() == b"fac"
    assert (new / "note_attachments/legacy.png").read_bytes() == b"legacy"
    assert (new / STATIC_UPLOADS / "geo_overlays/fish.jpg").read_bytes() == b"overlay"
    assert (new / STATIC_UPLOADS / "geo_overlays/tiles/L1/5/3/2.png").read_bytes() == b"tile"
    assert (new / STATIC_UPLOADS / "model_assets/previews/m.png").read_bytes() == b"model"
    assert (new / "uploads/keep.txt").exists()
    assert not (new / "uploads/uploads").exists(), "폴더가 한 겹 중첩됐다"


def test_old_install_is_left_intact(tmp_path):
    """복사이지 이동이 아니다 — 백업으로 밀려난 옛 설치가 그대로 복원 가능해야 한다."""
    def prepare(cur, new):
        _write(cur / "uploads/notes/a.jpg", b"n")

    cur, _new, result = _run_loop(tmp_path, prepare)
    assert result.returncode == 0
    assert (cur / "uploads/notes/a.jpg").read_bytes() == b"n"


def test_missing_source_dirs_are_skipped(tmp_path):
    """업로드가 한 번도 없던 설치(폴더 없음)에서 업그레이드가 실패하면 안 된다."""
    _cur, new, result = _run_loop(tmp_path, lambda cur, new: None)
    assert result.returncode == 0
    assert list(new.iterdir()) == []


@pytest.mark.skipif(os.geteuid() == 0, reason="root 는 권한 없는 파일도 읽는다")
def test_copy_failure_stops_the_upgrade(tmp_path):
    """복사에 실패했는데 조용히 넘어가면 사용자는 파일을 잃고도 모른다."""
    def prepare(cur, new):
        secret = cur / "uploads/notes/secret.jpg"
        _write(secret)
        secret.chmod(0)

    _cur, _new, result = _run_loop(tmp_path, prepare)
    assert result.returncode == 1
    assert "ERROR_FOUND" in result.stdout


def test_docker_prod_keeps_geo_overlays_in_a_volume():
    text = COMPOSE_PROD.read_text()
    assert ("- aot_geo_overlays:/app/aot/aot_flask/static/uploads/geo_overlays"
            in text)
    assert re.search(r"^  aot_geo_overlays:\s*$", text, re.MULTILINE), \
        "최상위 volumes 에 aot_geo_overlays 선언이 없다"
