# coding=utf-8
#
#
#  Copyright (C) 2015-2020 Kyle T. Gabriel <mycodo@kylegabriel.com>
#
#  This file is part of Mycodo
#
#  Mycodo is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  Mycodo is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with Mycodo. If not, see <http://www.gnu.org/licenses/>.
#
#  Contact at kylegabriel.com
#

import subprocess

import sqlalchemy
from flask import current_app
from sqlalchemy import and_

from aot.config import ALEMBIC_VERSION
from aot.config import INSTALL_DIRECTORY
from aot.config import USER_ROLES
from aot.config_devices_units import UNIT_CONVERSIONS
from aot.aot_flask.extensions import db
from .alembic_version import AlembicVersion
from .api_key import APIKey
from .calendar_integration import UserCalendarConnection
from .calendar_integration import CalendarEventLink
from .camera import Camera
from .controller import CustomController
from .controller import FunctionChannel
from .dashboard import Dashboard
from .dashboard import Widget
from .device_member import DeviceMember
from .display_order import DisplayOrder
from .function import Actions
from .function import Conditional
from .function import ConditionalConditions
from .function import Function
from .function import FunctionRuntimeState
from .function_cumulative import FunctionCumulativeState
from .function import Trigger
from .input import Input
from .input import InputChannel
from .measurement import Conversion
from .measurement import DeviceMeasurements
from .measurement import Measurement
from .measurement import Unit
from .method import Method
from .method import MethodData
from .misc import EnergyUsage
from .misc import Misc
from .user import User
from .user_api_key import UserAPIKey
from .notes import NoteTags
from .notes import Notes
from .note_schedule_link import NoteScheduleLink
from .geo_containment_cache import GeoContainmentCache
from .notice import NoticePost
from .notice import NoticePoll
from .notice import NoticePollOption
from .notice import NoticePollVote
from .notice import NoticeReply
from .notice import NoticeAck
from .geo import GeoMap
from .geo import GeoSetting
from .geo import GeoShape
from .geo import GeoLayer
from .geo import GeoFacility
from .geo import GeoModelAsset
from .geo_binding import GeoBinding
from .geo_plot import GeoPlot
from .geo_plot_stage_event import GeoPlotStageEvent
from .geo_program import GeoProgram
# 옛 이름 — 한 릴리스 동안만 남긴다(p6_43 에서 관리 프로그램으로 넓혔다).
GeoCropProgram = GeoProgram
from .irrigation import IrrigationDesign
from .output import Output
from .output import OutputChannel
from .pid import PID
from .remote import Remote
from .remote_access_token import RemoteAccessToken
from .role import Role
from .smtp import SMTP
from .ai import AIAgent
from .ai import AIHistory
from .ai import AIEntry
from .ai import AIRoleConfig       # Layer 2 Hybrid Loader — SBS-002_V2
from .ai import AIActionRegistry   # Layer 2 Hybrid Loader — SBS-002_V2
from .ai_skeleton import AIAgentSkeleton  # [TASK_254_FIX] Restore missing registration
from .ai_task import AITask
from .scheduler import SchedulerJobMeta
from .scheduler import SchedulerAuditLog
from .ai_settings import AIGlobalSettings
from .ai_domain_glossary import AIDomainGlossary
from .ai_user_profile import AIUserProfile
from .ai_context_record import AIContextRecord
from .ai_context_source import AIContextSource, SourceType
from .ai_library_sync_log import AILibrarySyncLog
from .ai_knowledge_chunk import AIKnowledgeChunk
from .ai_facility_learning import AIFacilityLearning
from .ai_recommendation import AIRecommendation
from .ai_status_snapshot import AIStatusSnapshot
from .ai_feedback_event import AIFeedbackEvent
from .ai_onboarding_record import AIOnboardingRecord
from .mcp_server import MCPServer
from .mcp_server import AgentMCPAccess
from .ai_summary import AISystemSummary
from .ai_summary import AISystemSummaryFeedback
from .ai_error_feedback import AIErrorFeedback
# from .ai_memory import AIUserSemanticMemory   # Layer 3 — SBS-002_V2
# from .ai_memory import AIGlossaryOverride     # Layer 3 — SBS-002_V2
from .tab import Tab
from .orch_device import OrchDevice
from .orch_workflow import OrchWorkflow
from .orch_task import OrchTask
from .ekg import HumanNote, DaemonEvent, PatternCluster, EdgeRecord  # Phase 5 EKG
from .ext_smartfarm_setpoints import ExtSmartfarmSetpoints  # Phase 2a EXT-KR-01
from .ext_nongsaro_guides import ExtNongsaroGuides          # Phase 2b EXT-KR-02
from .ext_pest_alerts import ExtPestAlerts              # Phase 2b EXT-KR-03
from .tier_adaptive_storage import TierThreshold           # Adaptive Document Storage
from .tier_adaptive_storage import TierDecision
from .tier_adaptive_storage import DocumentAccessLog
from .tier_adaptive_storage import AdaptiveStorageSettings
from .cold_storage import ColdDocuments                     # Tier 3 (Cold/Archive)
from .cold_storage import ArchiveIndex
from .cold_storage import ArchiveAuditLog
from .mcp_audit import MCPAuditLog, MCPConfirmation
from .audit import AuditLog
from .ai_advice import AIAdvice
from .geo_facility_setpoint import GeoFacilitySetpoint



def alembic_upgrade_db(app):
    """Upgrade the SQLite database schema to the current ALEMBIC_VERSION using Alembic.

    Checks the alembic_version row; if absent, empty, or mismatched, runs the
    upgrade script. Idempotent — safe to call on every startup.

    Fresh installs and existing installs take deliberately different paths (see
    the two branches below) — collapsing them caused the 2026-08-18 bug where
    both a brand-new database AND an existing one being upgraded across a
    migration that adds a table got stuck silently two revisions behind head
    (`db.create_all()` had already created the table from the current models,
    so alembic's own `CREATE TABLE` for that same table failed with "already
    exists" and the version was never bumped — indistinguishable from success
    to the caller, since the subprocess failure is only logged, not raised).

    @phase active
    """

    def run_alembic(subcommand, version):
        """Run `aot/scripts/upgrade_commands.sh <subcommand> <version>`."""
        command = '/bin/bash {path}/aot/scripts/upgrade_commands.sh {sub} {version}'.format(
            path=INSTALL_DIRECTORY, sub=subcommand, version=version)
        try:
            upgrade = subprocess.Popen(
                command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
            stdout, stderr = upgrade.communicate()
            if upgrade.returncode == 0:
                app.logger.info(f"Alembic {subcommand} successful.")
            else:
                app.logger.error(f"Alembic {subcommand} failed with return code {upgrade.returncode}")
                app.logger.error(f"STDOUT: {stdout.decode()}")
                app.logger.error(f"STDERR: {stderr.decode()}")
        except Exception as e:
            app.logger.error(f"Exception during alembic {subcommand}: {e}")

    def upgrade_alembic():
        """Run alembic database upgrade (existing database, no DDL from create_all() involved)."""
        app.logger.info(f"Database version mismatch or missing. Running alembic upgrade to {ALEMBIC_VERSION}...")
        # 목표를 ALEMBIC_VERSION 으로 명시한다. 'head' 를 쓰면 폐기된 구 계보의
        # p5_52 가 두 번째 head 로 남아 있어 "Multiple head revisions" 로 실패한다
        # (26.06.0 재베이스라인에서 p6_00.down_revision=None 으로 계보를 분리한 결과).
        run_alembic('update-alembic', ALEMBIC_VERSION)

    with app.app_context():
        try:
            alembic = AlembicVersion.query.first()
        except sqlalchemy.exc.OperationalError as e:
            if 'no such table' not in str(e).lower():
                raise
            # 완전 신규 설치 — alembic_version 테이블조차 없다. 실측(2026-08-18)
            # 으로 확인됨: `p6_00_rebaseline` 는 스키마를 처음부터 다 만들지 않고
            # 그 이전부터 있던 베이스 테이블(예: misc·roles)이 이미 있다고 가정한
            # 채 그 위에 증분 변경(ALTER 등)만 쌓는다. 그래서 여기서는 db.create_all()
            # 로 현재 모델 기준 최종(head) 스키마를 한 번에 만들고, alembic 은
            # DDL 을 다시 실행하지 않고 그 상태를 head 로 **스탬프만** 한다 —
            # 'upgrade' 로 리비전을 처음부터 재생하면 create_all() 이 이미 만든
            # 테이블(특히 최근 추가된 신규 테이블)과 부딪혀 "already exists" 로
            # 실패하고 버전은 갱신되지 않는다. 이 경로로 만들어진 테이블 중 일부는
            # SQLAlchemy 기본 인덱스 명명 규칙을 쓰므로 alembic 마이그레이션이
            # 명시한 인덱스 이름과 다를 수 있다(기능에는 영향 없음, 인덱스를 이름
            # 으로 참조하는 향후 마이그레이션이 있다면 유의).
            db.session.rollback()
            app.logger.info("No alembic_version table found (fresh install). Creating schema from models and stamping to head...")
            db.create_all()
            run_alembic('stamp-alembic', ALEMBIC_VERSION)
            return

        if alembic:  # If alembic_version table has an entry
            if alembic.version_num == '':
                app.logger.info("Alembic version entry empty. Deleting and upgrading...")
                alembic.delete()
                upgrade_alembic()
            elif alembic.version_num != ALEMBIC_VERSION:  # Not current version
                app.logger.info(f"Database version ({alembic.version_num}) does not match expected ({ALEMBIC_VERSION}). upgrading...")
                upgrade_alembic()
            else:
                app.logger.info(f"Database version ({alembic.version_num}) is up to date.")
        else:
            app.logger.info("No alembic version found in database. Upgrading...")
            upgrade_alembic()


def insert_or_ignore(an_object, a_session):
    """Insert an object, rolling back on IntegrityError (duplicate key) without raising.

    Mimics SQLite's INSERT OR IGNORE semantics. Logs debug messages for duplicate
    violations and other errors. Use for idempotent seeding of unique rows.

    @phase active
    """

    a_session.add(an_object)

    try:
        a_session.commit()
    except sqlalchemy.exc.IntegrityError as e:
        # Ignore duplicate primary key
        # This is the same as the 'INSERT OR IGNORE'
        current_app.logger.debug("An error occurred when committing changes to a database: "
                                 "{err}".format(err=e))
        a_session.rollback()
    except Exception as e:
        current_app.logger.error("Exception in 'insert_or_ignore'' call.  Error: '{err}'".format(err=e))
        # Something else went wrong!!
        a_session.rollback()
        raise


def init_db():
    """Create all tables defined by registered SQLAlchemy models if they do not exist.

    @phase active
    """
    db.create_all()


def drop_db():
    """Drop all tables from the database. Use with caution — this is destructive.

    @phase active
    """
    db.drop_all()


def populate_db():
    """Insert default rows into Role, AlembicVersion, DisplayOrder, Misc, and other tables.

    Creates initial system configuration records if they are not already present.
    Idempotent for known roles (updates existing records). Must be called after
    init_db().

    @phase active
    """
    known_roles = {r.name: r for r in Role.query.all()}
    for role_cfg in USER_ROLES:
        if role_cfg['name'] in known_roles:
            # Update Previous Roles
            previous_record = known_roles[role_cfg['name']]
            for k, v in role_cfg.items():
                if k == 'id':  # skip the primary key
                    continue
                setattr(previous_record, k, v)  # set values from app config
                previous_record.save()
        else:
            # Create new roles
            Role(**role_cfg).save()

    if not AlembicVersion.query.count():
        AlembicVersion().save()
    if not DisplayOrder.query.count():
        DisplayOrder(id=1).save()
    if not Misc.query.count():
        Misc(id=1).save()
    if not Misc.query.count():
        Misc(id=1).save()
    if not AIGlobalSettings.query.count():
        AIGlobalSettings(id=1).save()

    if not GeoSetting.query.count():
        GeoSetting(id=1).save()
    if not SMTP.query.count():
        SMTP(id=1).save()
    if not Dashboard.query.count():
        Dashboard(id=1, name='Default').save()
    if not APIKey.query.count():
        # Optional: Add any default API keys if needed
        pass
    
    if not IrrigationDesign.query.count():
        # Optional: Add default design if needed
        pass

    # Populate conversion tables
    for (conv_from, conv_to, equation) in UNIT_CONVERSIONS:
        if not Conversion.query.filter(
                and_(Conversion.convert_unit_from == conv_from,
                     Conversion.convert_unit_to == conv_to)).count():
            new_conv = Conversion()
            new_conv.protected = True
            new_conv.convert_unit_from = conv_from
            new_conv.convert_unit_to = conv_to
            new_conv.equation = equation
            new_conv.save()
