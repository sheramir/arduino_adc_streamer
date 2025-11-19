# Arduino ADC Streamer

Stream, display and save analog signals captured from Arduino board. This repository includes a comprehensive Python GUI application and Arduino sketch for high-speed ADC data acquisition and visualization.

## 🚀 Quick Start

1. **Upload Arduino Sketch**:
   - Open `ADC_Streamer XIAO MG24/ADC_Streamer XIAO MG24.ino`
   - Upload to your Arduino board

2. **Install Python Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Run the GUI**:
   ```bash
   python adc_gui.py
   ```

## 📁 Repository Contents

- **`adc_gui.py`**: Full-featured Python GUI application
- **`ADC_Streamer XIAO MG24/`**: Arduino sketch for ADC streaming
- **`requirements.txt`**: Python package dependencies
- **`GUI_README.md`**: Comprehensive GUI documentation

## ✨ Features

- 🔌 **Serial Communication**: Auto-detect and connect to Arduino
- ⚙️ **ADC Configuration**: Resolution (8-16 bits) and voltage reference control
- 📊 **Acquisition Control**: Multi-channel sequences, repeat averaging, timing control
- 📈 **Real-time Plotting**: Fast visualization with pyqtgraph
- 💾 **Data Export**: CSV data with metadata and plot images
- 🎨 **Interactive Visualization**: Channel selection and averaging modes

## 📖 Documentation

See **[GUI_README.md](GUI_README.md)** for detailed documentation including:
- Installation instructions
- Usage guide and workflows
- Troubleshooting tips
- Data format specifications
- Advanced features

## 🔧 Requirements

- Python 3.8+
- PyQt6, pyserial, pyqtgraph, numpy
- Arduino with compatible ADC (tested on XIAO MG24)

## 📊 Arduino Protocol

The Arduino sketch supports commands for:
- Channel configuration (`channels 0,1,2,3`)
- ADC settings (`res 12`, `ref 3.3`)
- Acquisition control (`repeat 20`, `delay 50`)
- Run modes (`run`, `run 1000`, `stop`)

Data is streamed as CSV lines: `value1,value2,...,valueN`

## 🤝 Contributing

Contributions welcome! Please open issues or pull requests.

## 📄 License

[Add your license here]
