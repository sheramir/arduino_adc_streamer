"""Registered acquisition interpretation around the existing mixin algorithms."""
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AcquisitionAdapter:
    id: str
    multi_array: bool = False
    combined: bool = False

    def descriptor(self, context, settings, layout, reported=None):
        if not self.multi_array:
            raise ValueError(f'{self.id} uses channel specs rather than an array descriptor')
        from config.testboard_acquisition import build_descriptor
        return build_descriptor(context.reported_mcu, settings, layout, reported, context)

    def channel_specs(self, owner):
        specs = list(owner.get_acquisition_channel_specs())
        if self.combined and hasattr(owner, 'get_rosette_display_channel_specs'):
            specs.extend(owner.get_rosette_display_channel_specs())
        return specs


ACQUISITION_ADAPTERS = {
    'channels': AcquisitionAdapter('channels'),
    'array_mux': AcquisitionAdapter('array_mux'),
    'array_combined': AcquisitionAdapter('array_combined', combined=True),
    'multi_array': AcquisitionAdapter('multi_array', multi_array=True),
}


def acquisition_adapter(context):
    return ACQUISITION_ADAPTERS[context.mode.definition['adapters']['acquisition']]
