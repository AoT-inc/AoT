# coding=utf-8
"""Docker 백업이 지도 오버레이(aot_geo_overlays 볼륨)를 담고 되돌리는지 지키는 가드.

오버레이 이미지는 사용자가 올린 원본(드론·항공사진)이라 다시 만들 방법이 없고,
DB 에는 URL 만 있다. 백업에서 빠지면 복원 뒤 오버레이가 전부 404 가 된다.
Docker·네트워크를 쓰지 않고 임시 폴더로만 돈다.
"""
import os
import tempfile

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


def test_matter_fabric_is_backed_up_but_never_restored(tmp_path, monkeypatch):
    """Matter Fabric 저장소는 백업에는 담기고 자동 복원은 되지 않는다.

    aot-app 에는 읽기 전용으로 마운트되고, 돌고 있는 matter_server 밑에서
    바꿔치기하면 안 된다(docs/design/matter-controller.md §6). 복원 루프가 이
    폴더를 건드리면 읽기 전용 마운트에서 예외가 나 복원 전체가 실패한다.
    """
    live = tmp_path / "matter_data"
    live.mkdir()
    (live / "fabric.json").write_text("orig")
    # 서버의 API 소켓도 이 볼륨 안에 있다. copy2 로 열면 백업 전체가 실패한다.
    import socket
    sock_path = os.path.join(tempfile.mkdtemp(prefix="mb"), "s")
    srv = socket.socket(socket.AF_UNIX)
    srv.bind(sock_path)
    os.rename(sock_path, live / "matter-server.sock")
    backups = tmp_path / "backups"

    monkeypatch.setattr(docker_backup, "UPLOAD_DIRS", [])
    monkeypatch.setattr(docker_backup, "BACKUP_ONLY_DIRS", [(str(live), "matter_data")])
    monkeypatch.setattr(docker_backup, "BACKUP_PATH", str(backups))
    monkeypatch.setattr(docker_backup, "SQL_DATABASE_AOT", str(tmp_path / "none.db"))
    monkeypatch.setattr(docker_backup, "_terminate_daemon_sync", lambda *a, **k: None)
    monkeypatch.setattr(docker_backup, "generate_widget_html", lambda *a, **k: None)
    monkeypatch.setattr(docker_backup, "reload_frontend", lambda *a, **k: None)

    assert docker_backup.docker_backup_estimate_size() == len("orig")
    status, dest = docker_backup.docker_backup_create()
    assert status == 0, dest
    assert open(os.path.join(dest, "matter_data", "fabric.json")).read() == "orig"
    assert not os.path.exists(os.path.join(dest, "matter_data", "matter-server.sock"))
    srv.close()

    (live / "fabric.json").write_text("changed")
    assert docker_backup.docker_backup_restore(dest)[0] == 0
    assert (live / "fabric.json").read_text() == "changed"


def test_live_dir_copy_failure_does_not_fail_the_backup(tmp_path, monkeypatch):
    """Matter 서버가 백업 중 파일을 바꿔 복사가 실패해도 백업은 DB 와 나머지로
    성공한다. 반쯤 복사된 Fabric 폴더는 남기지 않는다."""
    live = tmp_path / "matter_data"
    live.mkdir()
    (live / "fabric.json").write_text("orig")
    backups = tmp_path / "backups"
    monkeypatch.setattr(docker_backup, "UPLOAD_DIRS", [])
    monkeypatch.setattr(docker_backup, "BACKUP_ONLY_DIRS", [(str(live), "matter_data")])
    monkeypatch.setattr(docker_backup, "BACKUP_PATH", str(backups))
    monkeypatch.setattr(docker_backup, "SQL_DATABASE_AOT", str(tmp_path / "none.db"))
    monkeypatch.setattr(docker_backup.time, "sleep", lambda s: None)

    real_copytree = docker_backup.shutil.copytree

    def flaky_copytree(src, dst, **kw):
        if src == str(live):
            os.makedirs(dst, exist_ok=True)
            open(os.path.join(dst, "half"), "w").close()
            raise docker_backup.shutil.Error([("x", "y", "vanished")])
        return real_copytree(src, dst, **kw)

    monkeypatch.setattr(docker_backup.shutil, "copytree", flaky_copytree)
    status, dest = docker_backup.docker_backup_create()
    assert status == 0, dest
    assert not os.path.exists(os.path.join(dest, "matter_data"))
