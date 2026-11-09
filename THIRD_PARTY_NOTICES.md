# Third-party notices

This project builds on open-source libraries and speech models. The MIT license
in [LICENSE](LICENSE) covers the source code of this repository only. Model
weights and third-party libraries remain under their own licenses.

The converted Thai model folders are **not** redistributed in this repository.
The in-app model manager downloads public CTranslate2 conversions from Hugging
Face on demand. The information below is provided so users can follow the
corresponding terms.

## Speech models

| Model | Publisher | License | Source |
|---|---|---|---|
| Whisper (`small`, `medium`, `large-v3`) | OpenAI / Systran conversion | MIT | https://huggingface.co/Systran/faster-whisper-large-v3 |
| Whisper Large V3 Turbo (`turbo`) | OpenAI / Mobius Labs conversion | MIT | https://huggingface.co/mobiuslabsgmbh/faster-whisper-large-v3-turbo |
| Distill Whisper Thai Large V3 (`th-distill`) | Biomedical and Data Lab, Mahidol University (BiodatLab); CT2 conversion by Vinxscribe | MIT | https://huggingface.co/Vinxscribe/biodatlab-whisper-th-large-v3-faster |
| Pathumma Whisper Large V3 (TH) (`th-pathumma`) | NECTEC; CT2 conversion by PogusTheWhisper | Apache-2.0 (original model) | https://huggingface.co/PogusTheWhisper/Faster-Pathumma-whisper-th-large-v3-ct2 |

`biodatlab/distill-whisper-th-large-v3` is a Thai fine-tune/distillation of
OpenAI Whisper Large V3 Turbo. `nectec/Pathumma-whisper-th-large-v3` is a Thai +
English fine-tune of OpenAI Whisper Large V3. This project is not affiliated
with, or endorsed by, OpenAI, BiodatLab, NECTEC, or the conversion authors.

## Python libraries

| Library | License |
|---|---|
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | MIT |
| [CTranslate2](https://github.com/OpenNMT/CTranslate2) | MIT |
| [huggingface_hub](https://github.com/huggingface/huggingface_hub) | Apache-2.0 |
| [sounddevice](https://github.com/spatialaudio/python-sounddevice) | MIT |
| [PyAV](https://github.com/PyAV-Org/PyAV) | BSD-3-Clause |
| [onnxruntime](https://github.com/microsoft/onnxruntime) | MIT |
| [NumPy](https://numpy.org/) | BSD-3-Clause |
| [Pillow](https://python-pillow.org/) | HPND |
| [pyperclip](https://github.com/asweigart/pyperclip) | BSD-3-Clause |
| [PyInstaller](https://pyinstaller.org/) | GPL-2.0 with bootloader exception |
| [Inno Setup](https://jrsoftware.org/isinfo.php) | Inno Setup License (installer only) |
| [NVIDIA CUDA runtime wheels](https://pypi.org/project/nvidia-cublas-cu12/) | NVIDIA CUDA Toolkit EULA |

## Attribution and AI assistance

The application code and the icon artwork in `assets/` were produced for this
project with heavy AI assistance and manual testing. If you reuse the code,
keep the MIT notice. If you redistribute a converted model, include the original
model license and attribution from the table above.
