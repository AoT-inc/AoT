# coding=utf-8
"""Docker 백업이 지도 오버레이(aot_geo_overlays 볼륨)를 담고 되돌리는지 지키는 가드.

오버레이 이미지는 사용자가 올린 원본(드론·항공사진)이라 다시 만들 방법이 없고,
DB 에는 URL 만 있다. 백업에서 빠지면 복원 뒤 오버레이가 전부 404 가 된다.
Docker·네트워크를 쓰지 않고 임시 폴더로만 돈다.
"""
import os

from aot.utils import docker_backup


def test_geo_overlays_is_in_backup_dirs():
    names = [sub for _src, sub in docker_backup.UPLOAD_DIRS]
    assert "geo_overlays" in names
    src = dict((sub, d) for d, sub in docker_backup.UPLOAD_DIRS)["geo_overlays"]
    assert src.replace(os.sep, "/").endswith("static/uploads/geo_overlays")


def test_geo_overlays_round_trip_including_tiles(tmp_path, monkeypatch):
    live = tmp_path / "live_overlays"
    (live / "tiles" / "7").mkdir(parents=True)
    (live / "a.jpg").write_bytes(b"orig")
    (live / "tiles" / "7" / "0.png").write_bytes(b"tile")
    backups = tmp_path / "backups"

    monkeypatch.setattr(docker_backup, "UPLOAD_DIRS", [(str(live), "geo_overlays")])
    monkeypatch.setattr(docker_backup, "BACKUP_PATH", str(backups))
    monkeypatch.setattr(docker_backup, "SQL_DATABASE_AOT", str(tmp_path / "none.db"))

    status, dest = docker_backup.docker_backup_create()
    assert status == 0
    assert (open(os.path.join(dest, "geo_overlays", "a.jpg"), "rb").read() == b"orig")
    assert os.path.isfile(os.path.join(dest, "geo_overlays", "tiles", "7", "0.png"))

    # 복원: 라이브 내용을 지운 뒤 백업으로 되돌린다.
    (live / "a.jpg").write_bytes(b"changed")
    (live / "extra.png").write_bytes(b"x")
    docker_backup._replace_dir_contents(str(live), os.path.join(dest, "geo_overlays"))
    assert (live / "a.jpg").read_bytes() == b"orig"
    assert not (live / "extra.png").exists()
    assert (live / "tiles" / "7" / "0.png").exists()
