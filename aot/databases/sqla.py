# coding=utf-8
"""모델 층의 SQLAlchemy·Marshmallow 객체 — 정본 (아키텍처 4a, `docs/design/space-domain-package.md`).

모델(`aot.databases.models`)과 공간 도메인(`aot.space`)은 웹 패키지보다 아래층이다.
예전에는 이 두 객체가 `aot.aot_flask.extensions` 에 있어서, 모델을 import 하는 순간
웹 패키지가 함께 올라왔다. 객체는 그대로이고(설정은 지금처럼 앱 팩토리가
`db.init_app(app)` 으로 붙인다) 사는 자리만 아래로 옮겼다.
`aot.aot_flask.extensions` 는 같은 객체를 다시 내보낸다.

Flask-SQLAlchemy 를 쓰므로 `Model.query`·`db.session` 은 지금처럼 앱 컨텍스트가
있어야 동작한다 — 그 요구는 이 이동으로 바뀌지 않는다.
"""
from flask import app
from flask_sqlalchemy import SQLAlchemy
from flask_marshmallow import Marshmallow  # must be imported after SQLAlchemy

db = SQLAlchemy()
ma = Marshmallow(app)
