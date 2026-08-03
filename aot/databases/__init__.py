# coding=utf-8
import secrets
import uuid

from flask import current_app

from aot.aot_flask.extensions import db


class CRUDMixin(object):
    """
    Provides basic Create, Read, Update and Delete methods to SQLAlchemy models.
    Mix this class into any db.Model to inherit save() and delete() with
    automatic session commit. All methods delegate to Flask-SQLAlchemy's db.session.

    @phase active
    @dependency db
    """

    def save(self):
        """Add this model to the session and commit. Returns self for chaining.

        @phase active
        """
        db.session.add(self)
        db.session.commit()
        return self

    def delete(self):
        """Remove this model from the session and commit.

        @phase active
        """
        db.session.delete(self)
        db.session.commit()


def set_api_key(length):
    """Generate a cryptographically random API key of the given byte length.

    @phase active
    """
    return secrets.token_bytes(length)


def set_uuid():
    """Return a UUID4 string for use as a unique identifier.

    @phase active
    """
    return str(uuid.uuid4())


# [I10] 복제 시 암묵 복사가 금지되는 교차참조 컬럼. 이 값들은 다른 행/지도를
# 가리키는 링크라서 그대로 복사하면 복제본이 원본의 지도·zone 을 가리킨다
# (2026-08-03 사고: 복제된 장치의 map_overlay_id 가 남의 지도 도형을 가리킴).
# 필요하면 호출자가 kwargs 로 명시적으로 넘겨야 한다.
CLONE_CROSS_REF_DENYLIST = ('map_overlay_id', 'map_config_id')


def clone_model(model, **kwargs):
    """Clone an arbitrary SQLAlchemy model object without its primary key values.

    Loads the model's data, copies all non-pk columns into a new instance,
    applies any override kwargs, then saves the clone. Returns the new object
    or None if the model has no loaded primary key.

    [I10] 교차참조 컬럼(CLONE_CROSS_REF_DENYLIST)은 암묵 복사하지 않는다 —
    복제본은 '미배치' 상태로 시작하고, 링크가 필요하면 호출자가 kwargs 로
    명시한다. 앞으로 추가되는 모델도 자동으로 보호된다.

    @phase active
    @dependency db
    """
    # Ensure the model’s data is loaded before copying.
    try:
        model.id
    except Exception:
        return

    table = model.__table__
    non_pk_columns = [k for k in table.columns.keys() if k not in table.primary_key]
    data = {c: getattr(model, c) for c in non_pk_columns
            if c not in CLONE_CROSS_REF_DENYLIST}
    data.update(kwargs)

    clone = model.__class__(**data)
    db.session.add(clone)
    db.session.commit()
    return clone
