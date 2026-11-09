from pathlib import Path
import zipfile

from realtime_voice_typing import cuda_pack, model_manager
from realtime_voice_typing.settings import get_model_spec


def test_catalog_entries_match_spec_table():
    for entry in model_manager.MODEL_CATALOG:
        spec = get_model_spec(entry.key)
        assert spec is not None
        assert spec.label == entry.label
        assert entry.repo_id
        assert entry.size_gb > 0


def test_get_entry_accepts_key_and_path():
    assert model_manager.get_entry("turbo").key == "turbo"
    assert model_manager.get_entry(str(Path("somewhere") / "th-pathumma")).key == "th-pathumma"
    assert model_manager.get_entry("unknown-model") is None


def test_install_detection_and_resolution(tmp_path, monkeypatch):
    monkeypatch.setenv("RVT_DATA_DIR", str(tmp_path))
    entry = model_manager.MODEL_BY_KEY["small"]

    assert not model_manager.is_installed(entry)
    assert model_manager.resolve_model("small") == "small"

    folder = tmp_path / "models" / "small"
    folder.mkdir(parents=True)
    (folder / "model.bin").write_bytes(b"not-a-real-model")

    assert model_manager.is_installed(entry)
    assert model_manager.resolve_model("small") == str(folder)
    assert model_manager.installed_entries() == [entry]


def test_cuda_pack_detection_and_size(tmp_path, monkeypatch):
    monkeypatch.setenv("RVT_DATA_DIR", str(tmp_path))
    assert not cuda_pack.is_installed()

    cuda = tmp_path / "cuda"
    cuda.mkdir()
    for name in cuda_pack._REQUIRED_DLLS:
        (cuda / name).write_bytes(b"x" * (1024 * 1024))

    assert cuda_pack.is_installed()
    assert cuda_pack.installed_size_mb() > 0


def test_cuda_pack_install_from_zip(tmp_path, monkeypatch):
    monkeypatch.setenv("RVT_DATA_DIR", str(tmp_path))
    archive = tmp_path / "pack.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for name in cuda_pack._REQUIRED_DLLS:
            zf.writestr(f"bin/{name}", b"dll")

    cuda_pack.install_from_zip(archive)

    assert cuda_pack.is_installed()
    for name in cuda_pack._REQUIRED_DLLS:
        assert (tmp_path / "cuda" / name).is_file()
