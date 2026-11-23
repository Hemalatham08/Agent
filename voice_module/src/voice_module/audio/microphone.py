"""Microphone device detection and selection."""

import logging
from dataclasses import dataclass
from typing import List, Optional

import sounddevice as sd

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MicrophoneInfo:
    """Information about a microphone input device."""
    index: int
    name: str
    max_input_channels: int
    default_sample_rate: float
    hostapi: str


class MicrophoneError(Exception):
    """Error related to microphone operations."""
    def __init__(self, code: str, message: str, details: str = None):
        self.code = code
        self.message = message
        self.details = details
        super().__init__(f"[{code}] {message}")


def list_microphones() -> List[MicrophoneInfo]:
    """
    List all available microphone input devices.

    Returns:
        List of MicrophoneInfo for each input-capable device.

    Raises:
        MicrophoneError: If PortAudio initialization fails.
    """
    try:
        devices = sd.query_devices()
        hostapis = sd.query_hostapis()
    except Exception as e:
        logger.exception("Failed to query audio devices")
        raise MicrophoneError(
            code="DEVICE_QUERY_FAILED",
            message="Failed to query audio devices",
            details=str(e)
        )

    microphones = []
    for idx, device in enumerate(devices):
        if device.get("max_input_channels", 0) > 0:
            hostapi_idx = device.get("hostapi", 0)
            hostapi_name = hostapis[hostapi_idx]["name"] if hostapi_idx < len(hostapis) else "Unknown"

            info = MicrophoneInfo(
                index=idx,
                name=device.get("name", f"Device {idx}"),
                max_input_channels=device.get("max_input_channels", 1),
                default_sample_rate=device.get("default_samplerate", 44100.0),
                hostapi=hostapi_name
            )
            microphones.append(info)

    return microphones


def get_default_microphone() -> Optional[MicrophoneInfo]:
    """
    Get the default microphone input device.

    Returns:
        MicrophoneInfo for default device, or None if no input device available.
    """
    try:
        default_idx = sd.default.device[0]  # (input, output)
        if default_idx == -1:
            return None

        devices = sd.query_devices()
        device = devices[default_idx]
        if device.get("max_input_channels", 0) == 0:
            return None

        hostapis = sd.query_hostapis()
        hostapi_idx = device.get("hostapi", 0)
        hostapi_name = hostapis[hostapi_idx]["name"] if hostapi_idx < len(hostapis) else "Unknown"

        return MicrophoneInfo(
            index=default_idx,
            name=device.get("name", f"Device {default_idx}"),
            max_input_channels=device.get("max_input_channels", 1),
            default_sample_rate=device.get("default_samplerate", 44100.0),
            hostapi=hostapi_name
        )
    except Exception:
        return None


def validate_device(device_index: int) -> bool:
    """
    Validate that a device index exists and supports input.

    Args:
        device_index: Device index to validate.

    Returns:
        True if valid input device, False otherwise.
    """
    try:
        devices = sd.query_devices()
        if device_index < 0 or device_index >= len(devices):
            return False
        device = devices[device_index]
        return device.get("max_input_channels", 0) > 0
    except Exception:
        return False


def get_device_info(device_index: int) -> Optional[MicrophoneInfo]:
    """
    Get detailed info for a specific device index.

    Args:
        device_index: Device index to query.

    Returns:
        MicrophoneInfo if valid, None otherwise.
    """
    if not validate_device(device_index):
        return None

    try:
        devices = sd.query_devices()
        device = devices[device_index]
        hostapis = sd.query_hostapis()
        hostapi_idx = device.get("hostapi", 0)
        hostapi_name = hostapis[hostapi_idx]["name"] if hostapi_idx < len(hostapis) else "Unknown"

        return MicrophoneInfo(
            index=device_index,
            name=device.get("name", f"Device {device_index}"),
            max_input_channels=device.get("max_input_channels", 1),
            default_sample_rate=device.get("default_samplerate", 44100.0),
            hostapi=hostapi_name
        )
    except Exception:
        return None