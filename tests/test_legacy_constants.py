import ast
from pathlib import Path


LEGACY_CONSTANTS = Path("Legacy/config_constants.py")

LEGACY_VISUALIZATION_CONSTANTS = {
    "HEATMAP_WIDTH",
    "HEATMAP_HEIGHT",
    "SENSOR_POS_X",
    "SENSOR_POS_Y",
    "SENSOR_CALIBRATION",
    "SENSOR_NOISE_FLOOR",
    "SENSOR_SIZE",
    "INTENSITY_SCALE",
    "COP_EPS",
    "BLOB_SIGMA_X",
    "BLOB_SIGMA_Y",
    "SMOOTH_ALPHA",
    "HEATMAP_THRESHOLD",
    "CONFIDENCE_INTENSITY_REF",
    "SIGMA_SPREAD_FACTOR",
    "AXIS_SIGMA_FACTOR",
    "RMS_WINDOW_MS",
    "BIAS_CALIBRATION_DURATION_SEC",
    "HPF_CUTOFF_HZ",
    "HEATMAP_DC_REMOVAL_MODE",
    "HEATMAP_CHANNEL_SENSOR_MAP",
    "HEATMAP_REQUIRED_CHANNELS",
    "MAX_SENSOR_PACKAGES",
    "R_HEATMAP_CHANNEL_SENSOR_MAP",
    "R_HEATMAP_REQUIRED_CHANNELS",
    "R_HEATMAP_SENSOR_POS_X",
    "R_HEATMAP_SENSOR_POS_Y",
    "R_HEATMAP_DELTA_THRESHOLD",
    "R_HEATMAP_DELTA_RELEASE_THRESHOLD",
    "R_HEATMAP_INTENSITY_MIN",
    "R_HEATMAP_INTENSITY_MAX",
    "R_HEATMAP_AXIS_ADAPT_STRENGTH",
    "R_HEATMAP_MAP_SMOOTH_ALPHA",
    "R_HEATMAP_COP_SMOOTH_ALPHA",
    "SHEAR_INTEGRATION_WINDOW_MS",
    "SHEAR_BASELINE_ALPHA",
    "SHEAR_CONDITIONING_ALPHA",
    "SHEAR_DEADBAND_THRESHOLD",
    "SHEAR_CHANNEL_GAINS",
    "SHEAR_CHANNEL_BASELINES",
    "SHEAR_GAUSSIAN_SIGMA_X",
    "SHEAR_GAUSSIAN_SIGMA_Y",
    "SHEAR_INTENSITY_SCALE",
    "SHEAR_ARROW_SCALE",
    "SHEAR_ARROW_HEAD_LENGTH_BASE_PX",
    "SHEAR_ARROW_HEAD_LENGTH_AMPLIFIER",
    "SHEAR_ARROW_THICKNESS_AMPLIFIER",
    "SHEAR_CONFIDENCE_SIGNAL_REF",
    "SHEAR_VIEW_EXTENT",
    "SHEAR_SENSOR_RADIUS",
}

ARCHIVED_VISUALIZATION_MODULES = [
    Path("Legacy/data_processing/heatmap_555_processor.py"),
    Path("Legacy/data_processing/heatmap_piezo_processor.py"),
    Path("Legacy/data_processing/heatmap_processor.py"),
    Path("Legacy/data_processing/shear_processor.py"),
    Path("Legacy/gui/heatmap_panel.py"),
    Path("Legacy/gui/shear_panel.py"),
]


def _assigned_uppercase_names(path: Path) -> set[str]:
    module = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in module.body:
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        for target in targets:
            if isinstance(target, ast.Name) and target.id.isupper():
                names.add(target.id)
    return names


def test_legacy_visualization_constants_live_in_legacy_config():
    legacy_names = _assigned_uppercase_names(LEGACY_CONSTANTS)

    assert LEGACY_VISUALIZATION_CONSTANTS <= legacy_names


def test_archived_visualization_modules_import_legacy_constants():
    for path in ARCHIVED_VISUALIZATION_MODULES:
        module = ast.parse(path.read_text(encoding="utf-8"))
        imports = [
            node
            for node in module.body
            if isinstance(node, ast.ImportFrom)
        ]
        assert any(node.module == "Legacy.config_constants" for node in imports), path
        assert all(node.module != "config_constants" for node in imports), path
