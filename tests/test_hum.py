import numpy as np
import pytest

hum = pytest.importorskip("reflets.hum")

TWINKLE = [(0, 1, 0), (1, 1, 0), (2, 1, 7), (3, 1, 7), (4, 1, 9), (5, 1, 9), (6, 2, 7),
           (8, 1, 5), (9, 1, 5), (10, 1, 4), (11, 1, 4), (12, 1, 2), (13, 1, 2), (14, 2, 0)]


def sung(tonic: int, beat: float, latency: float, cents: float) -> np.ndarray:
    rng = np.random.default_rng(1)
    audio = np.zeros(int((16 * beat + 1) * hum.RATE), np.float32)
    for start, beats, degree in TWINKLE:
        length = beats * beat * 0.85
        t = np.arange(int(length * hum.RATE)) / hum.RATE
        scoop = -0.4 * np.exp(-t / 0.03)
        midi = tonic + degree + cents / 100 + scoop + 0.15 * np.sin(2 * np.pi * 5.5 * t)
        phase = 2 * np.pi * np.cumsum(440 * 2 ** ((midi - 69) / 12)) / hum.RATE
        voice = sum(np.sin(k * phase) / k for k in range(1, 6))
        envelope = np.minimum(1, t / 0.02) * np.minimum(1, (length - t) / 0.05)
        at = int((start * beat + latency) * hum.RATE)
        audio[at:at + len(t)] += (0.2 * voice * envelope).astype(np.float32)
    return audio + 0.003 * rng.standard_normal(len(audio)).astype(np.float32)


def test_twinkle_in_b_major_sung_sharp_with_latency():
    result = hum.transcribe(sung(47, 60 / 90, 0.19, 20), 60 / 90, 2, 0.19, 32)
    assert result.key.name == "B major"
    lines = hum.voice_lines(result.notes, [8] * 4, 24, result.key.fifths)
    assert lines == [
        "48 B2 48 B2 48 F#3 48 F#3",
        "48 G#3 48 G#3 96 F#3",
        "48 E3 48 E3 48 D#3 48 D#3",
        "48 C#3 48 C#3 96 B2",
    ]


def test_note_across_a_bar_line_is_tied():
    notes = [hum.Placed(6, 4, 60)]
    assert hum.voice_lines(notes, [8, 8], 24, 0) == ["144 r 48 C4~", "48 C4"]



def test_clicks_and_room_noise_give_no_notes():
    from reflets import audio

    clicks, _ = audio.click_track(60 / 90, 4, 20)
    room = 0.003 * np.random.default_rng(2).standard_normal(len(clicks)).astype(np.float32)
    result = hum.transcribe(0.3 * clicks + room, 60 / 90, 2, 0.19, 32)
    assert result is None or not result.notes
