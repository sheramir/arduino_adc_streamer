"""
ADC Configuration Snapshot Helpers
==================================
Normalize widget-derived ADC config values into a plain snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass


VREF_LABEL_TO_COMMAND = {
    "1.2V (Internal)": "1.2",
    "3.3V (VDD)": "vdd",
}


@dataclass(frozen=True, slots=True)
class ADCConfigurationSnapshot:
    reference: str
    osr: int
    gain: int
    repeat: int
    use_ground: bool
    ground_pin: int
    conv_speed: str
    samp_speed: str
    sample_rate: int
    array_operation_mode: str
    rb_ohms: float
    rk_ohms: float
    cf_farads: float
    rxmax_ohms: float

    def as_config_updates(self) -> dict:
        return {
            "reference": self.reference,
            "osr": self.osr,
            "gain": self.gain,
            "repeat": self.repeat,
            "use_ground": self.use_ground,
            "ground_pin": self.ground_pin,
            "conv_speed": self.conv_speed,
            "samp_speed": self.samp_speed,
            "sample_rate": self.sample_rate,
            "array_operation_mode": self.array_operation_mode,
            "rb_ohms": self.rb_ohms,
            "rk_ohms": self.rk_ohms,
            "cf_farads": self.cf_farads,
            "rxmax_ohms": self.rxmax_ohms,
        }


def normalize_reference(*, current_reference: str, vref_label: str | None, use_vref_control: bool) -> str:
    if not use_vref_control or not vref_label:
        return current_reference
    return VREF_LABEL_TO_COMMAND.get(vref_label, current_reference)


def normalize_gain(*, current_gain: int, gain_label: str | None) -> int:
    if not gain_label:
        return int(current_gain)
    return int(gain_label.replace("×", ""))


def build_adc_configuration_snapshot(
    *,
    current_reference: str,
    vref_label: str | None,
    use_vref_control: bool,
    current_osr: int,
    osr_label: str | None,
    current_gain: int,
    gain_label: str | None,
    current_repeat: int,
    repeat_value: int | None,
    current_use_ground: bool,
    use_ground_checked: bool | None,
    current_ground_pin: int,
    ground_pin_value: int | None,
    current_conv_speed: str,
    conv_speed_label: str | None,
    current_samp_speed: str,
    samp_speed_label: str | None,
    current_sample_rate: int,
    sample_rate_value: int | None,
    current_array_operation_mode: str,
    array_operation_mode: str | None,
    current_rb_ohms: float,
    rb_value: float | None,
    current_rk_ohms: float,
    rk_value: float | None,
    cf_farads: float,
    current_rxmax_ohms: float,
    rxmax_value: float | None,
) -> ADCConfigurationSnapshot:
    return ADCConfigurationSnapshot(
        reference=normalize_reference(
            current_reference=current_reference,
            vref_label=vref_label,
            use_vref_control=use_vref_control,
        ),
        osr=int(osr_label) if osr_label else int(current_osr),
        gain=normalize_gain(current_gain=current_gain, gain_label=gain_label),
        repeat=int(repeat_value if repeat_value is not None else current_repeat),
        use_ground=bool(current_use_ground if use_ground_checked is None else use_ground_checked),
        ground_pin=int(ground_pin_value if ground_pin_value is not None else current_ground_pin),
        conv_speed=str(conv_speed_label if conv_speed_label is not None else current_conv_speed),
        samp_speed=str(samp_speed_label if samp_speed_label is not None else current_samp_speed),
        sample_rate=int(sample_rate_value if sample_rate_value is not None else current_sample_rate),
        array_operation_mode=str(array_operation_mode if array_operation_mode is not None else current_array_operation_mode),
        rb_ohms=float(rb_value if rb_value is not None else current_rb_ohms),
        rk_ohms=float(rk_value if rk_value is not None else current_rk_ohms),
        cf_farads=float(cf_farads),
        rxmax_ohms=float(rxmax_value if rxmax_value is not None else current_rxmax_ohms),
    )
