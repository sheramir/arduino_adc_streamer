# Serial Communication

This folder contains all serial-port code for the Arduino ADC Streamer GUI: connecting to and disconnecting from the MCU's ADC stream and the optional force-sensor device, reading data on background threads so the Qt event loop never blocks, parsing ASCII status/ack lines and binary sample packets, and exposing GUI-facing mixins that the main window composes in. The ADC side (`adc_connection_state.py`, `adc_connection_workflow.py`, `adc_session.py`, `adc_serial.py`) and the force side (`force_connection_state.py`, `force_connection_workflow.py`, `force_session.py`, `force_serial.py`) follow a parallel structure: a session controller owns the `pyserial` port and reader thread, a workflow coordinates connect/disconnect sequencing, plain dataclasses describe view state for the GUI to render, and a mixin wires that machinery into the main window's widgets and callbacks. `serial_threads.py` defines the two `QThread` subclasses that actually read bytes off the wire — one decoding a binary block-packet protocol plus interleaved `#`-prefixed ASCII lines for the ADC, the other parsing CSV-like text lines for the force sensor — and `serial_parser.py` interprets the ADC's ASCII status output into an `ArduinoStatus` object. `__init__.py` re-exports the public classes and helpers so other modules can import from `serial_communication` directly.

## Files

### __init__.py

Package entry point; imports and re-exports all public classes, dataclasses, and builder functions from the other modules in this folder via `__all__`.

- No functions or classes of its own — pure re-export module.

### adc_connection_state.py

Defines plain dataclasses and builder functions describing ADC runtime status and the GUI view state for connected/disconnected states, with no I/O or Qt dependencies.

- `ADCConnectionViewState` — frozen dataclass holding connect-button text, widget enabled flags, style, and status message for the GUI to apply.
- `ArduinoStatus` — mutable dataclass holding the last-known Arduino configuration (channels, repeat, gain, reference, etc.).
  - `copy()` — returns a shallow dataclass copy via `dataclasses.replace`.
  - `apply(other)` — copies all fields from another `ArduinoStatus` into this instance in place.
- `LastSentConfig` — mutable dataclass tracking the last configuration values sent to the Arduino.
  - `copy()` — returns a shallow dataclass copy via `dataclasses.replace`.
- `build_default_last_sent_config()` — returns a fresh, empty `LastSentConfig`.
- `build_default_arduino_status()` — returns a fresh, empty `ArduinoStatus`.
- `build_connected_view_state()` — returns an `ADCConnectionViewState` representing the "connected, please configure" UI state.
- `build_disconnected_view_state()` — returns an `ADCConnectionViewState` representing the disconnected UI state.

### adc_connection_workflow.py

Coordinates the sequence of steps for connecting to and disconnecting from an ADC session, independent of any GUI widgets.

- `ADCConnectOutcome` — frozen dataclass result of a connect attempt: port name and detected MCU name.
- `ADCDisconnectOutcome` — frozen dataclass result of a disconnect attempt: list of warning strings.
- `ADCConnectionWorkflow` — coordinates ADC session connect/disconnect sequencing.
  - `connect(session, port_name, *, mcu_detection_timeout)` — opens the session's serial connection, runs MCU detection, and returns an `ADCConnectOutcome`.
  - `disconnect(session)` — disconnects the given session (or no-ops if `None`) and returns an `ADCDisconnectOutcome` with any warnings.

### adc_serial.py

Mixin class providing the GUI-facing ADC serial connect/disconnect/command methods used by the main window, delegating transport details to `ADCSessionController` and `ADCConnectionWorkflow`.

- `ADCSerialMixin` — mixin class for ADC serial communication methods.
  - `_apply_adc_connection_view_state(view_state)` — applies an `ADCConnectionViewState` to the relevant GUI widgets.
  - `_clear_adc_line_waiters()` — clears any pending line waiters on the active ADC session.
  - `_sync_adc_transport_state()` — mirrors the session-owned `serial_port`/`serial_thread` onto GUI attributes for legacy callers.
  - `_handle_adc_text_line(line)` — routes an incoming ADC text line to the session's waiters; returns whether it was consumed.
  - `_wait_for_adc_line(matcher, timeout, *, consume=False, send_action=None)` — delegates to the session's `wait_for_line`.
  - `_parse_ack_line(line)` — static method delegating to `ADCSessionController.parse_ack_line`.
  - `update_port_list()` — refreshes the ADC and force port combo boxes from `serial.tools.list_ports`.
  - `toggle_connection()` — connects or disconnects depending on current ADC serial port state.
  - `connect_serial()` — resolves the selected port, builds/uses the ADC session, runs the connect workflow, applies MCU state and view state, and updates the GUI for the detected MCU.
  - `_build_adc_session()` — constructs a new `ADCSessionController` wired to the GUI's data/error handlers.
  - `_handle_serial_reader_error(message)` — logs serial-thread errors and triggers a deferred disconnect if the message indicates a lost connection.
  - `disconnect_serial(*, cleanup_block=False)` — stops capture if running, runs the disconnect workflow, resets MCU/config state, and applies the disconnected view state.
  - `send_command(command)` — sends a raw command string through the active ADC session.
  - `drain_serial_input(duration=0.3)` — discards pending ADC bytes via the session without racing the reader thread.
  - `send_command_and_wait_ack(command, expected_value=None, timeout=CONFIG_COMMAND_TIMEOUT, max_retries=CONFIG_RETRY_ATTEMPTS)` — sends a command and waits for an `#OK`/`#NOT_OK` acknowledgment, returning `(success, received_value)`.

### adc_session.py

Owns the ADC serial port transport, reader-thread wiring, routed text-line waiting, and MCU detection/command-ack logic, independent of the GUI.

- `ADCSessionController` — controller for ADC serial-port transport and request/response waits.
  - `__init__(on_text_line, on_binary_sweep, on_error)` — stores callback hooks and initializes port/thread/waiter state.
  - `connect(port_name)` — opens the serial port, resets buffers, starts a `SerialReaderThread` connected to the callbacks.
  - `disconnect(*, thread_wait_ms=250)` — stops the reader thread and closes the port, collecting any warnings.
  - `clear_line_waiters()` — empties the list of pending line waiters.
  - `handle_text_line(line)` — routes an incoming line to matching waiters; returns whether a waiter consumed it.
  - `wait_for_line(matcher, timeout, *, consume=False, send_action=None)` — registers a waiter, optionally sends a command, and polls (processing Qt events) until the matcher fires or timeout.
  - `parse_ack_line(line)` — static method parsing `#OK`/`#NOT_OK` lines into `(success, value)` or `None`.
  - `send_command(command)` — writes a terminated command string to the serial port.
  - `send_command_and_wait_ack(command, expected_value, timeout, max_retries)` — sends a command and retries until an acknowledgment matching `expected_value` (if given) is received.
  - `drain_input(duration=0.3)` — sleeps briefly, clears the reader thread's buffer, and resets the port's input buffer.
  - `is_mcu_response_line(line)` — static method identifying a `#`-prefixed line as an MCU-name response (not an ack or status line).
  - `detect_mcu(timeout)` — sends the `mcu` command and waits for a matching response line, returning the detected MCU name.

### force_connection_state.py

Defines a plain dataclass and builder functions describing the force-sensor connection view state for the GUI.

- `ForceConnectionViewState` — frozen dataclass holding connect-button text and enabled flags for port selection and the reset button.
- `build_force_connected_view_state()` — returns a `ForceConnectionViewState` for the connected state.
- `build_force_disconnected_view_state()` — returns a `ForceConnectionViewState` for the disconnected state.

### force_connection_workflow.py

Coordinates connect/disconnect sequencing for the force-sensor session, independent of GUI widgets.

- `ForceConnectOutcome` — frozen dataclass result of a connect attempt: port name and whether calibration should start.
- `ForceDisconnectOutcome` — frozen dataclass result of a disconnect attempt: list of warning strings.
- `ForceConnectionWorkflow` — coordinates force session connect/disconnect sequencing.
  - `connect(session, port_name)` — connects the session and returns a `ForceConnectOutcome` (always requests calibration).
  - `disconnect(session)` — disconnects the given session (or no-ops if `None`) and returns a `ForceDisconnectOutcome` with any warnings.

### force_serial.py

Mixin class providing the GUI-facing force-sensor connect/disconnect/reset methods, delegating transport to `ForceSessionController` and `ForceConnectionWorkflow`.

- `ForceSerialMixin` — mixin class for force sensor serial communication methods.
  - `_apply_force_connection_view_state(view_state)` — applies a `ForceConnectionViewState` to the relevant GUI widgets.
  - `_sync_force_transport_state()` — mirrors the force session's `serial_port`/`serial_thread` onto GUI attributes.
  - `_build_force_session()` — constructs a new `ForceSessionController` wired to the GUI's data/error handlers.
  - `_warn_if_no_force_data_received()` — logs a warning if no force samples have arrived shortly after connecting.
  - `toggle_force_connection()` — connects or disconnects depending on current force serial port state.
  - `connect_force_serial()` — resolves the selected port, builds/uses the force session, runs the connect workflow, starts calibration, and updates the GUI (including channel list checkboxes).
  - `_handle_force_reader_error(message)` — logs force-reader errors and triggers a disconnect if the message indicates a lost connection.
  - `reset_force_load_cell()` — re-zeroes the load cell baseline from recently received raw samples.
  - `disconnect_force_serial()` — runs the disconnect workflow, resets force runtime state, and updates the GUI (including channel list checkboxes).

### force_session.py

Owns the force-sensor serial port transport and reader-thread wiring, independent of the GUI.

- `ForceSessionController` — controller for the force-sensor serial transport and reader thread.
  - `__init__(on_force_data, on_error)` — stores callback hooks and initializes port/thread state.
  - `connect(port_name)` — opens the serial port, waits for the sensor startup delay, resets the input buffer, and starts a `ForceReaderThread`; cleans up and re-raises on failure.
  - `disconnect(*, thread_wait_ms=FORCE_THREAD_STOP_TIMEOUT_MS)` — stops the reader thread and closes the port, collecting any warnings.

### serial_parser.py

Mixin class that interprets incoming ASCII serial lines from the Arduino into status fields and log messages.

- `SerialParserMixin` — mixin for parsing ASCII serial data.
  - `process_serial_data(line)` — routes a line to ADC line waiters first; otherwise logs `#`-prefixed status lines (parsing them when not an ack) or flags unexpected printable ASCII.
  - `parse_status_line(line)` — parses a single Arduino status line (channel list, `repeatCount`, `groundPin`, `useGroundBeforeEach`, `osr`, `gain`, `adcReference`/`reference`) into the GUI's `arduino_status` object, silently ignoring parse errors.

### serial_threads.py

Defines the two background `QThread` subclasses that read raw bytes from the ADC and force serial ports without blocking the GUI, including the binary block-packet decoder and the force-sensor CSV line parser.

- `parse_force_sensor_line(line)` — module function parsing a force-sensor line into `(x_force, z_force)` floats, supporting `x,z`, `timestamp,x,z`, and noisy/labeled variants via numeric-token extraction.
- `SerialReaderThread` — background thread reading ADC serial data without blocking the GUI; emits `data_received`, `binary_sweep_received`, and `error_occurred` Qt signals.
  - `__init__(serial_port)` — stores the port and initializes buffers/counters/state.
  - `run()` — main thread loop reading available bytes, feeding them to `process_binary_data`, and emitting an idle debug signal when no data has arrived.
  - `process_binary_data(buffer)` — parses the buffer for `0xAA 0x55`-headed binary block packets (validating sample count and timing sanity, emitting samples as a `numpy` uint16 array) interleaved with `#`-prefixed ASCII lines, trimming consumed bytes from the buffer.
  - `set_capturing(capturing, expected_samples_per_sweep=None)` — toggles capture mode, resets debug counters, and clears the binary buffer when capture stops.
  - `_maybe_emit_capture_idle_debug()` — emits a diagnostic `error_occurred` message if no data has been read for a while during capture.
  - `_is_packet_timing_sane(*, sample_count, avg_sample_time_us, block_start_us, block_end_us)` — validates a binary packet's timing fields against configured bounds before accepting it.
  - `clear_buffer()` — clears the internal binary buffer.
  - `stop()` — signals the thread loop to exit.
- `ForceReaderThread` — background thread reading force-sensor CSV data without blocking the GUI; emits `force_data_received` and `error_occurred` Qt signals.
  - `__init__(serial_port)` — stores the port and initializes debug counters.
  - `run()` — main thread loop reading lines, parsing them with `parse_force_sensor_line`, and emitting parsed samples or skip-warnings.
  - `stop()` — signals the thread loop to exit.
