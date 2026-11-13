# coding=utf-8
"""모델 층의 db·ma 정본은 `aot.databases.sqla` 다 (아키텍처 4a).

1. 웹 패키지의 `aot.aot_flask.extensions.db/ma` 는 **같은 객체**여야 한다 — 둘로
   갈라지면 모델은 한 객체에, 앱 팩토리의 `db.init_app` 은 다른 객체에 붙어 모든
   쿼리가 "앱에 등록되지 않음" 으로 죽는다.
2. 모델을 import 해도 웹 패키지(`aot.aot_flask`)가 올라오지 않는다. 새 프로세스에서
   실제로 올라온 모듈을 본다 — 소스만 세는 가드(`models-no-app`)와 다른 방법이다.
"""
import subprocess
import sys


def test_web_extensions_reexport_the_same_objects():
    from aot.aot_flask import extensions
    from aot.databases import sqla
    assert extensions.db is sqla.db
    assert extensions.ma is sqla.ma


def test_importing_models_does_not_load_the_web_package():
    code = ('import sys, aot.databases.models\n'
            "print(','.join(sorted(m for m in sys.modules "
            "if m.startswith('aot.aot_flask'))))")
    out = subprocess.run([sys.executable, '-c', code], capture_output=True,
                         text=True, check=True).stdout.strip()
    assert out == '', f'모델 import 가 웹 패키지를 올렸다: {out}'
