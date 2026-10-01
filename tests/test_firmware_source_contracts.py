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


def test_7953_project_contract_has_requested_pins_identity_and_order():
    sketch = SKETCHES / "TestBoard_7953"
    config = (sketch / "include" / "ConfigurableParameters.h").read_text(encoding="utf-8")
    platformio = (sketch / "platformio.ini").read_text(encoding="utf-8")
    firmware = _tree_text(sketch)

    assert (sketch / "platformio.ini").is_file()
    assert (sketch / "src" / "main.cpp").is_file()
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

    assert 'kMcuName[] = "TestBoard_7953"' in config
    assert "platform = teensy@6.0.0" in platformio
    for command in (
        "adcchannels",
        "scanorder",
        "array",
        "vmid",
        "adcseq",
        "spiengine",
        "spiclock",
        "channelrepeat",
    ):
        assert command in firmware
    pzt_controller = (sketch / "src" / "PztController.cpp").read_text(encoding="utf-8")
    assert 'command == "repeat"' not in pzt_controller
    assert 'command == "buffer"' not in pzt_controller
    assert "buffer_sweeps_" not in pzt_controller
    assert "channel_repeat_" in pzt_controller
    assert "spi_clock_hz_" in pzt_controller
    assert "kDefaultSpiClockHz = 20000000" in config
    assert "kAdcBiasResistorOhms[kAdcCount]" in config
    assert "1000000UL, 470000UL, 470000UL, 249000UL" in config
    assert "kMinSpiClockHz = 100000" in config
    assert "kMaxSpiClockHz = 30000000" in config
    for scan_order in ("SCAN_INTERLEAVED", "SCAN_ARRAY", "SCAN_ADC"):
        assert scan_order in firmware
    for engine in ("SPI_ENGINE_BLOCKING", "SPI_ENGINE_DMA", "SPI_ENGINE_LPSPI"):
        assert engine in firmware
    for sequence in ("ADC_SEQUENCE_MANUAL", "ADC_SEQUENCE_AUTO1"):
        assert sequence in firmware
    assert "parkActiveAdcs()" in firmware
    assert "buildParkStream" in firmware
    assert "kDefaultVmidChannel = 15" in config
    assert "channel == testboard_config::kDefaultVmidChannel" in pzt_controller
    assert 'command == "vmidchannel"' not in pzt_controller
    assert 'command == "vmidsample"' not in pzt_controller
    assert "startDma16" in firmware
    assert "startLpspi16" in firmware
    assert "EventResponder" in firmware
    assert "kAuto1Program = 0x8000" in firmware
    assert "kAuto1Mode = 0x2000" in firmware
    assert "auto1_programmed_masks_" in firmware
    assert "auto1_mask_valid_" in firmware
    assert "auto1_active_parked_" in firmware
    assert 'F("# auto1_program_count=")' in pzt_controller
    assert 'F("# auto1_resume_count=")' in pzt_controller
    assert "stream.auto_wait_for_vmid = true" in pzt_controller
    assert "stream.auto_finished_parked = true" in pzt_controller
    assert "1u << testboard_config::kDefaultVmidChannel" in pzt_controller
    assert "auto1ProgramCommand()) ||" in pzt_controller
    assert "g_samples[ready.destination] = sample" in pzt_controller
    assert "g_samples[destination] = stream.adc->returnedSample(response)" in pzt_controller
    assert "Do not flush binary traffic" in firmware
    assert "kBlockMagic1 = 0xAA" in firmware
    assert "kBlockMagic2 = 0x55" in firmware
    assert "class AdcDevice" in firmware
    assert "class Ads7953Adc" in firmware
