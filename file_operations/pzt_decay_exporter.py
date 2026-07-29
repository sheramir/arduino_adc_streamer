"""Human-readable export files for a PZT decay-characterization run."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict
from pathlib import Path

from data_processing.pzt_decay import PztDecayResult, PztDecaySample


SAMPLE_COLUMNS = (
    "SampleIndex", "BurstIndex", "RepeatIndex", "TimestampBasis", "TimingValid", "Timestamp", "RelativeTime_s", "Voltage_V", "Vmid_V",
    "DeltaFromVmid_V", "NormalizedAmplitude", "WallDeltaT_s",
    "ConnectedDecayDeltaT_s", "DisconnectedDecayDeltaT_s", "CumulativeWallTime_s",
    "CumulativeConnectedTime_s", "CumulativeDisconnectedTime_s", "CalculatedVoltage_V",
    "State", "FitIncluded", "RejectionReason",
)


class PztDecayExporter:
    """Write one run using a collision-resistant timestamp and result ID."""

    PRE_TREND_CONTEXT_SAMPLES = 10
    POST_FIT_CONTEXT_SAMPLES = 10

    def export(self, directory: str | Path, result: PztDecayResult, samples: list[PztDecaySample], *, write_summary: bool = True) -> dict[str, Path]:
        output_dir = Path(directory)
        output_dir.mkdir(parents=True, exist_ok=True)
        stem = f"pzt_decay_{result.logical_signal}_{result.created_at.strftime('%Y%m%d_%H%M%S_%f')}_{result.result_id[:8]}"
        sample_path = output_dir / f"{stem}_samples.csv"
        result_path = output_dir / f"{stem}_result.json"
        summary_path = output_dir / f"{stem}_summary.csv"
        self.write_samples_csv(sample_path, result, samples)
        payload = result.export_dict()
        payload["files"] = {"samples_csv": str(sample_path), "summary_csv": str(summary_path) if write_summary else None}
        result_path.write_text(json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8")
        if write_summary:
            self.write_summary_csv(summary_path, result, sample_path, result_path)
        return {"samples_csv": sample_path, "result_json": result_path, **({"summary_csv": summary_path} if write_summary else {})}

    @staticmethod
    def select_samples_for_csv(samples: list[PztDecaySample]) -> list[PztDecaySample]:
        """Keep the final decay evidence, without long target-wait recordings.

        The CSV is intended for inspecting the regression rather than for
        replaying the complete acquisition.  It therefore retains every
        final-trend point outside the normalized fit window, every fit-window
        point (including robust-fit outliers), the last ten pre-trend points,
        and ten chronological points after the fit window.  Samples captured
        while waiting for the target are deliberately omitted.
        """
        before_final = [
            index for index, sample in enumerate(samples)
            if sample.rejection_reason in {
                "before final descending decay trend",  # v1.0 results
                "before final selected decay event",    # event-scoped v1.1 results
            }
        ]
        outside_window = [
            index for index, sample in enumerate(samples)
            if sample.rejection_reason == "outside normalized fit window"
        ]
        in_window = [
            index for index, sample in enumerate(samples)
            if sample.fit_included
            or sample.rejection_reason == "robust connected-exposure fit outlier"
        ]
        selected = set(before_final[-PztDecayExporter.PRE_TREND_CONTEXT_SAMPLES:])
        selected.update(outside_window)
        selected.update(in_window)
        if in_window:
            last_fit_index = max(in_window)
            selected.update(range(
                last_fit_index + 1,
                min(last_fit_index + 1 + PztDecayExporter.POST_FIT_CONTEXT_SAMPLES, len(samples)),
            ))
        return [sample for index, sample in enumerate(samples) if index in selected]

    @staticmethod
    def write_samples_csv(path: str | Path, result: PztDecayResult, samples: list[PztDecaySample]) -> None:
        with Path(path).open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=SAMPLE_COLUMNS)
            writer.writeheader()
            for sample in PztDecayExporter.select_samples_for_csv(samples):
                writer.writerow({
                    "SampleIndex": sample.sample_index, "BurstIndex": sample.burst_index,
                    "RepeatIndex": sample.repeat_index, "TimestampBasis": sample.timestamp_basis,
                    "TimingValid": sample.timing_valid, "Timestamp": sample.timestamp_s,
                    "RelativeTime_s": sample.relative_time_s, "Voltage_V": sample.voltage_v,
                    "Vmid_V": result.vmid_v, "DeltaFromVmid_V": sample.delta_from_vmid_v,
                    "NormalizedAmplitude": sample.normalized_amplitude, "WallDeltaT_s": sample.wall_dt_s,
                    "ConnectedDecayDeltaT_s": sample.connected_decay_dt_s,
                    "DisconnectedDecayDeltaT_s": sample.disconnected_decay_dt_s,
                    "CumulativeWallTime_s": sample.cumulative_wall_time_s,
                    "CumulativeConnectedTime_s": sample.cumulative_connected_time_s,
                    "CumulativeDisconnectedTime_s": sample.cumulative_disconnected_time_s,
                    "CalculatedVoltage_V": sample.calculated_voltage_v, "State": sample.measurement_state,
                    "FitIncluded": sample.fit_included, "RejectionReason": sample.rejection_reason or "",
                })

    @staticmethod
    def write_summary_csv(path: str | Path, result: PztDecayResult, samples_path: Path, result_path: Path) -> None:
        fields = (
            "ResultID", "Timestamp", "Signal", "MUX", "MUXAddress", "MUXPin", "ADCInput", "Vmid_V",
            "TargetVoltage_V", "PlateauVoltage_V", "InitialAmplitude_V", "Samples", "FitSamples",
            "MeanWallDeltaT_s", "ConnectedDeltaT_s", "PreSampleDecay_s", "PostSampleConnected_s",
            "AlphaWithinBurst", "AlphaBurstBoundary", "AlphaFullMuxSelection", "TauWall_s", "TauOnEstimated_s", "Resistance_Ohm", "Capacitance_F", "R2",
            "RMSE_V", "QualityStatus", "Warnings", "SamplesCSV", "ResultJSON",
        )
        row = {
            "ResultID": result.result_id, "Timestamp": result.created_at.isoformat(), "Signal": result.logical_signal,
            "MUX": result.mapping.mux_number, "MUXAddress": result.mapping.mux_address, "MUXPin": result.mapping.mux_pin_label,
            "ADCInput": result.mapping.physical_adc_input, "Vmid_V": result.vmid_v, "TargetVoltage_V": result.target_voltage_v,
            "PlateauVoltage_V": result.plateau_voltage_v, "InitialAmplitude_V": result.initial_amplitude_v,
            "Samples": result.total_samples, "FitSamples": result.fit_samples,
            "MeanWallDeltaT_s": result.timing.mean_wall_sample_interval_s,
            "ConnectedDeltaT_s": result.timing.sensor_connected_s, "PreSampleDecay_s": result.timing.pre_sample_decay_s,
            "PostSampleConnected_s": result.timing.post_sample_connected_s,
            "AlphaWithinBurst": result.alpha_within_burst,
            "AlphaBurstBoundary": result.alpha_burst_boundary,
            "AlphaFullMuxSelection": result.alpha_full_mux_selection,
            "TauWall_s": result.tau_wall_s, "TauOnEstimated_s": result.tau_on_estimated_s,
            "Resistance_Ohm": result.connected_equivalent_resistance_ohm, "Capacitance_F": result.capacitance_estimated_f,
            "R2": result.r_squared, "RMSE_V": result.rmse_voltage_v, "QualityStatus": result.quality_status,
            "Warnings": "; ".join(result.warnings), "SamplesCSV": str(samples_path), "ResultJSON": str(result_path),
        }
        with Path(path).open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader(); writer.writerow(row)
