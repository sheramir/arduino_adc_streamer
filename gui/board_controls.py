"""Generic profile bindings for existing controls and future scalar parameters."""
from PyQt6.QtWidgets import QComboBox, QSpinBox, QDoubleSpinBox, QCheckBox, QLineEdit, QLabel, QFormLayout, QGroupBox
from config.boards.settings import context_for, parameter_values, legacy_updates


# Widget identities are app layout, not board defaults or capabilities.
BINDINGS = {
    'reference': ('vref_combo', 'vref_label'), 'osr': ('osr_combo', 'osr_label'),
    'gain': ('gain_combo', 'gain_label'), 'samples_per_channel': ('repeat_spin', 'repeat_label'),
    'settling_conversions': ('repeat_spin', 'repeat_label'), 'sweeps_per_block': ('buffer_spin', 'buffer_label'),
    'ground_pin': ('ground_pin_spin', 'ground_pin_label'),
    'ground_sampling': ('use_ground_check', None), 'vmid_sampling': ('use_ground_check', None),
    'spi_clock_hz': ('board_spi_clock_spin', 'board_spi_clock_label'),
    'sequence': ('board_sequence_combo', 'board_sequence_label'),
    'array_selection': ('sampled_array_combo', 'sampled_array_label'),
    'scan_order': ('array_scan_order_combo', 'array_scan_order_label'),
    'conversion_speed': ('conv_speed_combo', 'conv_speed_label'),
    'sampling_speed': ('samp_speed_combo', 'samp_speed_label'), 'sample_rate': ('sample_rate_spin', 'sample_rate_label'),
    'rb_ohms': ('rb_spin', 'rb_label'), 'rk_ohms': ('rk_spin', 'rk_label'), 'rxmax_ohms': ('rxmax_spin', 'rxmax_label'),
}


def bind_parameter(widget, param, value):
    definition = param.definition
    widget.blockSignals(True)
    try:
        if isinstance(widget, QComboBox):
            widget.clear()
            for choice in param.choices:
                widget.addItem(choice['label'], choice['id'])
            index = widget.findData(value)
            widget.setCurrentIndex(index if index >= 0 else widget.findData(param.default))
        elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
            scale = definition.get('display_scale', 1)
            low, high = definition.get('minimum', 0) * scale, definition.get('maximum', 1e9) * scale
            if isinstance(widget, QSpinBox):
                widget.setRange(int(low), int(high))
                widget.setValue(int(value * scale))
            else:
                widget.setDecimals(definition.get('decimals', 3))
                widget.setRange(low, high)
                widget.setSingleStep(definition.get('step', 1) * scale)
                widget.setValue(value * scale)
        elif isinstance(widget, QCheckBox):
            widget.setText(param.label)
            widget.setChecked(value)
        elif isinstance(widget, QLineEdit):
            widget.setText(str(value))
        widget.setToolTip(definition.get('tooltip', ''))
    finally:
        widget.blockSignals(False)


def widget_value(widget, param):
    if isinstance(widget, QComboBox):
        return widget.currentData() if widget.currentData() is not None else param.default
    if isinstance(widget, (QSpinBox, QDoubleSpinBox)):
        value = widget.value() / param.definition.get('display_scale', 1)
        return int(round(value)) if param.definition['type'] == 'integer' else value
    if isinstance(widget, QCheckBox):
        return widget.isChecked()
    return widget.text()


def create_parameter_widget(param):
    kind = param.definition['type']
    return {'enum': QComboBox, 'integer': QSpinBox, 'number': QDoubleSpinBox,
            'boolean': QCheckBox, 'text': QLineEdit}[kind]()


def apply_board_controls(owner, *, defaults=False):
    context = context_for(owner)
    if hasattr(owner, 'live_time_window_spin'):
        from config.boards.streaming import streaming_policy
        owner.live_time_window_spin.setVisible(streaming_policy(context.mode).batched)
    values = {} if defaults else parameter_values(owner.config)
    # Values from another board are migrated one field at a time.
    valid = {}
    ordered_parameters = sorted(context.mode.parameters.items(), key=lambda item: item[1].definition.get('order', 9999))
    for key, param in ordered_parameters:
        try:
            valid[key] = param.normalize(values.get(key, values.get(param.legacy_key, param.default)))
        except ValueError:
            valid[key] = param.default
    resolved = context.mode.resolve_settings(valid)
    updates = legacy_updates(context.mode, resolved)
    if hasattr(owner.config, 'register_parameters'):
        owner.config.register_parameters(context.mode)
    for key, value in updates.items():
        if hasattr(owner.config, 'parameters') and not hasattr(owner.config, key):
            owner.config.parameters[key] = value
        else:
            owner.config[key] = value
    used = set()
    controls = {}
    extras = getattr(owner, '_board_extra_controls', {})
    for widget, label in extras.values():
        widget.hide()
        widget.setEnabled(False)
        label.hide()
    for key, param in ordered_parameters:
        if key == 'cf_farads':  # Existing capacitance value/unit editor.
            if hasattr(owner, 'cf_value_spin'):
                unit = owner.cf_unit_combo.currentText()
                scale = {'pF': 1e-12, 'nF': 1e-9, 'uF': 1e-6}[unit]
                owner.cf_value_spin.blockSignals(True)
                owner.cf_value_spin.setRange(param.definition['minimum'] / scale, param.definition['maximum'] / scale)
                owner.cf_value_spin.setValue(resolved.requested[key] / scale)
                owner.cf_value_spin.blockSignals(False)
                for attr in ('cf_label', 'cf_value_spin', 'cf_unit_combo', 'cf_apply_btn'):
                    getattr(owner, attr).setVisible(resolved.visible[key])
                    getattr(owner, attr).setEnabled(resolved.enabled[key] and not getattr(owner, 'is_capturing', False))
            continue
        names = BINDINGS.get(key)
        if names:
            attr, label_attr = names
            # Settling conversions share the legacy Repeat widget; fixed payload repeat has no control.
            if key == 'samples_per_channel' and 'settling_conversions' in context.mode.parameters:
                continue
            widget = getattr(owner, attr, None)
            label = getattr(owner, label_attr, None) if label_attr else None
        else:
            if not hasattr(owner, 'adc_config_group'):
                continue
            section = param.definition.get('section', 'adc')
            groups = getattr(owner, '_board_extra_groups', {})
            if section not in groups:
                group = QGroupBox('Board parameters')
                group.setLayout(QFormLayout())
                parent = getattr(owner, 'acquisition_group', owner.adc_config_group) if section == 'acquisition' else owner.adc_config_group
                layout = parent.layout()
                layout.addWidget(group, layout.rowCount(), 0, 1, layout.columnCount())
                groups[section] = group
                owner._board_extra_groups = groups
            if key not in extras:
                widget, label = create_parameter_widget(param), QLabel(param.label)
                extras[key] = (widget, label)
                groups[section].layout().addRow(label, widget)
                def changed(*args, parameter=param, control=widget):
                    parameter = context_for(owner).mode.parameters.get(parameter.id)
                    if parameter is None:
                        return
                    owner.config.parameters[parameter.legacy_key] = parameter.normalize(widget_value(control, parameter))
                    owner.config_is_valid = False
                    owner.update_start_button_state()
                signal = widget.currentIndexChanged if isinstance(widget, QComboBox) else widget.valueChanged if isinstance(widget, (QSpinBox, QDoubleSpinBox)) else widget.toggled if isinstance(widget, QCheckBox) else widget.textChanged
                signal.connect(changed)
            widget, label = extras[key]
        if widget is None:
            continue
        controls[key] = widget
        used.add(widget)
        bind_parameter(widget, param, resolved.effective[key])
        widget.setVisible(resolved.visible[key] or param.definition.get('policy') == 'fixed' and key == 'ground_pin')
        widget.setEnabled(resolved.enabled[key] and not getattr(owner, 'is_capturing', False))
        if label:
            label.setText(param.label)
            label.setVisible(resolved.visible[key] or key == 'ground_pin')
    for attr, label_attr in BINDINGS.values():
        widget = getattr(owner, attr, None)
        if widget is not None and widget not in used:
            widget.hide()
            if label_attr and hasattr(owner, label_attr):
                getattr(owner, label_attr).hide()
    owner._board_parameter_controls = controls
    owner._board_extra_controls = extras
    for section, group in getattr(owner, '_board_extra_groups', {}).items():
        group.setVisible(any(k in context.mode.parameters and context.mode.parameters[k].definition.get('section', 'adc') == section for k in extras))
    if hasattr(owner, 'adc_config_group'):
        owner.adc_config_group.setVisible(any(p.definition.get('section') == 'adc' and p.definition.get('policy') == 'editable'
                                             for p in context.mode.parameters.values()))
    return resolved


def refresh_parameter_rules(owner, *, capture_locked=False):
    context = context_for(owner)
    resolved = context.mode.resolve_settings(parameter_values(owner.config))
    owner.config.update(legacy_updates(context.mode, resolved))
    for key, widget in getattr(owner, '_board_parameter_controls', {}).items():
        bind_parameter(widget, context.mode.parameters[key], resolved.effective[key])
        widget.setEnabled(resolved.enabled[key] and not capture_locked)
        visible = resolved.visible[key] or context.mode.parameters[key].definition.get('policy') == 'fixed' and key == 'ground_pin'
        widget.setVisible(visible)
        label_attr = BINDINGS.get(key, (None, None))[1]
        label = getattr(owner, label_attr, None) if label_attr else getattr(owner, '_board_extra_controls', {}).get(key, (None, None))[1]
        if label:
            label.setVisible(visible)


def read_board_controls(owner):
    context = context_for(owner)
    values = parameter_values(owner.config)
    for key, widget in getattr(owner, '_board_parameter_controls', {}).items():
        param = context.mode.parameters.get(key)
        if param and param.definition.get('policy') == 'editable':
            # Disabled repeat displays effective auto1; keep manual requested value.
            if widget.isEnabled():
                values[key] = widget_value(widget, param)
    if 'cf_farads' in context.mode.parameters and hasattr(owner, '_get_cf_farads_from_controls'):
        values['cf_farads'] = owner._get_cf_farads_from_controls()
    return context.mode.resolve_settings(values)
