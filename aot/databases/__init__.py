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


def clone_model(model, **kwargs):
    """Clone an arbitrary SQLAlchemy model object without its primary key values.

    Loads the model's data, copies all non-pk columns into a new instance,
    applies any override kwargs, then saves the clone. Returns the new object
    or None if the model has no loaded primary key.

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
    data = {c: getattr(model, c) for c in non_pk_columns}
    data.update(kwargs)

    clone = model.__class__(**data)
    db.session.add(clone)
    db.session.commit()
    return clone
