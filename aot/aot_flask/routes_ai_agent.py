# coding=utf-8
import json
import logging
import flask_login
from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required
from flask_babel import gettext
from aot.databases.models import db, AIAgent, AIHistory, AIEntry, Misc, AITask, AIGlobalSettings, APIKey, MCPServer, GeoFacility
from aot.ai.services.ai_agent_service import AIAgentService
from aot.ai.services.mcp_bridge_service import MCPBridgeService
from aot.aot_flask.utils.utils_general import user_has_permission

logger = logging.getLogger(__name__)
blueprint = Blueprint('routes_ai_agent', __name__)


# ---------------------------------------------------------------------------
# Page routes
# ---------------------------------------------------------------------------

@blueprint.route('/ai', methods=['GET'])
@login_required
def page_ai_dashboard():
    """AI Portal - accessible to all logged-in users."""
    from aot.databases.models import AIFacilityLearning, AIUserProfile

    entries_count = AIEntry.query.filter_by(is_activated=True).count()
    agents_count = AIAgent.query.filter_by(is_activated=True).count()
    recent_history = AIHistory.query.order_by(AIHistory.timestamp.desc()).limit(5).all()

    # Resolve facility_id
    facility_id = request.args.get('facility_id', None)
    if not facility_id and flask_login.current_user.is_authenticated:
        misc = Misc.query.first()
        if misc and hasattr(misc, 'default_facility_id'):
            facility_id = misc.default_facility_id

    # 016: Fetch AIUserProfile for onboarding mode detection
    user_profile = None
    if flask_login.current_user.is_authenticated:
        user_profile = AIUserProfile.query.filter_by(
            user_id=flask_login.current_user.id
        ).first()

    # Re-invoke flag: show Getting-to-Know flow even if already onboarded
    reinvoke = request.args.get('reinvoke', '0') == '1'

    # Facility-level learning record (used by 013/014 journey view)
    onboarding_profile = None
    if facility_id:
        onboarding_profile = AIFacilityLearning.query.filter_by(facility_id=facility_id).first()

    return render_template('pages/ai/ai.html',
                           entries_count=entries_count,
                           agents_count=agents_count,
                           recent_history=recent_history,
                           active_page='ai_dashboard',
                           now_timestamp=12345,
                           settings=Misc.query.first(),
                           ai_settings=AIGlobalSettings.query.first(),
                           facility_id=facility_id or '',
                           user_profile=user_profile,
                           reinvoke=reinvoke,
                           onboarding_profile=onboarding_profile)


@blueprint.route('/ai/agent', methods=['GET'])
@login_required
def page_ai_agent():
    """AI Agent page - Entry registration & Agent management. Editor+ only."""
    if not user_has_permission('edit_controllers'):
        return redirect(url_for('routes_ai_agent.page_ai_dashboard'))
    # Cleanup orphaned AIEntry records (no linked agents) before loading
    all_entries = AIEntry.query.order_by(AIEntry.created_at.desc()).all()
    entries = []
    for e in all_entries:
        has_agent = AIAgent.query.filter_by(entry_id=e.unique_id).first()
        if has_agent:
            entries.append(e)
        else:
            logger.info(f"Auto-deleting orphaned AIEntry '{e.name}' (no linked agents).")
            db.session.delete(e)
    if len(entries) != len(all_entries):
        db.session.commit()

    # v11: Serialize entries for frontend JS (JSON safe)
    serialized_entries = []
    for e in entries:
        serialized_entries.append({
            'unique_id': e.unique_id,
            'name': e.name,
            'model_type': e.model_type,
            'model_name': e.model_name
        })

    agents = AIAgent.query.order_by(AIAgent.position_y).all()
    engine_presets = AIAgentService.get_all_engine_presets()
    role_presets = AIAgentService.get_role_presets()
    api_keys = APIKey.query.all()
    mcp_servers = MCPServer.query.all()
    # Multi-site default: which GeoFacility _resolve_facility_id() falls back
    # to everywhere else (AI Library, conversational AI, portal). Previously
    # editable nowhere in the UI. See
    # .local/plans/phase6_knowledge_digest_design.md (multi-site addendum).
    facilities = GeoFacility.query.order_by(GeoFacility.name).all()

    return render_template('pages/ai/ai_agent.html',
                           entries=entries,
                           serialized_entries=serialized_entries,
                           agents=agents,
                           engine_presets=engine_presets,
                           role_presets=role_presets, # Added
                           api_keys=api_keys,
                           mcp_servers=mcp_servers,
                           facilities=facilities,
                           active_page='ai_agent',
                           settings=Misc.query.first(),
                           # Bugfix: template reads ai_settings.* (Models/Context tabs) but
                           # this route never passed it, so those fields silently always
                           # showed the hardcoded placeholder default, never the real value.
                           ai_settings=AIGlobalSettings.query.first())


@blueprint.route('/ai/manage', methods=['GET'])
@login_required
def page_ai_manage():
    """AI Manager - Integrated Conversation & Error Dashboard."""
    if not user_has_permission('edit_controllers'):
        return redirect(url_for('routes_ai_agent.page_ai_dashboard'))
        
    active_tab = request.args.get('tab', 'manage')
    history = AIHistory.query.order_by(AIHistory.timestamp.desc()).limit(100).all()
    agents = AIAgent.query.order_by(AIAgent.created_at.desc()).all()
    
    return render_template('pages/ai/ai_manage.html',
                           history=history,
                           active_tab=active_tab,
                           active_page='ai_manage')


@blueprint.route('/ai/scheduler', methods=['GET'])
@login_required
def page_ai_scheduler():
    """AI Scheduler - Collaborative Gantt UI & Task settings. (Legacy - Redirect to Geo Design)"""
    return redirect(url_for('routes_scheduler.page_scheduler'), code=301)


@blueprint.route('/ai/errors', methods=['GET'])
@login_required
def page_ai_errors():
    """AI Error Dashboard - Redirect to Integrated Manager."""
    if not user_has_permission('edit_controllers'):
        return redirect(url_for('routes_ai_agent.page_ai_dashboard'))
    return redirect(url_for('routes_ai_agent.page_ai_manage', tab='errors'), code=301)


@blueprint.route('/ai/save_agent_layout', methods=['POST'])
@login_required
def save_agent_layout():
    """Save positions of AI Agents."""
    if not user_has_permission('edit_controllers'):
        return jsonify({'status': 'error', 'message': 'Permission denied'}), 403
    data = request.get_json()
    for item in data:
        if 'id' in item and 'y' in item:
            agent = AIAgent.query.filter_by(unique_id=item['id']).first()
            if agent:
                agent.position_x = item.get('x', 0)
                agent.position_y = item['y']
                agent.width = item.get('w', 24)
                agent.height = item.get('h', 1)
    db.session.commit()
    return jsonify({'status': 'success'})


@blueprint.route('/ai/save_service_layout', methods=['POST'])
@login_required
def save_service_layout():
    """Save positions of AI Services (Entries)."""
    if not user_has_permission('edit_controllers'):
        return jsonify({'status': 'error', 'message': 'Permission denied'}), 403
    data = request.get_json()
    for item in data:
        if 'id' in item and 'y' in item:
            entry = AIEntry.query.filter_by(unique_id=item['id']).first()
            if entry:
                entry.position_x = item.get('x', 0)
                entry.position_y = item['y']
                entry.width = item.get('w', 24)
                entry.height = item.get('h', 1)
    db.session.commit()
    return jsonify({'status': 'success'})


# ---------------------------------------------------------------------------
# Entry CRUD
# ---------------------------------------------------------------------------

@blueprint.route('/ai/entry/add', methods=['POST'])
@login_required
def ai_entry_add():
    """Add a new AI Service Entry."""
    if not user_has_permission('edit_controllers'):
        return redirect(url_for('routes_ai_agent.page_ai_dashboard'))
    name = request.form.get('name')
    model_type = request.form.get('model_type', 'gemini')
    model_name = request.form.get('model_name', 'gemini-2.5-flash')
    api_endpoint = request.form.get('api_endpoint', '')
    auth_type = request.form.get('auth_type', 'api_key')
    auth_id = request.form.get('auth_id', '')
    api_key = request.form.get('api_key', '')
    
    if not name:
        flash(gettext("Service name is required."), "error")
        return redirect(url_for('routes_ai_agent.page_ai_agent'))

    new_entry = AIEntry(
        name=name,
        model_type=model_type,
        model_name=model_name,
        api_endpoint=api_endpoint,
        auth_type=auth_type,
        auth_id=auth_id,
        api_key=api_key
    )
    try:
        new_entry.save()
        flash(gettext("AI Service '%(name)s' registered.", name=name), "success")

        # [Auto-Save to API Key Manager]
        if api_key:
            from aot.aot_flask.utils import utils_settings
            utils_settings.auto_register_api_key(
                value=api_key,
                name=f"AI Service: {name}",
                provider=model_type,
                tag="AI_SERVICE"
            )

        # v3.1 §13-2-A: "register one key → all roles work". Auto-bind any
        # pipeline role that lacks a working (active + keyed) agent to this new
        # connection — gap-fill only, so it never clobbers a role the user
        # already configured. Wrapped so it can never break registration.
        if api_key:
            try:
                from aot.ai.services.role_binder import autobind_all_roles
                bound = autobind_all_roles(new_entry.unique_id, fill_missing_only=True)
                if bound:
                    flash(gettext("Auto-bound roles: %(roles)s", roles=", ".join(sorted(bound.keys()))), "success")
            except Exception as _ab_err:
                logger.warning(f"[ai_entry_add] autobind skipped: {_ab_err}")
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to register AI service: {e}")
        flash(gettext("Error registering service: %(err)s", err=str(e)), "error")
        
    return redirect(url_for('routes_ai_agent.page_ai_agent'))


@blueprint.route('/ai/entry/mod/<entry_id>', methods=['POST'])
@login_required
def ai_entry_mod(entry_id):
    """Modify an AI Service Entry."""
    if not user_has_permission('edit_controllers'):
        return redirect(url_for('routes_ai_agent.page_ai_dashboard'))
    entry = AIEntry.query.filter_by(unique_id=entry_id).first()
    if not entry:
        flash(gettext("Service entry not found."), "error")
        return redirect(url_for('routes_ai_agent.page_ai_agent'))

    entry.name = request.form.get('name', entry.name)
    entry.model_name = request.form.get('model_name', entry.model_name)
    entry.api_endpoint = request.form.get('api_endpoint', entry.api_endpoint)
    new_key = request.form.get('api_key', '')
    
    if new_key:
        entry.api_key = new_key
    try:
        db.session.commit()
        flash(gettext("Service '%(name)s' updated.", name=entry.name), "success")
        
        # [Auto-Save to API Key Manager]
        if new_key:
            from aot.aot_flask.utils import utils_settings
            utils_settings.auto_register_api_key(
                value=new_key,
                name=f"AI Service: {entry.name}",
                provider=entry.model_type,
                tag="AI_SERVICE"
            )
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to update AI service {entry_id}: {e}")
        flash(gettext("Error updating service: %(err)s", err=str(e)), "error")

    return redirect(url_for('routes_ai_agent.page_ai_agent'))


@blueprint.route('/ai/entry/delete/<entry_id>', methods=['POST'])
@login_required
def ai_entry_delete(entry_id):
    """Delete an AI Service Entry."""
    if not user_has_permission('edit_controllers'):
        return redirect(url_for('routes_ai_agent.page_ai_dashboard'))
    entry = AIEntry.query.filter_by(unique_id=entry_id).first()
    if entry:
        entry.delete()
        flash(gettext("Service entry deleted."), "success")
    return redirect(url_for('routes_ai_agent.page_ai_agent'))


@blueprint.route('/ai/agent/add_direct', methods=['POST'])
@login_required
def ai_agent_add_direct():
    """Directly add a new AI Agent with default settings (v12).
    Supports open_modal=true to return only agent_id for modal-first flow.
    Supports pipeline_role to pre-set role (from role-first add row).
    """
    if not user_has_permission('edit_controllers'):
        return jsonify({"status": "error", "message": "Permission denied"}), 403

    raw_val = request.form.get('source_select')
    if not raw_val or ':' not in raw_val:
        return jsonify({"status": "error", "message": "Invalid source selected"}), 400

    # Role-first: optional pipeline_role from add-row dropdown
    requested_role = request.form.get('pipeline_role')
    # Modal-first: if true, skip grid HTML in response
    open_modal = request.form.get('open_modal', 'false').lower() == 'true'

    mode, value = raw_val.split(':', 1)
    entry_id = None

    # Default engine fallback
    all_presets = AIAgentService.get_all_engine_presets()
    default_engine_key = next(iter(all_presets.keys())) if all_presets else 'gemini'
    model_type = default_engine_key
    model_name = ''

    if mode == 'entry':
        # Link to existing service
        entry = AIEntry.query.filter_by(unique_id=value).first()
        if not entry:
            return jsonify({"status": "error", "message": "Service entry not found"}), 404
        entry_id = entry.unique_id
        model_type = entry.model_type
        model_name = entry.model_name

        preset = AIAgentService.get_engine_info(model_type)
        engine_name = entry.name
    else:
        # Create new service from implementation automatically
        model_type = value
        preset = AIAgentService.get_engine_info(model_type)
        engine_name = preset.get('ai_name', model_type)

        # Default model from preset
        models = preset.get('models', [])
        if models:
            first_model = models[0]
            model_name = first_model.get('value') if isinstance(first_model, dict) else first_model

        # Auto-create service
        entry_base_name = preset.get('ai_manufacturer', 'AoT')
        entry_name = entry_base_name
        new_entry = AIEntry(
            name=entry_name,
            model_type=model_type,
            model_name=model_name,
            api_endpoint=preset.get('default_endpoint', ''),
            auth_type=preset.get('auth_methods', ['api_key'])[0],
            api_key='',  # Empty by default
            is_activated=False
        )
        new_entry.save()
        entry_id = new_entry.unique_id

    # Create Agent
    agent_name = engine_name

    # Determine pipeline_role: requested_role takes priority, else auto-detect
    pipeline_role = requested_role
    if not pipeline_role:
        ENGINE_ROLE_MAP = {
            'ai_router': 'router',
            'ai_planner': 'planner',
            'ai_synthesizer': 'synthesizer',
        }
        pipeline_role = ENGINE_ROLE_MAP.get(model_type, 'worker')

    # Role-first: merge role preset fields (model_tier, tool_access, system_prompt, specialty)
    role_preset = AIAgentService.get_role_presets().get(pipeline_role, {})
    initial_prompt = role_preset.get('system_prompt') or preset.get('system_prompt') or 'You are a helpful assistant.'
    initial_specialty = role_preset.get('specialty') or preset.get('specialty', 'general')
    initial_model_tier = role_preset.get('model_tier', 'standard')
    initial_tool_access = role_preset.get('tool_access', 'auto')

    # temperature and max_tokens from role preset DB fields
    initial_temperature = role_preset.get('temperature', 0.7)
    initial_max_tokens = role_preset.get('max_tokens', 2048)

    # model from role preset DB fields (overrides entry model_name if set)
    initial_model = role_preset.get('model_value', '')

    new_agent = AIAgent(
        name=agent_name,
        entry_id=entry_id,
        role='worker',
        specialty=initial_specialty,
        system_prompt=initial_prompt,
        temperature=initial_temperature,
        max_tokens=initial_max_tokens,
        pipeline_role=pipeline_role,
        model_tier=initial_model_tier,
        model_name=initial_model,
        tool_access=initial_tool_access,
        is_activated=False
    )
    new_agent.save()

    # v13→v6: Auto-create MCPServer with independent UUID and M:N mapping
    if preset.get('is_mcp'):
        from aot.databases.models import MCPServer
        from aot.databases.models.mcp_server import AgentMCPAccess
        new_mcp = MCPServer(
            name=f"{agent_name} Server",
            command=preset.get('default_command', ''),
            scope=preset.get('mcp_scope', 'general'),
            is_activated=True
        )
        new_mcp.save()

        access = AgentMCPAccess(
            agent_unique_id=new_agent.unique_id,
            mcp_unique_id=new_mcp.unique_id
        )
        db.session.add(access)
        db.session.commit()

        # v6: Set agent defaults for MCP-type
        # Preserve model_tier from role preset; override role and tool_access
        new_agent.model_tier = role_preset.get('model_tier', 'standard')
        new_agent.pipeline_role = 'executor'
        new_agent.tool_access = 'assigned'
        new_agent.save()

        logger.info(f"Auto-created MCPServer '{new_mcp.unique_id}' with M:N mapping for agent: {agent_name}")

    # Always return grid widget HTML
    entries = AIEntry.query.all()
    serialized_entries = [{'unique_id': e.unique_id, 'name': e.name, 'model_type': e.model_type} for e in entries]

    template = 'pages/ai/ai_agent_entry_mcp.html' if model_type.startswith('mcp_') else 'pages/ai/ai_agent_entry.html'
    html = render_template(template, agent=new_agent, entries=entries, serialized_entries=serialized_entries, model_type=model_type)

    return jsonify({
        "status": "success",
        "agent_id": new_agent.unique_id,
        "html": html,
        "message": f"Agent '{agent_name}' added."
    })


# ---------------------------------------------------------------------------
# Agent CRUD
# ---------------------------------------------------------------------------

@blueprint.route('/ai/agent/options/<unique_id>', methods=['GET'])
@login_required
def ai_agent_options(unique_id):
    """
    Renders the specialized option form for an agent based on its category.
    Matches the 'Function' system's dynamic option loading pattern.
    """
    agent = AIAgent.query.filter_by(unique_id=unique_id).first_or_404()
    
    # Get model type to determine category
    model_type = agent.entry.model_type if agent.entry else 'gemini' # Fallback
    engine_info = AIAgentService.get_engine_info(model_type)
    
    # Determine template based on category (from AIAgentService fallback or metadata)
    category = engine_info.get('ai_category', 'mcp' if engine_info.get('is_mcp') else 'llm')
    
    # [v6] Dynamically populate 'choices' for Reasoning Brain if applicable
    if 'custom_options' in engine_info:
        no_llms = False
        has_reasoning_opt = False
        
        for opt in engine_info.get('custom_options', []):
            if opt.get('id') == 'reasoning_entry_id':
                has_reasoning_opt = True
                # Filter and cleanup orphaned entries
                all_llm_entries = AIEntry.query.filter(
                    ~AIEntry.model_type.startswith('mcp_')
                ).all()
                llm_entries = []
                for e in all_llm_entries:
                    has_agent = AIAgent.query.filter_by(entry_id=e.unique_id).first()
                    if has_agent:
                        llm_entries.append(e)
                    else:
                        # Orphan - delete immediately to keep dropdown clean
                        logger.info(f"Auto-deleting orphaned AIEntry '{e.name}' from options loader.")
                        db.session.delete(e)
                
                if len(llm_entries) != len(all_llm_entries):
                    db.session.commit()

                opt['choices'] = [{'value': '', 'label': '-- Default System Engine --'}]
                for e in llm_entries:
                    opt['choices'].append({'value': e.unique_id, 'label': f"{e.name} ({e.model_name})"})
                
                # If no LLM entries exist, hide the option
                no_llms = len(llm_entries) == 0
                if no_llms:
                    opt['hidden'] = True
                
        # Also hide 'llm_model' if 'reasoning_entry_id' is hidden or essentially unused
        if has_reasoning_opt and no_llms:
            for opt in engine_info.get('custom_options', []):
                if opt.get('id') == 'llm_model':
                    opt['hidden'] = True
    
    # Parse custom options JSON
    custom_options = {}
    if agent.custom_options_json:
        try:
            custom_options = json.loads(agent.custom_options_json)
        except Exception as e:
            logger.warning(f"Failed to parse custom_options_json for agent {unique_id}: {str(e)}")
            
    template = f"pages/ai/options/options_{category}.html"
    
    try:
        api_keys = APIKey.query.all()
        html = render_template(template, agent=agent, engine_info=engine_info, custom_options=custom_options, api_keys=api_keys)
        service_name = engine_info.get('ai_name', '')
        return jsonify({"status": "success", "html": html, "service_name": service_name})
    except Exception as e:
        logger.error(f"Error rendering AI options template {template}: {str(e)}")
        return jsonify({"status": "error", "message": f"Template error: {category}"}), 500


@blueprint.route('/ai/agent/add', methods=['POST'])
@login_required
def ai_agent_add():
    """Add a new AI Agent (and optionally a new AI Service Entry)."""
    if not user_has_permission('edit_controllers'):
        return redirect(url_for('routes_ai_agent.page_ai_dashboard'))
    
    agent_name = request.form.get('name')
    entry_id = request.form.get('entry_id')
    role = request.form.get('role', 'worker')
    specialty = request.form.get('specialty', 'general')
    system_prompt = request.form.get('system_prompt')
    
    # If system_prompt is empty or default, try to fetch from preset
    if not system_prompt or system_prompt == 'You are a helpful assistant.':
        check_model_type = request.form.get('model_type', '')
        if not check_model_type and entry_id != 'new':
            from aot.databases.models.ai import AIEntry
            e = AIEntry.query.get(entry_id)
            if e:
                check_model_type = e.model_type
        
        if check_model_type:
            # v20.0: Correctly pull preset prompt
            preset = AIAgentService.get_engine_info(check_model_type)
            if preset and preset.get('system_prompt'):
                system_prompt = preset.get('system_prompt')
    
    # Final fallback if still empty
    if not system_prompt:
        system_prompt = 'You are a helpful assistant for the AoT (AI of Things) platform.'

    if not agent_name:
        flash(gettext("Agent name is required."), "error")
        return redirect(url_for('routes_ai_agent.page_ai_agent'))

    # Handling new service creation
    if entry_id == 'new':
        service_name = request.form.get('service_name')
        if not service_name:
            flash(gettext("Service name is required for new service registration."), "error")
            return redirect(url_for('routes_ai_agent.page_ai_agent'))
        
        new_entry = AIEntry(
            name=service_name,
            model_type=request.form.get('model_type', ''),
            model_name=request.form.get('model_name', ''),
            api_endpoint=request.form.get('api_endpoint', ''),
            auth_type=request.form.get('auth_type', 'api_key'),
            auth_id=request.form.get('auth_id', ''),
            api_key=request.form.get('api_key', ''),
            is_activated=False
        )
        # If model_name is missing, fallback to preset default
        if not new_entry.model_name and new_entry.model_type:
            preset = AIAgentService.get_engine_info(new_entry.model_type)
            models = preset.get('models', [])
            if models:
                first_model = models[0]
                new_entry.model_name = first_model.get('value') if isinstance(first_model, dict) else first_model

        new_entry.save()
        entry_id = new_entry.unique_id
        flash(gettext("AI Service '%(name)s' registered.", name=service_name), "success")
        
        # [Auto-Save to API Key Manager]
        if new_entry.api_key:
            from aot.aot_flask.utils import utils_settings
            utils_settings.auto_register_api_key(
                value=new_entry.api_key,
                name=f"AI Service: {service_name}",
                provider=new_entry.model_type,
                tag="AI_SERVICE"
            )

    if not entry_id:
        flash(gettext("An AI Service (Entry) must be selected."), "error")
        return redirect(url_for('routes_ai_agent.page_ai_agent'))

    # v6: Automatic pipeline_role mapping based on model_type
    ENGINE_ROLE_MAP = {
        'ai_router': 'router',
        'ai_planner': 'planner',
        'ai_synthesizer': 'synthesizer'
    }
    
    # If pipeline_role is default 'worker', check if we should map it based on engine
    pipeline_role = request.form.get('pipeline_role', 'worker')
    if pipeline_role == 'worker':
        # Check model_type from form (for new) or from entry (for existing)
        check_model_type = request.form.get('model_type', '')
        if not check_model_type and entry_id != 'new':
            from aot.databases.models.ai import AIEntry
            e = AIEntry.query.get(entry_id)
            if e:
                check_model_type = e.model_type
        
        if check_model_type in ENGINE_ROLE_MAP:
            pipeline_role = ENGINE_ROLE_MAP[check_model_type]
            logger.info(f"Auto-mapping pipeline_role to '{pipeline_role}' based on engine '{check_model_type}'")

    new_agent = AIAgent(
        name=agent_name,
        entry_id=entry_id,
        role=role,
        specialty=specialty,
        system_prompt=system_prompt,
        pipeline_role=pipeline_role,
        model_tier=request.form.get('model_tier', 'standard'),
        tool_access=request.form.get('tool_access', 'auto'),
        custom_options_json=json.dumps(custom_options),
        is_activated=False
    )
    new_agent.save()

    # v6: Handle many-to-many MCP mapping
    if new_agent.tool_access == 'assigned':
        assigned_mcp_ids = request.form.getlist('assigned_mcp_ids')
        for mcp_id in assigned_mcp_ids:
            from aot.databases.models.mcp_server import AgentMCPAccess
            mapping = AgentMCPAccess(agent_unique_id=new_agent.unique_id, mcp_unique_id=mcp_id)
            db.session.add(mapping)
        db.session.commit()

    # v6: Sync env_var custom options → MCPServer.env_json
    model_type_val = request.form.get('model_type', '')
    if custom_options and model_type_val.startswith('mcp_'):
        info = AIAgentService.get_engine_info(model_type_val)
        env_updates = {}
        for opt in info.get('custom_options', []):
            env_key = opt.get('env_var')
            if env_key and custom_options.get(opt['id']):
                env_updates[env_key] = custom_options[opt['id']]
        if env_updates:
            from aot.databases.models.mcp_server import AgentMCPAccess as _MCA
            from aot.databases.models import MCPServer
            mapping = _MCA.query.filter_by(agent_unique_id=new_agent.unique_id).first()
            if mapping:
                mcp = MCPServer.query.filter_by(unique_id=mapping.mcp_unique_id).first()
                if mcp:
                    current_env = mcp.env_vars
                    current_env.update(env_updates)
                    mcp.env_vars = current_env
                    db.session.commit()

    flash(gettext("Agent '%(name)s' created.", name=agent_name), "success")
    return redirect(url_for('routes_ai_agent.page_ai_agent'))


@blueprint.route('/ai/agent/mod/<agent_id>', methods=['POST'])
@login_required
def ai_agent_mod(agent_id):
    """Modify an AI Agent."""
    if not user_has_permission('edit_controllers'):
        return redirect(url_for('routes_ai_agent.page_ai_dashboard'))
    agent = AIAgent.query.filter_by(unique_id=agent_id).first()
    if not agent:
        flash(gettext("Agent not found."), "error")
        return redirect(url_for('routes_ai_agent.page_ai_agent'))

    agent.name = request.form.get('name', agent.name)
    agent.role = request.form.get('role', agent.role)
    agent.specialty = request.form.get('specialty', agent.specialty)
    agent.system_prompt = request.form.get('system_prompt', agent.system_prompt)
    
    # v6: Update new pipeline fields
    agent.pipeline_role = request.form.get('pipeline_role', agent.pipeline_role)
    agent.model_tier = request.form.get('model_tier', agent.model_tier)
    agent.tool_access = request.form.get('tool_access', agent.tool_access)

    # v12: Update model name and api key in the linked entry if provided
    new_model_name = request.form.get('model_name')
    if new_model_name and agent.entry:
        agent.entry.model_name = new_model_name
        
    new_api_key = request.form.get('api_key')
    
    if new_api_key and new_api_key.strip() and agent.entry:
        agent.entry.api_key = new_api_key
        # v6: If this is an MCP agent, also sync this key into custom_options_json for the first env_var
        if agent.entry.model_type.startswith('mcp_'):
            info = AIAgentService.get_engine_info(agent.entry.model_type)
            # Find the primary env_var credential
            for _opt in info.get('custom_options', []):
                if _opt.get('env_var'): # Map to first env_var by default if top field is used
                    _cur_opts = json.loads(agent.custom_options_json or '{}')
                    _cur_opts[_opt['id']] = new_api_key
                    agent.custom_options_json = json.dumps(_cur_opts)
                    break

    # v12: Handle custom options (preserve blank password fields)
    existing_custom = json.loads(agent.custom_options_json or '{}')
    custom_options = {}
    for key, value in request.form.items():
        if key.startswith('custom_'):
            opt_id = key.replace('custom_', '', 1)
            custom_options[opt_id] = value

    if custom_options:
        model_type = agent.entry.model_type if agent.entry else ''
        info = AIAgentService.get_engine_info(model_type)
        pw_ids = {o['id'] for o in info.get('custom_options', []) if o.get('type') == 'password'}
        for pid in pw_ids:
            if pid in custom_options and not custom_options[pid].strip() and pid in existing_custom:
                custom_options[pid] = existing_custom[pid]
        agent.custom_options_json = json.dumps(custom_options)

    # v6: Sync env_var custom options → MCPServer.env_json
    # MCP service credentials (e.g. GOOGLE_MAPS_API_KEY) entered in the agent modal
    # must also be written to the linked MCPServer's env_json for subprocess injection.
    if custom_options and agent.entry and agent.entry.model_type.startswith('mcp_'):
        from aot.databases.models.mcp_server import MCPServer
        info = AIAgentService.get_engine_info(agent.entry.model_type)
        env_updates = {}
        for opt in info.get('custom_options', []):
            env_key = opt.get('env_var')
            if env_key and custom_options.get(opt['id']):
                env_updates[env_key] = custom_options[opt['id']]
        if env_updates:
            from aot.databases.models.mcp_server import AgentMCPAccess as _MCA
            mapping = _MCA.query.filter_by(agent_unique_id=agent.unique_id).first()
            if mapping:
                mcp = MCPServer.query.filter_by(unique_id=mapping.mcp_unique_id).first()
                if mcp:
                    current_env = mcp.env_vars
                    current_env.update(env_updates)
                    mcp.env_vars = current_env

    # v6: Handle many-to-many MCP mapping (refresh only when 'assigned' mode)
    from aot.databases.models.mcp_server import AgentMCPAccess
    if agent.tool_access == 'assigned':
        AgentMCPAccess.query.filter_by(agent_unique_id=agent.unique_id).delete()
        assigned_mcp_ids = request.form.getlist('assigned_mcp_ids')
        for mcp_id in assigned_mcp_ids:
            mapping = AgentMCPAccess(agent_unique_id=agent.unique_id, mcp_unique_id=mcp_id)
            db.session.add(mapping)

    try:
        db.session.commit()
        flash(gettext("Agent '%(name)s' updated.", name=agent.name), "success")
        
        # [Auto-Save to API Key Manager]
        if new_api_key and new_api_key.strip() and agent.entry:
            from aot.aot_flask.utils import utils_settings
            utils_settings.auto_register_api_key(
                value=new_api_key,
                name=f"AI Service: {agent.entry.name}",
                provider=agent.entry.model_type,
                tag="AI_SERVICE"
            )
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to update agent {agent_id}: {e}")
        flash(gettext("Error updating agent: %(err)s", err=str(e)), "error")

    return redirect(url_for('routes_ai_agent.page_ai_agent'))


@blueprint.route('/ai/agent/delete/<agent_id>', methods=['POST'])
@login_required
def ai_agent_delete(agent_id):
    """Delete an AI Agent."""
    if not user_has_permission('edit_controllers'):
        return redirect(url_for('routes_ai_agent.page_ai_dashboard'))
    agent = AIAgent.query.filter_by(unique_id=agent_id).first()
    if agent:
        entry = agent.entry
        agent_name = agent.name

        # v6: Clean up M:N MCP mappings and deactivate orphaned MCPServers
        from aot.databases.models.mcp_server import AgentMCPAccess
        orphan_mappings = AgentMCPAccess.query.filter_by(agent_unique_id=agent.unique_id).all()
        orphan_mcp_ids = [m.mcp_unique_id for m in orphan_mappings]
        AgentMCPAccess.query.filter_by(agent_unique_id=agent.unique_id).delete()

        # Delete MCPServers that no longer have any agent binding (kill process first)
        for mcp_id in orphan_mcp_ids:
            remaining = AgentMCPAccess.query.filter_by(mcp_unique_id=mcp_id).count()
            if remaining == 0:
                orphan_mcp = MCPServer.query.filter_by(unique_id=mcp_id).first()
                if orphan_mcp:
                    # Stop running process if any
                    try:
                        from aot.ai.services.mcp_bridge_service import MCPBridgeService
                        MCPBridgeService.stop_server(mcp_id)
                    except Exception:
                        pass
                    mcp_name = orphan_mcp.name
                    db.session.delete(orphan_mcp)
                    logger.info(f"Deleted orphaned MCPServer '{mcp_name}' after agent deletion.")

        agent.delete()

        # Cleanup: If the associated entry has no other agents, delete it too
        if entry:
            other_agents_count = AIAgent.query.filter_by(entry_id=entry.unique_id).count()
            if other_agents_count == 0:
                entry.delete()
                logger.info(f"Orphaned service '{entry.name}' cleaned up after deleting agent '{agent_name}'.")
        
        flash(gettext("Agent '%(name)s' deleted.", name=agent_name), "success")
    return redirect(url_for('routes_ai_agent.page_ai_agent'))


# ---------------------------------------------------------------------------
# Activate / Deactivate
# ---------------------------------------------------------------------------

@blueprint.route('/ai/entry/activate/<entry_id>', methods=['POST'])
@login_required
def ai_entry_activate(entry_id):
    """Activate an AI Service Entry."""
    if not user_has_permission('edit_controllers', silent=True):
        return jsonify({"status": "error", "message": "Permission denied"}), 403
    entry = AIEntry.query.filter_by(unique_id=entry_id).first()
    if not entry:
        return jsonify({"status": "error", "message": "Entry not found"}), 404
    entry.is_activated = True
    db.session.commit()
    return jsonify({"status": "success", "entry_id": entry_id})


@blueprint.route('/ai/entry/deactivate/<entry_id>', methods=['POST'])
@login_required
def ai_entry_deactivate(entry_id):
    """Deactivate an AI Service Entry."""
    if not user_has_permission('edit_controllers', silent=True):
        return jsonify({"status": "error", "message": "Permission denied"}), 403
    entry = AIEntry.query.filter_by(unique_id=entry_id).first()
    if not entry:
        return jsonify({"status": "error", "message": "Entry not found"}), 404
    entry.is_activated = False
    db.session.commit()
    return jsonify({"status": "success", "entry_id": entry_id})


@blueprint.route('/ai/agent/activate/<agent_id>', methods=['POST'])
@login_required
def ai_agent_activate(agent_id):
    """Activate an AI Agent."""
    if not user_has_permission('edit_controllers', silent=True):
        return jsonify({"status": "error", "message": "Permission denied"}), 403
    agent = AIAgent.query.filter_by(unique_id=agent_id).first()
    if not agent:
        return jsonify({"status": "error", "message": "Agent not found"}), 404
    agent.is_activated = True

    # v6: Re-activate assigned MCPServers when agent is activated
    from aot.databases.models.mcp_server import AgentMCPAccess
    mappings = AgentMCPAccess.query.filter_by(agent_unique_id=agent.unique_id).all()
    for m in mappings:
        mcp = MCPServer.query.filter_by(unique_id=m.mcp_unique_id).first()
        if mcp and not mcp.is_activated:
            mcp.is_activated = True
            logger.info(f"Re-activated MCPServer '{mcp.name}' with agent '{agent.name}'")

    db.session.commit()
    return jsonify({"status": "success", "agent_id": agent_id})


@blueprint.route('/ai/agent/deactivate/<agent_id>', methods=['POST'])
@login_required
def ai_agent_deactivate(agent_id):
    """Deactivate an AI Agent."""
    if not user_has_permission('edit_controllers', silent=True):
        return jsonify({"status": "error", "message": "Permission denied"}), 403
    agent = AIAgent.query.filter_by(unique_id=agent_id).first()
    if not agent:
        return jsonify({"status": "error", "message": "Agent not found"}), 404
    agent.is_activated = False

    # v6: Deactivate MCPServers exclusively bound to this agent
    from aot.databases.models.mcp_server import AgentMCPAccess
    mappings = AgentMCPAccess.query.filter_by(agent_unique_id=agent.unique_id).all()
    for m in mappings:
        # Only deactivate if no OTHER active agent also uses this MCP
        other_active = db.session.query(AgentMCPAccess).join(
            AIAgent, AgentMCPAccess.agent_unique_id == AIAgent.unique_id
        ).filter(
            AgentMCPAccess.mcp_unique_id == m.mcp_unique_id,
            AgentMCPAccess.agent_unique_id != agent.unique_id,
            AIAgent.is_activated == True
        ).count()
        if other_active == 0:
            mcp = MCPServer.query.filter_by(unique_id=m.mcp_unique_id).first()
            if mcp and mcp.is_activated:
                mcp.is_activated = False
                logger.info(f"Deactivated MCPServer '{mcp.name}' (no other active agents)")

    db.session.commit()
    return jsonify({"status": "success", "agent_id": agent_id})


# ---------------------------------------------------------------------------
# MCP Server CRUD (v13)
# ---------------------------------------------------------------------------

@blueprint.route('/ai/mcp/add', methods=['POST'])
@login_required
def ai_mcp_add():
    """Add a new MCP Server."""
    if not user_has_permission('edit_controllers'):
        return redirect(url_for('routes_ai_agent.page_ai_agent'))
    
    name = request.form.get('name')
    command = request.form.get('command')
    scope = request.form.get('scope', 'general')
    env_json = request.form.get('env_json', '{}')
    
    if not name or not command:
        flash(gettext("Name and Command are required for MCP Server."), "error")
        return redirect(url_for('routes_ai_agent.page_ai_agent'))

    new_mcp = MCPServer(
        name=name,
        command=command,
        scope=scope,
        env_json=env_json,
        is_activated=False
    )
    
    # Handle custom options
    custom_opts = {}
    for k, v in request.form.items():
        if k.startswith('custom_'):
            opt_id = k.replace('custom_', '', 1)
            custom_opts[opt_id] = v
    if custom_opts:
        new_mcp.custom_options_json = json.dumps(custom_opts)

    new_mcp.save()
    flash(gettext("MCP Server '%(name)s' added.", name=name), "success")
    return redirect(url_for('routes_ai_agent.page_ai_agent'))


@blueprint.route('/ai/mcp/mod/<mcp_id>', methods=['POST'])
@login_required
def ai_mcp_mod(mcp_id):
    """Modify an MCP Server."""
    if not user_has_permission('edit_controllers'):
        return redirect(url_for('routes_ai_agent.page_ai_agent'))
    
    mcp = MCPServer.query.filter_by(unique_id=mcp_id).first()
    if not mcp:
        flash(gettext("MCP Server not found."), "error")
        return redirect(url_for('routes_ai_agent.page_ai_agent'))

    mcp.name = request.form.get('name', mcp.name)
    mcp.command = request.form.get('command', mcp.command)
    mcp.scope = request.form.get('scope', mcp.scope)
    mcp.env_json = request.form.get('env_json', mcp.env_json)

    # Handle custom options
    custom_opts = {}
    for k, v in request.form.items():
        if k.startswith('custom_'):
            opt_id = k.replace('custom_', '', 1)
            custom_opts[opt_id] = v
    if custom_opts:
        mcp.custom_options_json = json.dumps(custom_opts)

    db.session.commit()
    flash(gettext("MCP Server '%(name)s' updated.", name=mcp.name), "success")
    return redirect(url_for('routes_ai_agent.page_ai_agent'))


@blueprint.route('/ai/mcp/delete/<mcp_id>', methods=['POST'])
@login_required
def ai_mcp_delete(mcp_id):
    """Delete an MCP Server."""
    if not user_has_permission('edit_controllers'):
        return redirect(url_for('routes_ai_agent.page_ai_agent'))
    
    mcp = MCPServer.query.filter_by(unique_id=mcp_id).first()
    if mcp:
        name = mcp.name
        # v6: Clean up M:N agent mappings before deleting MCP
        from aot.databases.models.mcp_server import AgentMCPAccess
        AgentMCPAccess.query.filter_by(mcp_unique_id=mcp.unique_id).delete()
        mcp.delete()
        flash(gettext("MCP Server '%(name)s' deleted.", name=name), "success")
    return redirect(url_for('routes_ai_agent.page_ai_agent'))


@blueprint.route('/ai/mcp/activate/<mcp_id>', methods=['POST'])
@login_required
def ai_mcp_activate(mcp_id):
    """Activate an MCP Server."""
    if not user_has_permission('edit_controllers', silent=True):
        return jsonify({"status": "error", "message": "Permission denied"}), 403
    mcp = MCPServer.query.filter_by(unique_id=mcp_id).first()
    if not mcp:
        return jsonify({"status": "error", "message": "MCP Server not found"}), 404
    mcp.is_activated = True
    db.session.commit()
    return jsonify({"status": "success", "mcp_id": mcp_id})


@blueprint.route('/ai/mcp/deactivate/<mcp_id>', methods=['POST'])
@login_required
def ai_mcp_deactivate(mcp_id):
    """Deactivate an MCP Server."""
    if not user_has_permission('edit_controllers', silent=True):
        return jsonify({"status": "error", "message": "Permission denied"}), 403
    mcp = MCPServer.query.filter_by(unique_id=mcp_id).first()
    if not mcp:
        return jsonify({"status": "error", "message": "MCP Server not found"}), 404
    mcp.is_activated = False
    db.session.commit()
    return jsonify({"status": "success", "mcp_id": mcp_id})


@blueprint.route('/ai/save_mcp_layout', methods=['POST'])
@login_required
def save_mcp_layout():
    """Save positions of MCP Servers."""
    if not user_has_permission('edit_controllers'):
        return jsonify({'status': 'error', 'message': 'Permission denied'}), 403
    data = request.get_json()
    for item in data:
        if 'id' in item and 'y' in item:
            mcp = MCPServer.query.filter_by(unique_id=item['id']).first()
            if mcp:
                mcp.position_x = item.get('x', 0)
                mcp.position_y = item['y']
                mcp.width = item.get('w', 24)
                mcp.height = item.get('h', 1)
    db.session.commit()
    return jsonify({'status': 'success'})


# ---------------------------------------------------------------------------
# v6: Quick Setup (MCP + Agent in one step)
# ---------------------------------------------------------------------------

@blueprint.route('/ai/quick-setup', methods=['POST'])
@login_required
def ai_quick_setup():
    """v6: Create an MCP Server + Executor Agent with M:N mapping in one step."""
    if not user_has_permission('edit_controllers'):
        return jsonify({"status": "error", "message": "Permission denied"}), 403

    mcp_name = request.form.get('mcp_name')
    mcp_command = request.form.get('mcp_command')
    agent_name = request.form.get('agent_name', f"{mcp_name} Executor")
    entry_id = request.form.get('entry_id')
    mcp_scope = request.form.get('scope', 'general')

    if not mcp_name or not mcp_command:
        return jsonify({"status": "error", "message": "MCP name and command are required"}), 400

    from aot.databases.models.mcp_server import AgentMCPAccess

    # 1. Create MCP Server (independent UUID)
    new_mcp = MCPServer(name=mcp_name, command=mcp_command, scope=mcp_scope, is_activated=True)
    new_mcp.save()

    # 2. Create Executor Agent
    new_agent = AIAgent(
        name=agent_name,
        entry_id=entry_id,
        role='worker',
        pipeline_role='executor',
        model_tier='standard',
        tool_access='assigned',
        is_activated=False
    )
    new_agent.save()

    # 3. Create M:N mapping
    access = AgentMCPAccess(agent_unique_id=new_agent.unique_id, mcp_unique_id=new_mcp.unique_id)
    db.session.add(access)
    db.session.commit()

    logger.info(f"[QuickSetup] Created MCP '{mcp_name}' + Agent '{agent_name}' with mapping")

    return jsonify({
        "status": "success",
        "agent_id": new_agent.unique_id,
        "mcp_id": new_mcp.unique_id
    })


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

@blueprint.route('/api/v1/ai/agent/reason', methods=['POST'])
@login_required
def ai_agent_reason():
    """Trigger reasoning for a specific agent."""
    if not user_has_permission('edit_controllers', silent=True):
        return jsonify({"status": "error", "message": "Insufficient permission"}), 403

    data = request.json or {}
    agent_id = data.get('agent_id')
    goal = data.get('goal', 'General optimization')

    if not agent_id:
        return jsonify({"status": "error", "message": "Missing agent_id"}), 400

    result = AIAgentService.run_agent_reasoning(agent_id, goal)
    return jsonify(result)


@blueprint.route('/api/v1/ai/agent/execute', methods=['POST'])
@login_required
def ai_agent_execute():
    """Execute a specific logged action from history. Admin only."""
    data = request.json or {}
    history_id = data.get('history_id')
    action_index = data.get('action_index', 0)

    if not history_id:
        return jsonify({"status": "error", "message": "Missing history_id"}), 400

    if flask_login.current_user.role_id != 1:
        return jsonify({"status": "error", "message": "Admin privileges required"}), 403

    result = AIAgentService.execute_logged_action(history_id, action_index)
    return jsonify(result)


@blueprint.route('/api/v1/ai/service/<entry_id>/info', methods=['GET'])
@login_required
def ai_service_info(entry_id):
    """Get engine-specific information for a service entry."""
    entry = AIEntry.query.filter_by(unique_id=entry_id).first()
    if not entry:
        return jsonify({"status": "error", "message": "Service entry not found"}), 404

    info = AIAgentService.get_engine_info(entry.model_type)
    return jsonify({
        "status": "success",
        "model_type": entry.model_type,
        "ai_information": info
    })


@blueprint.route('/api/v1/ai/tasks', methods=['GET'])
@login_required
def ai_get_tasks():
    """Retrieves all AI tasks and Scheduler jobs for Gantt visualization."""
    from aot.databases.models import SchedulerJobMeta
    
    # Order by parent_id (grouping), then sort_order, then start_date
    tasks = AITask.query.order_by(AITask.parent_id, AITask.sort_order.asc(), AITask.start_date.asc()).all()
    serialized = []
    
    # 1. Add General Tasks (AITask)
    for t in tasks:
        serialized.append({
            'id': t.unique_id,
            'content': t.title,
            'start': t.start_date.isoformat() if t.start_date else None,
            'end': t.end_date.isoformat() if t.end_date else None,
            'type': t.task_type,
            'status': t.status,
            'parent_id': t.parent_id,
            'assignee_id': t.assignee_id,
            'assignee_type': t.assignee_type,
            'is_goal': t.is_goal,
            'layer': 'general'
        })
    
    # 2. Add AoT Device Jobs (SchedulerJobMeta)
    jobs = SchedulerJobMeta.query.all()
    for j in jobs:
        # We treat each job as a "task" in the Gantt
        serialized.append({
            'id': f"job_{j.unique_id}",
            'content': f"[{j.action_type.upper()}] {j.target_id}",
            'start': j.schedule_time.isoformat() if j.schedule_time else None,
            'end': j.end_time.isoformat() if j.end_time else (j.schedule_time.isoformat() if j.schedule_time else None),
            'type': 'device_control',
            'status': j.state.lower(),
            'parent_id': 'group_aot_devices', # Fixed group for devices
            'assignee_id': 'AI',
            'assignee_type': 'agent',
            'is_goal': False,
            'layer': 'aot'
        })
        
    return jsonify(serialized)


@blueprint.route('/api/v1/ai/task/add', methods=['POST'])
@login_required
def ai_task_add_api():
    """Adds a new AITask."""
    if not user_has_permission('edit_controllers'):
        return jsonify({"status": "error", "message": "Permission denied"}), 403
    
    data = request.json or {}
    title = data.get('title')
    if not title:
        return jsonify({"status": "error", "message": "Missing title"}), 400
    
    new_task = AITask(
        title=title,
        description=data.get('description', ''),
        task_type=data.get('task_type', 'task'),
        parent_id=data.get('parent_id'),
        owner_id=flask_login.current_user.unique_id,
        status='pending'
    )
    
    # Handle dates
    from datetime import datetime
    try:
        if data.get('start_date'):
            new_task.start_date = datetime.fromisoformat(data['start_date'].replace('Z', '+00:00'))
        else:
            new_task.start_date = utc_now()
            
        if data.get('end_date'):
            new_task.end_date = datetime.fromisoformat(data['end_date'].replace('Z', '+00:00'))
    except ValueError as e:
        return jsonify({"status": "error", "message": f"Invalid date format: {e}"}), 400
        
    new_task.save()
    return jsonify({"status": "success", "task_id": new_task.unique_id})


@blueprint.route('/api/v1/ai/task/delete/<task_id>', methods=['POST', 'DELETE'])
@login_required
def ai_task_delete_api(task_id):
    """Deletes an AITask."""
    if not user_has_permission('edit_controllers'):
        return jsonify({"status": "error", "message": "Permission denied"}), 403
    
    task = AITask.query.filter_by(unique_id=task_id).first()
    if not task:
        return jsonify({"status": "error", "message": "Task not found"}), 404
        
    parent_id = task.parent_id
    task.delete()
    
    if parent_id:
        from aot.ai.services.task_manager import task_status_aggregator
        task_status_aggregator(parent_id)
        
    return jsonify({"status": "success"})


@blueprint.route('/api/v1/ai/task/reorder', methods=['POST'])
@login_required
def ai_task_reorder():
    """Updates parent_id of a task for hierarchy changes."""
    if not user_has_permission('edit_controllers'):
        return jsonify({"status": "error", "message": "Permission denied"}), 403
    
    data = request.json or {}
    task_id = data.get('task_id')
    new_parent_id = data.get('parent_id')
    direction = data.get('direction') # 'up' or 'down'

    if not task_id:
        return jsonify({"status": "error", "message": "Missing task_id"}), 400

    task = AITask.query.filter_by(unique_id=task_id).first()
    if not task:
        return jsonify({"status": "error", "message": "Task not found"}), 404

    from aot.ai.services.task_manager import prevent_cycle, task_status_aggregator
    
    # Case 1: Change Parent (Indent/Outdent)
    if new_parent_id is not None or 'parent_id' in data:
        if new_parent_id and prevent_cycle(new_parent_id, task_id):
            return jsonify({"status": "error", "message": "Circular dependency detected"}), 400

        old_parent_id = task.parent_id
        task.parent_id = new_parent_id
        db.session.commit()

        if old_parent_id: task_status_aggregator(old_parent_id)
        if new_parent_id: task_status_aggregator(new_parent_id)
        return jsonify({"status": "success", "task_id": task_id, "parent_id": new_parent_id})

    # Case 2: Change Order (Up/Down)
    if direction:
        siblings = AITask.query.filter_by(parent_id=task.parent_id).order_by(AITask.sort_order.asc(), AITask.start_date.asc()).all()
        idx = -1
        for i, s in enumerate(siblings):
            if s.unique_id == task_id:
                idx = i
                break
        
        if idx == -1:
            return jsonify({"status": "error", "message": "Task not found in siblings"}), 404
        
        target_idx = -1
        if direction == 'up' and idx > 0:
            target_idx = idx - 1
        elif direction == 'down' and idx < len(siblings) - 1:
            target_idx = idx + 1
            
        if target_idx != -1:
            target_task = siblings[target_idx]
            # Swap sort_order
            # If sort_order is same (initially 0), we need to re-index them
            if task.sort_order == target_task.sort_order:
                for i, s in enumerate(siblings):
                    s.sort_order = i * 10
                db.session.commit()
                # Refetch after re-index to get updated values
                task = AITask.query.filter_by(unique_id=task_id).first()
                siblings = AITask.query.filter_by(parent_id=task.parent_id).order_by(AITask.sort_order.asc(), AITask.start_date.asc()).all()
                idx = siblings.index(task)
                target_idx = idx - 1 if direction == 'up' else idx + 1
                target_task = siblings[target_idx]

            # Final Swap
            task.sort_order, target_task.sort_order = target_task.sort_order, task.sort_order
            db.session.commit()
            return jsonify({"status": "success", "task_id": task_id, "direction": direction})

    return jsonify({"status": "error", "message": "Nothing to update"}), 400


@blueprint.route('/api/v1/ai/task/update', methods=['POST'])
@login_required
def ai_task_update():
    """Updates task properties (title, description, status, dates, etc.)."""
    if not user_has_permission('edit_controllers'):
        return jsonify({"status": "error", "message": "Permission denied"}), 403
    
    data = request.json or {}
    task_id = data.get('task_id')
    if not task_id:
        return jsonify({"status": "error", "message": "Missing task_id"}), 400

    task = AITask.query.filter_by(unique_id=task_id).first()
    if not task:
        return jsonify({"status": "error", "message": "Task not found"}), 404

    # Update basic fields (only if key explicitly provided)
    if 'title' in data:       task.title = data['title']
    if 'description' in data: task.description = data['description']
    if 'status' in data:      task.status = data['status']
    if 'task_type' in data:   task.task_type = data['task_type']
    if 'priority' in data:    task.priority = data['priority']
    
    # Hierarchy update
    new_parent_id = data.get('parent_id')
    if 'parent_id' in data:
        # Check for cycles if changing parent
        if new_parent_id and new_parent_id != task.parent_id:
            from aot.ai.services.task_manager import prevent_cycle
            if prevent_cycle(new_parent_id, task.unique_id):
                return jsonify({"status": "error", "message": "Circular dependency"}), 400
        task.parent_id = new_parent_id

    # Update dates
    from datetime import datetime
    try:
        if 'start_date' in data and data['start_date']:
            # Handle possible datetime objects or strings
            val = data['start_date']
            if isinstance(val, str):
                task.start_date = datetime.fromisoformat(val.replace('Z', '+00:00'))
        if 'end_date' in data and data['end_date']:
            val = data['end_date']
            if isinstance(val, str):
                task.end_date = datetime.fromisoformat(val.replace('Z', '+00:00'))
    except ValueError as e:
        return jsonify({"status": "error", "message": f"Invalid date format: {e}"}), 400

    db.session.commit()

    # If status changed, trigger aggregation on parent
    if 'status' in data and task.parent_id:
        from aot.ai.services.task_manager import task_status_aggregator
        task_status_aggregator(task.parent_id)

    # If dates changed, recalculate parent's date range from children
    if ('start_date' in data or 'end_date' in data) and task.parent_id:
        from aot.ai.services.task_manager import sync_parent_dates
        sync_parent_dates(task.parent_id)

    return jsonify({"status": "success", "task_id": task_id})

@blueprint.route('/api/v1/ai/settings/update', methods=['POST'])
@login_required
def api_update_ai_settings():
    """Update AI Global Settings."""
    if not user_has_permission('edit_controllers'):
        return jsonify({'status': 'error', 'message': 'Permission denied'}), 403
    
    data = request.get_json()
    ai_settings = AIGlobalSettings.query.first()
    if not ai_settings:
        ai_settings = AIGlobalSettings(id=1)
        db.session.add(ai_settings)
        
    try:
        if 'auto_approve_routine' in data:
            ai_settings.auto_approve_routine = bool(data['auto_approve_routine'])
        if 'max_impact_auto_approve' in data:
            ai_settings.max_impact_auto_approve = int(data['max_impact_auto_approve'])
        if 'blackout_start' in data:
            ai_settings.blackout_start = str(data['blackout_start'])
        if 'blackout_end' in data:
            ai_settings.blackout_end = str(data['blackout_end'])
        if 'require_feedback' in data:
            ai_settings.require_feedback = bool(data['require_feedback'])
        if 'default_supervisor' in data:
            ai_settings.default_supervisor = str(data['default_supervisor'])
        if 'default_worker' in data:
            ai_settings.default_worker = str(data['default_worker'])
        if 'context_hours' in data:
            ai_settings.context_hours = int(data['context_hours'])
        if 'max_history' in data:
            ai_settings.max_history = int(data['max_history'])
        if 'budget_limit_usd' in data:
            ai_settings.budget_limit_usd = float(data['budget_limit_usd'])
        
        # System Prompt Template Update
        if 'system_prompt_template' in data:
            ai_settings.system_prompt_template = str(data['system_prompt_template'])
        
        if 'context_broadcast_enabled' in data:
            ai_settings.context_broadcast_enabled = bool(data['context_broadcast_enabled'])

        # AI Feature Toggle
        if 'ai_enabled' in data:
            new_val = bool(data['ai_enabled'])
            if ai_settings.ai_enabled != new_val:
                ai_settings.ai_enabled = new_val

        # Multi-site default facility — lives on Misc (shared with the rest
        # of the app), not AIGlobalSettings. This is the fallback
        # _resolve_facility_id() uses everywhere (AI Library, conversational
        # AI, portal) when no page-level facility scope is resolved.
        if 'default_facility_id' in data:
            misc = Misc.query.first()
            if misc:
                misc.default_facility_id = str(data['default_facility_id'] or '')

        restart_required = False
        db.session.commit()
        return jsonify({
            "status": "success", 
            "message": "Settings updated",
            "restart_required": restart_required
        })
    except Exception as e:
        logger.exception("Failed to update AI settings")
        return jsonify({"status": "error", "message": str(e)}), 500

@blueprint.route('/api/v1/ai/task/reject', methods=['POST'])
@login_required
def api_reject_ai_task():
    """Reject (delete) a PROPOSED AITask."""
    if not user_has_permission('edit_controllers'):
        return jsonify({'status': 'error', 'message': 'Permission denied'}), 403
    data = request.get_json()
    task_id = data.get('task_id')
    if not task_id:
        return jsonify({'status': 'error', 'message': 'Missing task_id'}), 400
        
    task = AITask.query.filter_by(unique_id=task_id).first()
    if task:
        task.status = 'cancelled'
        db.session.commit()
        return jsonify({'status': 'success', 'message': 'Task rejected and marked as cancelled'})
    return jsonify({'status': 'error', 'message': 'Task not found'}), 404


# ---------------------------------------------------------------------------
# Device & Connectivity management
# ---------------------------------------------------------------------------

@blueprint.route('/api/v1/ai/devices', methods=['GET'])
@login_required
def api_ai_devices():
    """
    Returns a JSON list of all Input and Output devices with their AI enablement status.
    Used by the AI Settings modal (Tab 2).
    """
    try:
        from aot.databases.models.input import Input
        from aot.databases.models.output import Output
        
        inputs = Input.query.all()
        outputs = Output.query.all()
        
        devices = []
        for inp in inputs:
            devices.append({
                'device_id': inp.unique_id,
                'name': inp.name or inp.unique_id,
                'kind': 'input',
                'device_type': inp.device or 'unknown',
                'is_ai_enabled': getattr(inp, 'is_ai_enabled', False),
                'is_activated': inp.is_activated
            })
            
        for out in outputs:
            devices.append({
                'device_id': out.unique_id,
                'name': out.name or out.unique_id,
                'kind': 'output',
                'device_type': out.output_type or 'unknown',
                'is_ai_enabled': getattr(out, 'is_ai_enabled', False),
                'is_activated': getattr(out, 'is_activated', True) # Output lacks is_activated column
            })
            
        return jsonify(devices)
    except Exception as e:
        logger.error(f"[api_ai_devices] Error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@blueprint.route('/api/v1/ai/devices/<device_id>/ai_toggle', methods=['POST'])
@login_required
def api_ai_device_toggle(device_id):
    """
    Toggle is_ai_enabled for a specific Input or Output device.
    Body: { "kind": "input"|"output", "is_ai_enabled": true|false }
    """
    if not user_has_permission('edit_controllers'):
        return jsonify({'status': 'error', 'message': 'Permission denied'}), 403

    data = request.get_json() or {}
    kind = data.get('kind', 'input')
    enabled = bool(data.get('is_ai_enabled', False))

    try:
        if kind == 'input':
            from aot.databases.models.input import Input
            device = Input.query.filter_by(unique_id=device_id).first()
        else:
            from aot.databases.models.output import Output
            device = Output.query.filter_by(unique_id=device_id).first()

        if not device:
            return jsonify({'status': 'error', 'message': 'Device not found'}), 404

        if not hasattr(device, 'is_ai_enabled'):
            return jsonify({
                'status': 'error',
                'message': 'DB migration required. Run aot/scripts/add_is_ai_enabled_field.py first.'
            }), 500

        device.is_ai_enabled = enabled
        db.session.commit()
        return jsonify({'status': 'success', 'device_id': device_id, 'is_ai_enabled': enabled})

    except Exception as exc:
        logger.error(f"[api_ai_device_toggle] Error: {exc}")
        db.session.rollback()
        # Handle cases where column might be missing despite migration check
        return jsonify({
            'status': 'error',
            'message': f"Operation failed: {str(exc)}. If this is a 'no such column' error, please run the migration script."
        }), 500


@blueprint.route('/api/v1/ai/device-context/<device_id>', methods=['GET'])
@login_required
def api_get_device_ai_context(device_id):
    """
    Get AI context data for a specific device.
    Returns device identity and device-type-specific context sections.
    """
    if not user_has_permission('edit_controllers'):
        return jsonify({'status': 'error', 'message': 'Permission denied'}), 403

    try:
        from aot.ai.device_ai_context_assembler import DeviceAIContextAssembler

        assembler = DeviceAIContextAssembler(db.session)
        context = assembler.get_device_context(device_id)

        if context is None:
            return jsonify({'status': 'error', 'message': 'Device not found'}), 404

        return jsonify({
            'status': 'success',
            'device_id': device_id,
            'context': context
        }), 200

    except Exception as exc:
        logger.error(f"[api_get_device_ai_context] Error: {exc}")
        return jsonify({
            'status': 'error',
            'message': f"Failed to retrieve device context: {str(exc)}"
        }), 500
