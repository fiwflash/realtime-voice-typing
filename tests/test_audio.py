import sys
import types

import pytest

from realtime_voice_typing.audio import AudioCapture, list_input_devices


@pytest.fixture(autouse=True)
def _silence_audio_log(monkeypatch):
    monkeypatch.setattr("realtime_voice_typing.audio._log", lambda message: None)


class FakeStream:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def start(self):
        pass

    def stop(self):
        pass

    def close(self):
        pass


class FakeSoundDevice:
    def __init__(self):
        self.default = types.SimpleNamespace(device=[0, 9])
        self.stream_kwargs = None
        self._hostapis = [
            {"name": "MME"},
            {"name": "Windows WDM-KS"},
            {"name": "Windows WASAPI"},
        ]
        self._devices = [
            {"name": "Mic A", "max_input_channels": 1, "hostapi": 0},
            {"name": "Speakers", "max_input_channels": 0, "hostapi": 0},
            {"name": "Mic A", "max_input_channels": 1, "hostapi": 2},
            {"name": "Mic B", "max_input_channels": 1, "hostapi": 1},
            {"name": "Mic C", "max_input_channels": 1, "hostapi": 2},
            {"name": "Mic C", "max_input_channels": 1, "hostapi": 0},
        ]

    def query_devices(self, device=None, kind=None):
        if device is None:
            return self._devices
        return self._devices[device]

    def query_hostapis(self, index=None):
        if index is None:
            return self._hostapis
        return self._hostapis[index]

    def WasapiSettings(self, auto_convert=False):
        return types.SimpleNamespace(auto_convert=auto_convert)

    def InputStream(self, **kwargs):
        if kwargs.get("device") in getattr(self, "fail_devices", ()):
            raise RuntimeError("simulated stream failure")
        self.stream_kwargs = kwargs
        return FakeStream(**kwargs)


def test_list_input_devices_excludes_wdm_ks_and_dedupes(monkeypatch):
    fake = FakeSoundDevice()
    monkeypatch.setitem(sys.modules, "sounddevice", fake)

    devices = list_input_devices()

    assert [device["name"] for device in devices] == ["Mic A", "Mic C"]
    assert all(device["hostapi"] == "Windows WASAPI" for device in devices)
    assert devices[0]["index"] == 2
    assert devices[1]["index"] == 4


def test_capture_uses_wasapi_auto_convert(monkeypatch):
    fake = FakeSoundDevice()
    monkeypatch.setitem(sys.modules, "sounddevice", fake)

    capture = AudioCapture(16000, device=2)
    capture.start()

    assert fake.stream_kwargs["device"] == 2
    assert fake.stream_kwargs["samplerate"] == 16000
    assert fake.stream_kwargs["extra_settings"].auto_convert is True


def test_capture_on_mme_has_no_extra_settings(monkeypatch):
    fake = FakeSoundDevice()
    monkeypatch.setitem(sys.modules, "sounddevice", fake)

    capture = AudioCapture(16000, device=0)
    capture.start()

    assert fake.stream_kwargs["device"] == 0
    assert "extra_settings" not in fake.stream_kwargs


def test_capture_ignores_unusable_wdm_ks_index(monkeypatch):
    fake = FakeSoundDevice()
    monkeypatch.setitem(sys.modules, "sounddevice", fake)

    # Mic B (index 3) is WDM-KS only and cannot be opened; fall back to default.
    capture = AudioCapture(16000, device=3)
    capture.start()

    assert fake.stream_kwargs["device"] == 0


def test_capture_resolves_by_name_over_stale_index(monkeypatch):
    fake = FakeSoundDevice()
    monkeypatch.setitem(sys.modules, "sounddevice", fake)

    # Stale index would pick the wrong device, but the saved name wins.
    capture = AudioCapture(16000, device=3, device_name="Mic A")
    capture.start()

    assert fake.stream_kwargs["device"] == 2
    assert fake.stream_kwargs["extra_settings"].auto_convert is True


def test_capture_falls_through_when_first_device_fails(monkeypatch):
    fake = FakeSoundDevice()
    fake.fail_devices = {2}
    monkeypatch.setitem(sys.modules, "sounddevice", fake)

    capture = AudioCapture(16000, device=2)
    capture.start()

    # Device 2 (Mic A WASAPI) failed to open; it must try the next usable device.
    assert fake.stream_kwargs["device"] == 0
    assert capture.active_device == 0


def test_capture_does_not_switch_to_other_mic_when_named_device_fails(monkeypatch):
    fake = FakeSoundDevice()
    fake.fail_devices = {0, 2}  # both host-API variants of "Mic A" fail
    monkeypatch.setitem(sys.modules, "sounddevice", fake)

    capture = AudioCapture(16000, device=2, device_name="Mic A")

    with pytest.raises(RuntimeError):
        capture.start()

    # Must not silently record from a different microphone ("Mic C" index 4).
    assert capture.active_device is None


def test_capture_falls_back_when_named_device_missing(monkeypatch):
    fake = FakeSoundDevice()
    monkeypatch.setitem(sys.modules, "sounddevice", fake)

    capture = AudioCapture(16000, device=None, device_name="Nonexistent Mic")
    capture.start()

    assert fake.stream_kwargs["device"] == 0
