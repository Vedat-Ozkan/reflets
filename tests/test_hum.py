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
    result = hum.transcribe(sung(47, 60 / 90, 0.19, 20), 60 / 90, 2, 0.19, 0, 32)
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


def test_a_bar_hummed_again_keeps_the_key_of_the_take_before():
    beat = 60 / 90
    audio = sung(48, beat, 0.19, 20)
    whole = hum.transcribe(audio, beat, 2, 0.19, 0, 32)
    bar = audio[int(4 * beat * hum.RATE):int((8 * beat + 0.5) * hum.RATE)]
    assert hum.transcribe(bar, beat, 2, 0.19, 0, 8).key.name != "C major"
    again = hum.transcribe(bar, beat, 2, 0.19, 0, 8, known=whole.key)
    assert again.key.name == "C major" and [n.pitch for n in again.notes] == [57, 57, 55]


def test_clicks_and_room_noise_give_no_notes():
    from reflets import audio

    clicks, _ = audio.click_track(60 / 90, 4, 20)
    room = 0.003 * np.random.default_rng(2).standard_normal(len(clicks)).astype(np.float32)
    result = hum.transcribe(0.3 * clicks + room, 60 / 90, 2, 0.19, 0, 32)
    assert result is None or not result.notes


def test_synthesised_melodies_keep_their_floor_with_the_delay_measured_or_searched():
    from eval.hum_synth import singers, totals

    paths = [("measured", 0, 0), ("searched, or as given", hum.DELAY_RANGE, 1)]
    for by_kind in totals(singers(4), paths):
        t = by_kind["all"]
        assert t["placed"] / t["notes"] > 0.87 and t["whole"] / t["notes"] > 0.73 and t["outside placed"] >= 100
        assert by_kind["rhythm"]["placed"] / by_kind["rhythm"]["notes"] > 0.86
