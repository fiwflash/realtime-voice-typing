# Third-party notices

This project builds on open-source libraries and speech models. The MIT license
in [LICENSE](LICENSE) covers the source code of this repository only. Model
weights and third-party libraries remain under their own licenses.

The converted Thai model folders (`models/th-distill`, `models/th-pathumma`) are
**not** redistributed in this repository because of their size. The information
below is provided so users can obtain them from their original publishers and
follow the corresponding terms.

## Speech models

| Model | Publisher | License | Source |
|---|---|---|---|
| Whisper (`small`, `medium`, `large-v3`, `turbo`) | OpenAI | MIT | https://github.com/openai/whisper |
| Distill Whisper Thai Large V3 (`th-distill`) | Biomedical and Data Lab, Mahidol University (BiodatLab) | MIT | https://huggingface.co/biodatlab/distill-whisper-th-large-v3 |
| Pathumma Whisper Large V3 (TH) (`th-pathumma`) | NECTEC | Apache-2.0 | https://huggingface.co/nectec/Pathumma-whisper-th-large-v3 |

`biodatlab/distill-whisper-th-large-v3` is a Thai fine-tune/distillation of
OpenAI Whisper Large V3 Turbo. `nectec/Pathumma-whisper-th-large-v3` is a Thai +
English fine-tune of OpenAI Whisper Large V3. This project is not affiliated
with, or endorsed by, OpenAI, BiodatLab, or NECTEC.

## Python libraries

| Library | License |
|---|---|
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | MIT |
| [CTranslate2](https://github.com/OpenNMT/CTranslate2) | MIT |
| [sounddevice](https://github.com/spatialaudio/python-sounddevice) | MIT |
| [soundfile](https://github.com/bastibe/python-soundfile) | BSD-3-Clause |
| [NumPy](https://numpy.org/) | BSD-3-Clause |
| [Pillow](https://python-pillow.org/) | HPND |
| [keyboard](https://github.com/boppreh/keyboard) | MIT |
| [pyperclip](https://github.com/asweigart/pyperclip) | BSD-3-Clause |
| [NVIDIA CUDA runtime wheels](https://pypi.org/project/nvidia-cublas-cu12/) | NVIDIA CUDA Toolkit EULA |

## Attribution and AI assistance

The application code and the icon artwork in `assets/` were produced for this
project with heavy AI assistance and manual testing. If you reuse the code,
keep the MIT notice. If you redistribute a converted model, include the original
model license and attribution from the table above.
