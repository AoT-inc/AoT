# coding=utf-8
"""Provide business logic for the unified tab system across all pages.

@phase active
@stability stable
@dependency Tab, Input, Output, Function, Widget, Trigger, Conditional, PID, CustomController
"""
import uuid
import logging
import os
from typing import List, Optional, Dict, Any
from sqlalchemy import and_
from flask import current_app

from aot.databases.models import Tab, Input, Output, Function, Widget, Trigger, Conditional, PID, CustomController, InputChannel, OutputChannel, FunctionChannel, Actions, ConditionalConditions, DeviceMeasurements, GeoShape
from aot.aot_flask.extensions import db
from aot.aot_flask.utils.utils_general import delete_entry_with_id
from aot.config import PATH_PYTHON_CODE_USER

logger = logging.getLogger(__name__)


class TabService:
    """Manage tab configuration and state for the web UI.

    @phase active
    @stability stable
    @dependency Tab, Input, Output, Function, Widget, Trigger, Conditional, PID, CustomController
    """

    @staticmethod
    def get_tabs_for_page(page_type: str) -> List[Tab]:
        """Retrieve all tabs for a specific page type, ordered by position."""
        try:
            tabs = Tab.query.filter_by(page_type=page_type).order_by(Tab.position).all()
            return tabs
        except Exception as e:
            logger.error(f"Error getting tabs for page {page_type}: {e}")
            return []

    @staticmethod
    def get_tab_by_id(tab_id: str) -> Optional[Tab]:
        """Retrieve a tab by its unique_id."""
        try:
            return Tab.query.filter_by(unique_id=tab_id).first()
        except Exception as e:
            logger.error(f"Error getting tab {tab_id}: {e}")
            return None

    @staticmethod
    def get_default_tab(page_type: str) -> Optional[Tab]:
        """Return the default tab (position 0) for a page type, creating it if absent."""
        try:
            # Try to get existing default tab
            default_tab = Tab.query.filter_by(page_type=page_type, position=0).first()

            if not default_tab:
                # Create default tab if it doesn't exist
                tab_names = {
                    'dashboard': 'Dashboard',
                    'input': 'Input',
                    'output': 'Output',
                    'function': 'Function'
                }

                default_tab = Tab()
                default_tab.unique_id = str(uuid.uuid4())
                default_tab.name = tab_names.get(page_type, page_type.capitalize())
                default_tab.page_type = page_type
                default_tab.position = 0
                default_tab.save()

                logger.info(f"Created default tab for {page_type}: {default_tab.name}")

            return default_tab
        except Exception as e:
            logger.error(f"Error getting/creating default tab for {page_type}: {e}")
            return None

    @staticmethod
    def get_next_tab_name(page_type: str) -> str:
        """Generate the next sequential tab name for a page type."""
        try:
            existing_tabs = Tab.query.filter_by(page_type=page_type).all()

            if not existing_tabs:
                # First tab
                return page_type.capitalize()

            # Extract numeric suffixes from existing tab names
            base_name = page_type.capitalize()
            numbers = []

            for tab in existing_tabs:
                if tab.name == base_name:
                    numbers.append(1)
                elif tab.name.startswith(base_name + ' '):
                    try:
                        num = int(tab.name[len(base_name) + 1:])
                        numbers.append(num)
                    except ValueError:
                        continue

            if not numbers:
                return f"{base_name} 2"

            next_num = max(numbers) + 1
            return f"{base_name} {next_num}"

        except Exception as e:
            logger.error(f"Error generating next tab name for {page_type}: {e}")
            return f"{page_type.capitalize()} New"

    @staticmethod
    def create_tab(page_type: str, name: Optional[str] = None) -> Optional[Tab]:
        """Create a new tab for a page type with auto-generated name if not provided."""
        try:
            # Get next position
            existing_tabs = Tab.query.filter_by(page_type=page_type).order_by(Tab.position).all()
            if existing_tabs:
                next_position = existing_tabs[-1].position + 1
            else:
                next_position = 0

            # Generate name if not provided
            if not name:
                name = TabService.get_next_tab_name(page_type)

            # Create tab
            new_tab = Tab()
            new_tab.unique_id = str(uuid.uuid4())
            new_tab.name = name
            new_tab.page_type = page_type
            new_tab.position = next_position
            
            # Use db.session directly for better error handling
            db.session.add(new_tab)
            db.session.commit()

            logger.info(f"Created new tab: {name} (page_type={page_type}, position={next_position})")
            return new_tab

        except Exception as e:
            logger.error(f"Error creating tab for {page_type}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            db.session.rollback()
            return None

    @staticmethod
    def rename_tab(tab_id: str, new_name: str) -> bool:
        """Rename a tab identified by unique_id."""
        try:
            tab = Tab.query.filter_by(unique_id=tab_id).first()
            if not tab:
                logger.error(f"Tab not found: {tab_id}")
                return False

            old_name = tab.name
            tab.name = new_name
            tab.save()

            logger.info(f"Renamed tab {tab_id}: {old_name} -> {new_name}")
            return True

        except Exception as e:
            logger.error(f"Error renaming tab {tab_id}: {e}")
            db.session.rollback()
            return False

    @staticmethod
    def duplicate_tab(source_tab_id: str) -> Optional[Tab]:
        """Duplicate a tab and all its entries with deactivated state."""
        try:
            source_tab = Tab.query.filter_by(unique_id=source_tab_id).first()
            if not source_tab:
                logger.error(f"Source tab not found: {source_tab_id}")
                return None

            # Create new tab with sequential name
            new_tab = TabService.create_tab(
                page_type=source_tab.page_type,
                name=None  # Auto-generate sequential name
            )

            if not new_tab:
                return None

            # Duplicate entries based on page type
            if source_tab.page_type == 'input':
                entries = Input.query.filter_by(tab_id=source_tab_id).all()
                for entry in entries:
                    old_unique_id = entry.unique_id
                    new_entry = Input()
                    # Copy all fields
                    for column in Input.__table__.columns:
                        if column.name not in ['id', 'unique_id', 'tab_id', 'is_activated']:
                            setattr(new_entry, column.name, getattr(entry, column.name))

                    new_unique_id = str(uuid.uuid4())
                    new_entry.unique_id = new_unique_id
                    new_entry.tab_id = new_tab.unique_id
                    new_entry.is_activated = False
                    new_entry.save()
                    
                    # Duplicate InputChannels
                    channels = InputChannel.query.filter_by(input_id=old_unique_id).all()
                    for channel in channels:
                        new_channel = InputChannel()
                        for column in InputChannel.__table__.columns:
                            if column.name not in ['id', 'unique_id', 'input_id']:
                                setattr(new_channel, column.name, getattr(channel, column.name))
                        new_channel.unique_id = str(uuid.uuid4())
                        new_channel.input_id = new_unique_id
                        new_channel.save()

                logger.info(f"Duplicated {len(entries)} Input entries to new tab {new_tab.unique_id}")

            elif source_tab.page_type == 'output':
                entries = Output.query.filter_by(tab_id=source_tab_id).all()
                for entry in entries:
                    old_unique_id = entry.unique_id
                    new_entry = Output()
                    # Copy all fields including map location data
                    for column in Output.__table__.columns:
                        if column.name not in ['id', 'unique_id', 'tab_id', 'is_activated']:
                            setattr(new_entry, column.name, getattr(entry, column.name))

                    new_unique_id = str(uuid.uuid4())
                    new_entry.unique_id = new_unique_id
                    new_entry.tab_id = new_tab.unique_id
                    new_entry.is_activated = False
                    new_entry.save()

                    # Duplicate OutputChannels
                    channels = OutputChannel.query.filter_by(output_id=old_unique_id).all()
                    for channel in channels:
                        new_channel = OutputChannel()
                        for column in OutputChannel.__table__.columns:
                            if column.name not in ['id', 'unique_id', 'output_id']:
                                setattr(new_channel, column.name, getattr(channel, column.name))
                        new_channel.unique_id = str(uuid.uuid4())
                        new_channel.output_id = new_unique_id
                        new_channel.save()

                logger.info(f"Duplicated {len(entries)} Output entries to new tab {new_tab.unique_id}")

            elif source_tab.page_type == 'function':
                # Duplicate Function entries
                function_entries = Function.query.filter_by(tab_id=source_tab_id).all()
                for entry in function_entries:
                    new_entry = Function()
                    for column in Function.__table__.columns:
                        if column.name not in ['id', 'unique_id', 'tab_id']:
                            setattr(new_entry, column.name, getattr(entry, column.name))
                    new_entry.unique_id = str(uuid.uuid4())
                    new_entry.tab_id = new_tab.unique_id
                    new_entry.save()
                logger.info(f"Duplicated {len(function_entries)} Function entries to new tab {new_tab.unique_id}")

                # Duplicate Trigger entries (includes trigger_sequence)
                trigger_entries = Trigger.query.filter_by(tab_id=source_tab_id).all()
                for entry in trigger_entries:
                    new_entry = Trigger()
                    for column in Trigger.__table__.columns:
                        if column.name not in ['id', 'unique_id', 'tab_id', 'is_activated']:
                            setattr(new_entry, column.name, getattr(entry, column.name))
                    new_entry.unique_id = str(uuid.uuid4())
                    new_entry.tab_id = new_tab.unique_id
                    new_entry.is_activated = False
                    new_entry.save()
                logger.info(f"Duplicated {len(trigger_entries)} Trigger entries (including sequences) to new tab {new_tab.unique_id}")

                # Duplicate Conditional entries
                conditional_entries = Conditional.query.filter_by(tab_id=source_tab_id).all()
                for entry in conditional_entries:
                    new_entry = Conditional()
                    for column in Conditional.__table__.columns:
                        if column.name not in ['id', 'unique_id', 'tab_id', 'is_activated']:
                            setattr(new_entry, column.name, getattr(entry, column.name))
                    new_entry.unique_id = str(uuid.uuid4())
                    new_entry.tab_id = new_tab.unique_id
                    new_entry.is_activated = False
                    new_entry.save()
                logger.info(f"Duplicated {len(conditional_entries)} Conditional entries to new tab {new_tab.unique_id}")

                # Duplicate PID entries
                pid_entries = PID.query.filter_by(tab_id=source_tab_id).all()
                for entry in pid_entries:
                    new_entry = PID()
                    for column in PID.__table__.columns:
                        if column.name not in ['id', 'unique_id', 'tab_id', 'is_activated']:
                            setattr(new_entry, column.name, getattr(entry, column.name))
                    new_entry.unique_id = str(uuid.uuid4())
                    new_entry.tab_id = new_tab.unique_id
                    new_entry.is_activated = False
                    # device_tz_listeners before_insert가 좌표 기반으로 timezone을 채움.
                    # 좌표가 없는 경우엔 Misc.timezone fallback을 직접 기록.
                    if not new_entry.timezone and not new_entry.latitude:
                        try:
                            from aot.databases.models import Misc
                            misc = Misc.query.first()
                            if misc and misc.timezone:
                                new_entry.timezone = misc.timezone
                        except Exception:
                            pass
                    new_entry.save()
                logger.info(f"Duplicated {len(pid_entries)} PID entries to new tab {new_tab.unique_id}")

                # Duplicate CustomController entries
                custom_entries = CustomController.query.filter_by(tab_id=source_tab_id).all()
                for entry in custom_entries:
                    old_unique_id = entry.unique_id
                    new_entry = CustomController()
                    for column in CustomController.__table__.columns:
                        if column.name not in ['id', 'unique_id', 'tab_id', 'is_activated']:
                            setattr(new_entry, column.name, getattr(entry, column.name))
                    new_unique_id = str(uuid.uuid4())
                    new_entry.unique_id = new_unique_id
                    new_entry.tab_id = new_tab.unique_id
                    new_entry.is_activated = False
                    new_entry.save()
                    
                    # Duplicate FunctionChannels
                    channels = FunctionChannel.query.filter_by(function_id=old_unique_id).all()
                    for channel in channels:
                        new_channel = FunctionChannel()
                        for column in FunctionChannel.__table__.columns:
                            if column.name not in ['id', 'unique_id', 'function_id']:
                                setattr(new_channel, column.name, getattr(channel, column.name))
                        new_channel.unique_id = str(uuid.uuid4())
                        new_channel.function_id = new_unique_id
                        new_channel.save()
                logger.info(f"Duplicated {len(custom_entries)} CustomController entries to new tab {new_tab.unique_id}")

            elif source_tab.page_type == 'dashboard':
                # For dashboard, widgets can be duplicated separately if needed
                # For now, just create empty tab
                logger.info(f"Created duplicate dashboard tab {new_tab.unique_id}")

            db.session.commit()
            return new_tab

        except Exception as e:
            logger.error(f"Error duplicating tab {source_tab_id}: {e}")
            db.session.rollback()
            return None

    @staticmethod
    def delete_tab(tab_id: str) -> Dict[str, Any]:
        """Delete a tab and its associated entries with fail-fast rollback on error."""
        try:
            tab = Tab.query.filter_by(unique_id=tab_id).first()
            if not tab:
                return {
                    'success': False,
                    'message': 'Tab not found',
                    'redirect_tab_id': None
                }

            # Check if this is the last tab
            all_tabs = Tab.query.filter_by(page_type=tab.page_type).all()
            if len(all_tabs) <= 1:
                return {
                    'success': False,
                    'message': 'Cannot delete the last tab on this page',
                    'redirect_tab_id': tab_id
                }

            # Find the next tab to redirect to
            redirect_tab = None
            for t in all_tabs:
                if t.unique_id != tab_id:
                    redirect_tab = t
                    break

            page_type = tab.page_type

            # ===== PRE-CLEANUP: 기존 고아 장치 정리 =====
            TabService._cleanup_orphans_for_page(page_type)

            # ===== FAIL-FAST DELETION =====
            # 자식 장치 삭제 실패 시 전체 롤백 (고아 방지)
            if page_type == 'input':
                entries = Input.query.filter_by(tab_id=tab_id).all()
                for entry in entries:
                    try:
                        TabService._delete_input_entry(entry.unique_id)
                    except Exception as e:
                        logger.error(f"Error deleting Input {entry.unique_id}: {e}")
                        raise  # Fail fast

            elif page_type == 'output':
                entries = Output.query.filter_by(tab_id=tab_id).all()
                for entry in entries:
                    try:
                        TabService._delete_output_entry(entry.unique_id)
                    except Exception as e:
                        logger.error(f"Error deleting Output {entry.unique_id}: {e}")
                        raise

            elif page_type == 'function':
                triggers = Trigger.query.filter_by(tab_id=tab_id).all()
                for entry in triggers:
                    try:
                        TabService._delete_trigger_entry(entry.unique_id)
                    except Exception as e:
                        logger.error(f"Error deleting Trigger {entry.unique_id}: {e}")
                        raise

                conditionals = Conditional.query.filter_by(tab_id=tab_id).all()
                for entry in conditionals:
                    try:
                        TabService._delete_conditional_entry(entry.unique_id)
                    except Exception as e:
                        logger.error(f"Error deleting Conditional {entry.unique_id}: {e}")
                        raise

                pids = PID.query.filter_by(tab_id=tab_id).all()
                for entry in pids:
                    try:
                        TabService._delete_pid_entry(entry.unique_id)
                    except Exception as e:
                        logger.error(f"Error deleting PID {entry.unique_id}: {e}")
                        raise

                custom_controllers = CustomController.query.filter_by(tab_id=tab_id).all()
                for entry in custom_controllers:
                    try:
                        TabService._delete_custom_controller_entry(entry.unique_id)
                    except Exception as e:
                        logger.error(f"Error deleting CustomController {entry.unique_id}: {e}")
                        raise

                functions = Function.query.filter_by(tab_id=tab_id).all()
                for entry in functions:
                    try:
                        TabService._delete_function_entry(entry.unique_id)
                    except Exception as e:
                        logger.error(f"Error deleting Function {entry.unique_id}: {e}")
                        raise

            elif page_type == 'dashboard':
                widgets = Widget.query.filter_by(tab_id=tab_id).all()
                for widget in widgets:
                    try:
                        widget.delete()
                    except Exception as e:
                        logger.error(f"Error deleting Widget {widget.unique_id}: {e}")
                        raise

            # 모든 자식 장치 삭제 성공 → 탭 삭제
            tab.delete()
            db.session.commit()

            logger.info(f"Deleted tab {tab_id} from {page_type}")

            # ===== POST-CLEANUP: 새로 발생한 고아 장치 정리 =====
            TabService._cleanup_orphans_for_page(page_type)

            return {
                'success': True,
                'message': 'Tab deleted successfully',
                'redirect_tab_id': redirect_tab.unique_id if redirect_tab else None
            }

        except Exception as e:
            logger.error(f"Tab deletion failed, rolled back: {e}")
            db.session.rollback()
            return {
                'success': False,
                'message': f'탭 삭제 실패: 장치 삭제 중 오류 발생. 문제 장치를 먼저 확인하세요.',
                'redirect_tab_id': tab_id
            }

    @staticmethod
    def reorder_tabs(tab_ids: List[str]) -> bool:
        """Reorder tabs by updating their position field to match the given list order."""
        try:
            offset = len(tab_ids) + 1000

            tabs = {tab.unique_id: tab for tab in Tab.query.filter(Tab.unique_id.in_(tab_ids)).all()}

            # Phase 1: shift to temporary positions to avoid unique constraint conflicts
            for index, tab_id in enumerate(tab_ids):
                tab = tabs.get(tab_id)
                if tab:
                    tab.position = offset + index
                    db.session.add(tab)
            db.session.flush()

            # Phase 2: set final positions
            for index, tab_id in enumerate(tab_ids):
                tab = tabs.get(tab_id)
                if tab:
                    tab.position = index
                    db.session.add(tab)

            db.session.commit()
            logger.info(f"Reordered {len(tab_ids)} tabs")
            return True

        except Exception as e:
            logger.error(f"Error reordering tabs: {e}")
            db.session.rollback()
            return False

    # ========== Private Helper Methods for Entry Deletion ==========
    
    @staticmethod
    def _delete_input_entry(input_id: str):
        """Delete an Input entry with proper cleanup (deactivation, channels, measurements, etc.)"""
        from aot.aot_flask.utils.utils_input import controller_activate_deactivate
        
        input_dev = Input.query.filter_by(unique_id=input_id).first()
        if not input_dev:
            return
        
        map_config_id = input_dev.map_config_id
        
        # Deactivate if active
        if input_dev.is_activated:
            messages = {"success": [], "info": [], "warning": [], "error": []}
            controller_activate_deactivate(messages, 'deactivate', 'Input', input_id)
        
        # Delete Actions
        actions = Actions.query.filter_by(function_id=input_id).all()
        for action in actions:
            delete_entry_with_id(Actions, action.unique_id, flash_message=False)
        
        # Delete DeviceMeasurements
        measurements = DeviceMeasurements.query.filter_by(device_id=input_id).all()
        for measurement in measurements:
            delete_entry_with_id(DeviceMeasurements, measurement.unique_id, flash_message=False)
        
        # Delete InputChannels
        channels = InputChannel.query.filter_by(input_id=input_id).all()
        for channel in channels:
            delete_entry_with_id(InputChannel, channel.unique_id, flash_message=False)
        
        # Delete Input
        delete_entry_with_id(Input, input_id, flash_message=False)

        # Delete map config ONLY if no remaining Input/Output shares it.
        # [P3] 원칙 1 — 지도는 장치의 소유물이 아니다. 장치를 지워도
        # 지도는 남는다. 지도 삭제는 geo/design 에서 명시적으로만.

        # Delete GeoShapes owned by this input (device-scoped, safe).
        GeoShape.query.filter_by(device_id=input_id).delete(synchronize_session=False)
        
        # Delete Python code file
        try:
            file_path = os.path.join(PATH_PYTHON_CODE_USER, f'input_python_code_{input_id}.py')
            if os.path.exists(file_path):
                os.remove(file_path)
        except Exception as e:
            logger.warning(f"Could not delete Python code file for Input {input_id}: {e}")
    
    @staticmethod
    def _delete_output_entry(output_id: str):
        """Delete an Output entry with proper cleanup (channels, measurements, etc.)"""
        from aot.aot_flask.utils.utils_output import manipulate_output
        
        output_dev = Output.query.filter_by(unique_id=output_id).first()
        if not output_dev:
            return
        
        map_config_id = output_dev.map_config_id
        
        # Delete DeviceMeasurements
        measurements = DeviceMeasurements.query.filter_by(device_id=output_id).all()
        for measurement in measurements:
            delete_entry_with_id(DeviceMeasurements, measurement.unique_id, flash_message=False)
        
        # Delete OutputChannels
        channels = OutputChannel.query.filter_by(output_id=output_id).all()
        for channel in channels:
            delete_entry_with_id(OutputChannel, channel.unique_id, flash_message=False)
        
        # Delete Output
        delete_entry_with_id(Output, output_id, flash_message=False)

        # Delete map config ONLY if no remaining Output (or Input) shares it.
        # Shared map_configs typically back zone/site/facility GeoShapes used
        # across pages; blindly deleting them wipes those shared shapes too.
        # [P3] 원칙 1 — 지도는 장치의 소유물이 아니다. 장치를 지워도
        # 지도는 남는다. 지도 삭제는 geo/design 에서 명시적으로만.

        # Delete GeoShapes owned by this output (device-scoped, safe).
        GeoShape.query.filter_by(device_id=output_id).delete(synchronize_session=False)
        
        # Notify daemon
        if not current_app.config.get('TESTING', False):
            try:
                manipulate_output('Delete', output_id)
            except Exception as e:
                logger.warning(f"Could not notify daemon about Output deletion {output_id}: {e}")
    
    @staticmethod
    def _delete_trigger_entry(trigger_id: str):
        """Delete a Trigger entry with proper cleanup (deactivation, actions, etc.)"""
        from aot.aot_flask.utils.utils_trigger import trigger_deactivate
        
        trigger = Trigger.query.filter_by(unique_id=trigger_id).first()
        if not trigger:
            return
        
        # Deactivate if active
        if trigger.is_activated:
            trigger_deactivate(trigger_id)
        
        # Delete Actions
        actions = Actions.query.filter_by(function_id=trigger_id).all()
        for action in actions:
            delete_entry_with_id(Actions, action.unique_id, flash_message=False)
        
        # Delete Trigger
        delete_entry_with_id(Trigger, trigger_id, flash_message=False)
    
    @staticmethod
    def _delete_conditional_entry(conditional_id: str):
        """Delete a Conditional entry with proper cleanup (deactivation, conditions, actions, etc.)"""
        from aot.aot_flask.utils.utils_conditional import conditional_deactivate
        
        conditional = Conditional.query.filter_by(unique_id=conditional_id).first()
        if not conditional:
            return
        
        # Deactivate if active
        if conditional.is_activated:
            conditional_deactivate(conditional_id)
        
        # Delete ConditionalConditions
        conditions = ConditionalConditions.query.filter_by(conditional_id=conditional_id).all()
        for condition in conditions:
            delete_entry_with_id(ConditionalConditions, condition.unique_id, flash_message=False)
        
        # Delete Actions
        actions = Actions.query.filter_by(function_id=conditional_id).all()
        for action in actions:
            delete_entry_with_id(Actions, action.unique_id, flash_message=False)
        
        # Delete Conditional
        delete_entry_with_id(Conditional, conditional_id, flash_message=False)
        
        # Delete Python code file
        try:
            file_path = os.path.join(PATH_PYTHON_CODE_USER, f'conditional_{conditional_id}.py')
            if os.path.exists(file_path):
                os.remove(file_path)
        except Exception as e:
            logger.warning(f"Could not delete Python code file for Conditional {conditional_id}: {e}")
    
    @staticmethod
    def _delete_pid_entry(pid_id: str):
        """Delete a PID entry with proper cleanup (deactivation, measurements, etc.)"""
        from aot.aot_flask.utils.utils_pid import pid_deactivate
        
        pid = PID.query.filter_by(unique_id=pid_id).first()
        if not pid:
            return
        
        # Deactivate if active
        if pid.is_activated:
            pid_deactivate(pid_id)
        
        # Delete DeviceMeasurements
        measurements = DeviceMeasurements.query.filter_by(device_id=pid_id).all()
        for measurement in measurements:
            delete_entry_with_id(DeviceMeasurements, measurement.unique_id, flash_message=False)
        
        # Delete PID
        delete_entry_with_id(PID, pid_id, flash_message=False)
    
    @staticmethod
    def _delete_custom_controller_entry(controller_id: str):
        """Delete a CustomController entry with proper cleanup (deactivation, channels, measurements, etc.)"""
        from aot.aot_flask.utils.utils_controller import controller_deactivate
        
        controller = CustomController.query.filter_by(unique_id=controller_id).first()
        if not controller:
            return
        
        map_config_id = controller.map_config_id
        
        # Deactivate if active
        if controller.is_activated:
            controller_deactivate(controller_id)
        
        # Delete DeviceMeasurements
        measurements = DeviceMeasurements.query.filter_by(device_id=controller_id).all()
        for measurement in measurements:
            delete_entry_with_id(DeviceMeasurements, measurement.unique_id, flash_message=False)
        
        # Delete FunctionChannels
        channels = FunctionChannel.query.filter_by(function_id=controller_id).all()
        for channel in channels:
            delete_entry_with_id(FunctionChannel, channel.unique_id, flash_message=False)
        
        # Delete CustomController
        delete_entry_with_id(CustomController, controller_id, flash_message=False)

        # Delete map config ONLY if no remaining device shares it.
        # [P3] 원칙 1 — 지도는 장치의 소유물이 아니다. 장치를 지워도
        # 지도는 남는다. 지도 삭제는 geo/design 에서 명시적으로만.
        
        # Delete Python code file
        try:
            file_path = os.path.join(PATH_PYTHON_CODE_USER, f'conditional_{controller_id}.py')
            if os.path.exists(file_path):
                os.remove(file_path)
        except Exception as e:
            logger.warning(f"Could not delete Python code file for CustomController {controller_id}: {e}")
    
    @staticmethod
    def _delete_function_entry(function_id: str):
        """Delete a Function entry with proper cleanup"""
        function = Function.query.filter_by(unique_id=function_id).first()
        if not function:
            return
        
        # Delete Function
        delete_entry_with_id(Function, function_id, flash_message=False)

    # ========== Orphan Detection & Cleanup Methods ==========

    @staticmethod
    def find_orphaned_entries() -> Dict[str, list]:
        """Find entries whose tab_id references a non-existent tab."""
        valid_tab_ids = {tab.unique_id for tab in Tab.query.all()}
        valid_tab_ids.add(None)  # NULL is valid (legacy entries)

        # NOTE: Widget is intentionally excluded. Widget.tab_id references the
        # Dashboard model's unique_id, not the Tab model. Treating widgets as
        # orphans by Tab membership reassigned them to a Tab id, breaking the
        # Dashboard->Widget link and making dashboards appear empty.
        TABLE_MAP = {
            'input': Input,
            'output': Output,
            'trigger': Trigger,
            'conditional': Conditional,
            'pid': PID,
            'custom_controller': CustomController,
            'function': Function,
        }

        orphans = {}
        for entry_type, Model in TABLE_MAP.items():
            orphan_ids = []
            for entry in Model.query.all():
                if hasattr(entry, 'tab_id') and entry.tab_id not in valid_tab_ids:
                    orphan_ids.append(entry.unique_id)
            if orphan_ids:
                orphans[entry_type] = orphan_ids

        if orphans:
            total = sum(len(ids) for ids in orphans.values())
            logger.warning(f"Found {total} orphaned entries: {orphans}")

        return orphans

    @staticmethod
    def cleanup_orphaned_entries(orphans: Dict[str, list]) -> int:
        """Reassign orphaned entries to their page's default tab to preserve data.

        Note: Does NOT commit. The caller's transaction owns the commit so that
        a rollback in the caller also rolls back the reassignments. Previously
        this committed independently, which leaked partial changes when the
        parent tab-delete failed.
        """
        # Widget excluded — see find_orphaned_entries note. Widget.tab_id
        # references Dashboard.unique_id, not Tab.unique_id.
        PAGE_MAP = {
            'input': 'input',
            'output': 'output',
            'trigger': 'function',
            'conditional': 'function',
            'pid': 'function',
            'custom_controller': 'function',
            'function': 'function',
        }
        MODEL_MAP = {
            'input': Input,
            'output': Output,
            'trigger': Trigger,
            'conditional': Conditional,
            'pid': PID,
            'custom_controller': CustomController,
            'function': Function,
        }

        reassigned = 0
        for entry_type, entry_ids in orphans.items():
            page_type = PAGE_MAP.get(entry_type)
            Model = MODEL_MAP.get(entry_type)
            if not page_type or not Model:
                continue

            default_tab = TabService.get_default_tab(page_type)
            if not default_tab:
                logger.error(f"Orphan cleanup: no default tab for page_type={page_type}")
                continue

            for entry_id in entry_ids:
                entry = Model.query.filter_by(unique_id=entry_id).first()
                if entry:
                    old_tab = entry.tab_id
                    entry.tab_id = default_tab.unique_id
                    entry.save()
                    reassigned += 1
                    logger.debug(
                        f"Reassigned {entry_type} {entry_id}: "
                        f"{old_tab} → {default_tab.unique_id}"
                    )

        if reassigned:
            logger.info(f"Orphan cleanup: reassigned {reassigned} entries to default tabs (pending commit)")

        return reassigned

    @staticmethod
    def _cleanup_orphans_for_page(page_type: str):
        """
        Silently scan and reassign orphan entries.
        Called automatically during tab create/delete operations.
        Failures are logged at DEBUG level to avoid noise.
        """
        try:
            orphans = TabService.find_orphaned_entries()
            if orphans:
                TabService.cleanup_orphaned_entries(orphans)
        except Exception as e:
            logger.error(f"Orphan cleanup failed: {e}", exc_info=True)

