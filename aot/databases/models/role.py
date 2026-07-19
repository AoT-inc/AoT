# coding=utf-8
from aot.databases import CRUDMixin
from aot.databases import set_uuid
from aot.aot_flask.extensions import db


class Role(CRUDMixin, db.Model):
    """
    Defines a named set of permissions for operators.

    Roles are seeded from USER_ROLES in aot.config at first run and may be updated
    on subsequent population calls. Each role grants boolean flags for view, edit,
    and reset capabilities across settings, controllers, users, cameras, stats, and logs.

    @phase active
    """
    __tablename__ = "roles"
    __table_args__ = {'extend_existing': True}
    # __abstract__ = True

    id = db.Column(db.Integer, unique=True, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)
    name = db.Column(db.String(36), nullable=False, unique=True)
    edit_settings = db.Column(db.Boolean, nullable=False, default=False)
    edit_controllers = db.Column(db.Boolean, nullable=False, default=False)
    edit_users = db.Column(db.Boolean, nullable=False, default=False)
    view_settings = db.Column(db.Boolean, nullable=False, default=False)
    view_camera = db.Column(db.Boolean, nullable=False, default=False)
    view_stats = db.Column(db.Boolean, nullable=False, default=False)
    view_logs = db.Column(db.Boolean, nullable=False, default=False)
    reset_password = db.Column(db.Boolean, nullable=False, default=False)

    # user = db.relationship("User", back_populates="roles")

    def __repr__(self):
        return "<{cls}(id={s.id}, name='{s.name}')>".format(s=self, cls=self.__class__.__name__)
