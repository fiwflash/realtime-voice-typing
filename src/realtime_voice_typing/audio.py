"""Continuous microphone capture using sounddevice."""

import queue

import numpy as np


# Host APIs that reliably support capture through PortAudio/sounddevice on
# Windows. Windows WDM-KS is intentionally excluded: sounddevice cannot open it
# for callback capture ("Blocking API not supported yet" / WdmSyncIoctl errors).
_USABLE_HOSTAPIS = ("Windows WASAPI", "Windows DirectSound", "MME")

# When a microphone is exposed through several host APIs, prefer these in order.
_HOSTAPI_PREFERENCE = ("Windows WASAPI", "Windows DirectSound", "MME")


def _hostapi_rank(name: str) -> int:
    try:
        return _HOSTAPI_PREFERENCE.index(name)
    except ValueError:
        return len(_HOSTAPI_PREFERENCE)


def _is_usable_hostapi(name: str) -> bool:
    return any(known in name for known in _USABLE_HOSTAPIS)


def _log(message: str) -> None:
    try:
        from .paths import log_file

        with open(log_file(), "a", encoding="utf-8") as handle:
            handle.write(f"[audio] {message}\n")
    except Exception:
        pass


def _collect_input_devices(sd) -> list[dict]:
    """De-duplicated usable input devices, preferred host API per name."""
    hostapis = sd.query_hostapis()
    devices: dict[str, dict] = {}

    for index, info in enumerate(sd.query_devices()):
        if info.get("max_input_channels", 0) <= 0:
            continue

        hostapi_name = hostapis[info["hostapi"]]["name"]
        if not _is_usable_hostapi(hostapi_name):
            continue

        name = info["name"].strip()
        rank = _hostapi_rank(hostapi_name)
        existing = devices.get(name)
        if existing is None or rank < existing["_rank"]:
            devices[name] = {
                "index": index,
                "name": name,
                "hostapi": hostapi_name,
                "label": f"{name} [{hostapi_name}]",
                "_rank": rank,
            }

    result = []
    for device in devices.values():
        device.pop("_rank", None)
        result.append(device)
    return result


def list_input_devices() -> list[dict]:
    """Return usable input devices, one entry per physical microphone."""
    import sounddevice as sd

    return _collect_input_devices(sd)


def _devices_named(sd, name: str) -> list[int]:
    """Usable device indices whose name matches exactly, best host API first."""
    hostapis = sd.query_hostapis()
    matches = []
    for index, info in enumerate(sd.query_devices()):
        if info.get("max_input_channels", 0) <= 0:
            continue
        if str(info["name"]).strip() != name:
            continue
        hostapi_name = hostapis[info["hostapi"]]["name"]
        if not _is_usable_hostapi(hostapi_name):
            continue
        matches.append((_hostapi_rank(hostapi_name), index))
    matches.sort()
    return [index for _, index in matches]


class AudioCapture:
    """Captures mono float32 audio from a chosen (or the default) input device."""

    def __init__(
        self,
        sample_rate: int = 16000,
        device: int | None = None,
        device_name: str | None = None,
    ):
        self.sample_rate = sample_rate
        self.device = device
        self.device_name = device_name
        self.active_device = None
        self.active_device_name = None
        self._stream = None
        self._queue: queue.Queue = queue.Queue()

    def _callback(self, indata, frames, time_info, status):
        # indata is (frames, channels); keep only the first channel as contiguous mono.
        self._queue.put(np.ascontiguousarray(indata[:, 0], dtype="float32"))

    def start(self) -> None:
        import sounddevice as sd

        candidates = self._candidate_devices(sd)
        if not candidates:
            raise RuntimeError(
                "No usable microphone found. Connect a microphone and set it as the "
                "default input device."
            )

        _log(
            f"start capture desired_name={self.device_name!r} "
            f"desired_index={self.device!r} candidates={candidates}"
        )

        failures = []
        for device in candidates:
            try:
                self._open(sd, device)
                self.active_device = device
                self.active_device_name = self._device_name(sd, device)
                _log(f"opened input device {device}: {self.active_device_name}")
                return
            except Exception as exc:  # noqa: BLE001 - try the next usable device
                failures.append(f"{device}: {exc}")
                _log(f"device {device} failed: {exc}")
                self._close_quietly()

        raise RuntimeError("Could not open a microphone. Tried: " + " | ".join(failures))

    def _open(self, sd, device: int) -> None:
        kwargs = dict(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            device=device,
            callback=self._callback,
        )
        extra_settings = self._extra_settings(sd, device)
        if extra_settings is not None:
            kwargs["extra_settings"] = extra_settings
        self._queue = queue.Queue()
        stream = sd.InputStream(**kwargs)
        stream.start()
        self._stream = stream

    def _close_quietly(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

    @staticmethod
    def _device_name(sd, index: int) -> str:
        try:
            info = sd.query_devices(index)
            return str(info["name"]).strip()
        except Exception:
            return f"device {index}"

    @staticmethod
    def _is_usable_device(sd, index: int) -> bool:
        """True if the device index exists, has inputs, and uses a usable host API."""
        try:
            info = sd.query_devices(index)
        except Exception:
            return False
        if info.get("max_input_channels", 0) <= 0:
            return False
        try:
            hostapi_name = sd.query_hostapis(info["hostapi"])["name"]
        except Exception:
            return False
        return _is_usable_hostapi(hostapi_name)

    def _candidate_devices(self, sd) -> list[int]:
        """Ordered, de-duplicated list of devices worth trying.

        If a specific microphone name was chosen, only that physical device is
        used (across its host APIs) — never a different microphone — so the app
        cannot silently fall back to a silent device. Without a name, the saved
        index, the system default and finally every usable device are tried.
        """
        if self.device_name:
            named = _devices_named(sd, self.device_name)
            if named:
                return named

        devices = _collect_input_devices(sd)

        ordered: list[int] = []
        if (
            self.device is not None
            and self.device >= 0
            and self._is_usable_device(sd, self.device)
        ):
            ordered.append(self.device)
        default_input = sd.default.device[0]
        if (
            default_input is not None
            and default_input >= 0
            and self._is_usable_device(sd, default_input)
        ):
            ordered.append(default_input)
        ordered.extend(device["index"] for device in devices)

        seen = set()
        result = []
        for index in ordered:
            if index not in seen:
                seen.add(index)
                result.append(index)
        return result

    @staticmethod
    def _extra_settings(sd, device: int):
        """WASAPI needs auto-convert so a 16 kHz stream works on 48 kHz devices."""
        try:
            info = sd.query_devices(device)
            hostapi_name = sd.query_hostapis(info["hostapi"])["name"]
        except Exception:
            return None
        if "WASAPI" in hostapi_name:
            try:
                return sd.WasapiSettings(auto_convert=True)
            except Exception:
                return None
        return None

    def read(self, timeout: float | None = None) -> np.ndarray | None:
        """Return the next audio block, or None if nothing arrived within the timeout."""
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def stop(self) -> None:
        self._close_quietly()
