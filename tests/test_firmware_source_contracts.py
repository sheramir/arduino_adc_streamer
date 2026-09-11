from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SKETCHES = REPO_ROOT / "Arduino_Sketches"


def _tree_text(path: Path) -> str:
    return "\n".join(
        file.read_text(encoding="utf-8")
        for file in sorted(path.rglob("*"))
        if file.suffix in {".ino", ".h", ".cpp"}
    )


def test_pcb17_modular_sources_use_arduino_compilable_src_layout():
    modular = SKETCHES / "PCB1.7_with_libraries"
    for board in (modular / "Teensy", modular / "MG24"):
        assert (board / f"{board.name}.ino").is_file()
        assert (board / "src").is_dir()
        assert not (board / "libraries").exists()
        assert list((board / "src").glob("*.cpp"))


def test_pcb17_modular_teensy_preserves_host_protocol_surface():
    monolithic = (SKETCHES / "PCB1.7_SPI" / "Teensy_SPI_Master_Array_PZT_PZR1.7_DRDY.ino").read_text(
        encoding="utf-8"
    )
    modular = _tree_text(SKETCHES / "PCB1.7_with_libraries" / "Teensy")
    for literal in (
        "# Array_PZT_PZR1.7",
        "#OK",
        "#NOT_OK",
        "0xAA",
        "0x55",
        '"mode"',
        '"channels"',
        '"pztmuxes"',
        '"rschannels"',
        '"repeat"',
        '"buffer"',
        '"run"',
        '"stop"',
        '"status"',
        '"mcu"',
    ):
        assert literal in monolithic
        assert literal in modular


def test_pcb17_modular_mg24_preserves_transport_constants():
    monolithic = (SKETCHES / "PCB1.7_SPI" / "MG24_Dual_MUX_SPI_Slave1.7_DRDY.ino").read_text(
        encoding="utf-8"
    )
    modular = _tree_text(SKETCHES / "PCB1.7_with_libraries" / "MG24")
    for literal in ("0xAA", "0x55", "20", "0x0D", "0x0C", "0x0B"):
        assert literal in monolithic
        assert literal in modular


def test_7953_sketch_contract_has_requested_pins_identity_and_order():
    sketch = SKETCHES / "PCB_TestBoard_7953"
    config = (sketch / "ConfigurableParameters.h").read_text(encoding="utf-8")
    firmware = _tree_text(sketch)

    assert (sketch / "PCB_TestBoard_7953.ino").is_file()
    assert (sketch / "src").is_dir()
    for name, value in {
        "kSpi1MisoPin": 12,
        "kSpi1MosiPin": 11,
        "kSpi1SckPin": 13,
        "kAdc1CsPin": 9,
        "kAdc2CsPin": 24,
        "kSpi2MisoPin": 39,
        "kSpi2MosiPin": 26,
        "kSpi2SckPin": 27,
        "kAdc3CsPin": 32,
        "kAdc4CsPin": 33,
    }.items():
        assert f"{name} = {value}" in config

    assert 'kMcuName[] = "PCB_TestBoard_7953"' in config
    assert "channel -> repeat -> ADC1,ADC2,ADC3,ADC4" in firmware
    assert "kBlockMagic1 = 0xAA" in firmware
    assert "kBlockMagic2 = 0x55" in firmware
    assert "class AdcDevice" in firmware
    assert "class Ads7953Adc" in firmware
