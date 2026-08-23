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
    # Settings > Users 의 역할 탭 카드 순서 (users.position_y 와 같은 방식).
    position_y = db.Column(db.Integer, default=0)
    edit_settings = db.Column(db.Boolean, nullable=False, default=False)
    edit_controllers = db.Column(db.Boolean, nullable=False, default=False)
    # 작기 운영 — 구획 생성·수정·종료, 몫, 구역 총량, 구획 노트, 프로그램 **선택**
    # (프로그램 **편집**은 계속 edit_settings 다: 단계·목표는 제어로 흐른다).
    #
    # `edit_settings` 보다 **낮은 권한**으로 두는 것이 요지다. 예전에는 구획 관련
    # 쓰기가 전부 edit_settings 하나에 걸려, 작기 기록만 맡기려 해도 장치·시설·
    # 네트워크 설정까지 함께 열어야 했다 — 그래서 현장에서는 결국 모두에게
    # Editor 를 주게 되고 권한 체계가 있으나 쓰이지 않았다.
    #
    # **`edit_settings` 는 이것을 함의한다**(`user_has_permission` 이 처리).
    # 따로 체크하게 하면 기존 Editor 가 업그레이드 순간 구획을 못 쓰게 된다.
    edit_plots = db.Column(db.Boolean, nullable=False, default=False)
    edit_users = db.Column(db.Boolean, nullable=False, default=False)
    view_settings = db.Column(db.Boolean, nullable=False, default=False)
    view_camera = db.Column(db.Boolean, nullable=False, default=False)
    view_stats = db.Column(db.Boolean, nullable=False, default=False)
    view_logs = db.Column(db.Boolean, nullable=False, default=False)
    reset_password = db.Column(db.Boolean, nullable=False, default=False)

    # user = db.relationship("User", back_populates="roles")

    def __repr__(self):
        return "<{cls}(id={s.id}, name='{s.name}')>".format(s=self, cls=self.__class__.__name__)
