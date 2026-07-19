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
from .camera import Camera
from .controller import CustomController
from .controller import FunctionChannel
from .dashboard import Dashboard
from .dashboard import Widget
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
from .notes import NoteTags
from .notes import Notes
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
from .irrigation import IrrigationDesign
from .output import Output
from .output import OutputChannel
from .pid import PID
from .remote import Remote
from .role import Role
from .smtp import SMTP
from .ai import AIAgent
from .ai import AIHistory
from .ai import AIEntry
from .ai import AIRoleConfig       # Layer 2 Hybrid Loader — SBS-002_V2
from .ai import AIActionRegistry   # Layer 2 Hybrid Loader — SBS-002_V2
from .ai_skeleton import AIAgentSkeleton  # [TASK_254_FIX] Restore missing registration
from .ai_task import AITask
from .ai_task_history import AITaskHistory
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
from .mcp_audit import MCPAuditLog, MCPConfirmation
from .geo_facility_setpoint import GeoFacilitySetpoint



def alembic_upgrade_db(app):
    """Upgrade the SQLite database schema to the current ALEMBIC_VERSION using Alembic.

    Checks the alembic_version row; if absent, empty, or mismatched, runs the
    upgrade script. Idempotent — safe to call on every startup.

    @phase active
    """

    def upgrade_alembic():
        """Run alembic database upgrade."""
        app.logger.info("Database version mismatch or missing. Running alembic upgrade head...")
        command = '/bin/bash {path}/aot/scripts/upgrade_commands.sh update-alembic'.format(path=INSTALL_DIRECTORY)
        try:
            upgrade = subprocess.Popen(
                command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
            stdout, stderr = upgrade.communicate()
            if upgrade.returncode == 0:
                app.logger.info("Alembic upgrade successful.")
            else:
                app.logger.error(f"Alembic upgrade failed with return code {upgrade.returncode}")
                app.logger.error(f"STDOUT: {stdout.decode()}")
                app.logger.error(f"STDERR: {stderr.decode()}")
        except Exception as e:
            app.logger.error(f"Exception during alembic upgrade: {e}")

    with app.app_context():
        alembic = AlembicVersion.query.first()

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
