"""Tests for microphone device detection (mocked)."""

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest
from voice_module.audio import (
    list_microphones,
    get_default_microphone,
    validate_device,
    get_device_info,
    MicrophoneInfo,
    MicrophoneError,
)


def make_mock_device(index, name, max_input_channels, default_samplerate, hostapi=0):
    """Create a mock device dict matching sounddevice API."""
    return {
        "index": index,
        "name": name,
        "hostapi": hostapi,
        "max_input_channels": max_input_channels,
        "max_output_channels": 0,
        "default_low_input_latency": 0.01,
        "default_low_output_latency": 0.01,
        "default_high_input_latency": 0.1,
        "default_high_output_latency": 0.1,
        "default_samplerate": default_samplerate,
    }


def make_mock_hostapi(name):
    """Create a mock hostapi dict matching sounddevice API."""
    return {
        "name": name,
        "devices": [],
        "default_input_device": -1,
        "default_output_device": -1,
    }


def test_list_microphones_returns_input_devices():
    """Test that list_microphones returns only input-capable devices."""
    mock_devices = [
        make_mock_device(0, "Built-in Mic", 2, 44100.0),
        make_mock_device(1, "Headset Mic", 1, 48000.0),
        make_mock_device(2, "Speakers", 0, 44100.0),  # No input
        make_mock_device(3, "USB Mic", 1, 16000.0),
    ]
    mock_hostapis = (make_mock_hostapi("MME"), make_mock_hostapi("Windows DirectSound"))

    with patch("sounddevice.query_devices", return_value=mock_devices):
        with patch("sounddevice.query_hostapis", return_value=mock_hostapis):
            mics = list_microphones()

    assert len(mics) == 3
    assert all(isinstance(m, MicrophoneInfo) for m in mics)
    assert mics[0].index == 0
    assert mics[0].name == "Built-in Mic"
    assert mics[0].max_input_channels == 2
    assert mics[2].index == 3
    assert mics[2].name == "USB Mic"


def test_list_microphones_empty_when_no_input_devices():
    """Test empty list when no input devices available."""
    mock_devices = [
        make_mock_device(0, "Speakers", 0, 44100.0),
        make_mock_device(1, "Headphones", 0, 48000.0),
    ]
    mock_hostapis = (make_mock_hostapi("MME"),)

    with patch("sounddevice.query_devices", return_value=mock_devices):
        with patch("sounddevice.query_hostapis", return_value=mock_hostapis):
            mics = list_microphones()

    assert mics == []


def test_list_microphones_raises_on_portaudio_error():
    """Test MicrophoneError raised on PortAudio failure."""
    with patch("sounddevice.query_devices", side_effect=RuntimeError("PortAudio init failed")):
        with pytest.raises(MicrophoneError) as exc:
            list_microphones()
    assert exc.value.code == "DEVICE_QUERY_FAILED"


def test_get_default_microphone_returns_first_input():
    """Test get_default_microphone returns default input device."""
    mock_devices = [
        make_mock_device(0, "Built-in Mic", 2, 44100.0),
        make_mock_device(1, "Headset Mic", 1, 48000.0),
    ]
    mock_hostapis = (make_mock_hostapi("MME"),)

    with patch("sounddevice.default.device", (0, -1)):
        with patch("sounddevice.query_devices", return_value=mock_devices):
            with patch("sounddevice.query_hostapis", return_value=mock_hostapis):
                default = get_default_microphone()

    assert default is not None
    assert default.index == 0
    assert default.name == "Built-in Mic"


def test_get_default_microphone_none_when_no_default():
    """Test get_default_microphone returns None when no default input."""
    mock_devices = [make_mock_device(0, "Speakers", 0, 44100.0)]
    mock_hostapis = (make_mock_hostapi("MME"),)

    with patch("sounddevice.default.device", (-1, -1)):
        with patch("sounddevice.query_devices", return_value=mock_devices):
            with patch("sounddevice.query_hostapis", return_value=mock_hostapis):
                default = get_default_microphone()

    assert default is None


def test_validate_device_true_for_valid_input():
    """Test validate_device returns True for valid input device."""
    mock_devices = [make_mock_device(0, "Mic", 1, 44100.0)]

    with patch("sounddevice.query_devices", return_value=mock_devices):
        assert validate_device(0) is True
        assert validate_device(1) is False
        assert validate_device(-1) is False


def test_get_device_info_returns_info_for_valid():
    """Test get_device_info returns MicrophoneInfo for valid device."""
    mock_devices = [make_mock_device(0, "USB Mic", 1, 16000.0, hostapi=0)]
    mock_hostapis = (make_mock_hostapi("MME"),)

    with patch("sounddevice.query_devices", return_value=mock_devices):
        with patch("sounddevice.query_hostapis", return_value=mock_hostapis):
            info = get_device_info(0)

    assert info is not None
    assert info.index == 0
    assert info.name == "USB Mic"
    assert info.max_input_channels == 1
    assert info.default_sample_rate == 16000.0


def test_get_device_info_none_for_invalid():
    """Test get_device_info returns None for invalid device."""
    mock_devices = [make_mock_device(0, "Speakers", 0, 44100.0)]

    with patch("sounddevice.query_devices", return_value=mock_devices):
        assert get_device_info(0) is None
        assert get_device_info(999) is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])