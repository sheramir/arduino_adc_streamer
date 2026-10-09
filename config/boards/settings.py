"""Bridge legacy GUI state to semantic parameters without board-name branching."""
from copy import deepcopy
from . import get_board_registry


def context_for(owner):
    context = getattr(owner, 'board_context', None)
    name = getattr(owner, 'current_mcu', None)
    state = getattr(owner, 'config', {})
    selected = state.get('array_operation_mode', 'PZT')
    if context and context.reported_mcu == (name or '').strip() and context.mode is context.profile.mode(selected):
        return context
    return get_board_registry().context(name, selected)


def parameter_values(state):
    from dataclasses import asdict, is_dataclass
    values = asdict(state) if is_dataclass(state) else dict(state)
    values.update(values.pop('parameters', {}))
    return values


def legacy_updates(mode, resolved):
    return {p.legacy_key: resolved.requested[key] for key, p in mode.parameters.items()}


def set_parameter(owner, key, value):
    """Write through the active definition, including its compatibility state key."""
    parameter = context_for(owner).mode.parameters[key]
    owner.config[parameter.legacy_key] = parameter.normalize(value)


def validate_state(context, state):
    return context.mode.resolve_settings(parameter_values(state))


class BoardPreferences:
    """JSON-serializable preferences, separate from display/capture state."""
    def __init__(self, data=None):
        self.data = deepcopy(data or {})

    def save(self, context, state):
        settings = validate_state(context, state)
        self.data.setdefault(context.profile.id, {})[context.mode.id] = dict(settings.requested)

    def restore(self, context):
        if context.profile.definition.get('preferences', {}).get('reconnect') == 'defaults':
            return context.mode.resolve_settings()
        saved = self.data.get(context.profile.id, {}).get(context.mode.id, {})
        valid = {}
        for key, value in saved.items():
            if key in context.mode.parameters:
                try:
                    valid[key] = context.mode.parameters[key].normalize(value)
                except ValueError:
                    pass
        return context.mode.resolve_settings(valid)
