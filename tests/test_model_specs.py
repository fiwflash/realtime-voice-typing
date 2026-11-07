from realtime_voice_typing.gui import evaluate_model_fit
from realtime_voice_typing.settings import MODEL_CHOICES, get_model_spec


def test_every_model_choice_has_spec_metadata():
    for _, value in MODEL_CHOICES:
        spec = get_model_spec(value)
        assert spec is not None
        assert spec.vram_gb
        assert spec.recommended_spec


def test_evaluate_model_fit_warns_when_cpu_only_for_large_model():
    cpu_machine = {"cuda_ready": False, "vram_gb": None, "gpu_name": None}
    text, color = evaluate_model_fit("large-v3", cpu_machine)
    assert "CPU" in text
    assert color == "#b45309"


def test_evaluate_model_fit_marks_8gb_gpu_ready_for_pathumma():
    gpu_machine = {"cuda_ready": True, "vram_gb": 8.0, "gpu_name": "RTX 4060"}
    text, color = evaluate_model_fit("th-pathumma", gpu_machine)
    assert "RTX 4060" in text
    assert color == "#15803d"
