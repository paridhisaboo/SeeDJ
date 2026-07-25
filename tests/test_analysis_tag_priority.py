"""
Tests the tag-search/priority/merge logic in analysis.py using mock tag
objects shaped exactly like pyrekordbox's real tag classes (verified by
reading pyrekordbox/anlz/tags.py directly — see that file's TAGS registry
and each class's .get() implementation).

This does NOT test pyrekordbox's own binary parsing (that's pyrekordbox's
tested responsibility, not ours) — it tests OUR logic: which tag we prefer
when multiple are present, how we merge tags found across sibling DAT/EXT
files, and that we handle a tag's .get() raising cleanly.
"""
import numpy as np

from app.rekordbox.analysis import _extract_beat_grid, _extract_waveform


class _FakeTag:
    """Mimics AbstractAnlzTag's public surface: .type and .get()."""

    def __init__(self, tag_type: str, get_return):
        self.type = tag_type
        self._get_return = get_return

    def get(self):
        if isinstance(self._get_return, Exception):
            raise self._get_return
        return self._get_return


def _beat_grid_return(n: int, bpm: float = 128.0):
    # Real shape confirmed from PQTZAnlzTag.get() / PQT2AnlzTag.get():
    # a (beats, bpms, times) tuple of numpy arrays.
    beats = np.array([(i % 4) + 1 for i in range(n)], dtype=np.int8)
    bpms = np.full(n, bpm, dtype=np.float64)
    times = np.array([i * (60.0 / bpm) for i in range(n)], dtype=np.float64)
    return beats, bpms, times


def test_beat_grid_prefers_pqt2_over_pqtz_when_both_present():
    tags = [
        _FakeTag("PQTZ", _beat_grid_return(4, bpm=120.0)),
        _FakeTag("PQT2", _beat_grid_return(4, bpm=128.0)),
    ]
    points, used = _extract_beat_grid(tags)

    assert used == "PQT2"
    assert points[0].bpm == 128.0


def test_beat_grid_falls_back_to_pqtz_when_pqt2_absent():
    tags = [_FakeTag("PQTZ", _beat_grid_return(4, bpm=120.0))]
    points, used = _extract_beat_grid(tags)

    assert used == "PQTZ"
    assert len(points) == 4
    assert points[0].beat_number == 1
    assert points[1].beat_number == 2


def test_beat_grid_returns_empty_when_no_grid_tag_present():
    tags = [_FakeTag("PPTH", "/some/path.mp3")]
    points, used = _extract_beat_grid(tags)

    assert points == []
    assert used is None


def test_beat_grid_skips_tag_that_raises_and_does_not_crash():
    tags = [
        _FakeTag("PQT2", RuntimeError("corrupt struct")),
        _FakeTag("PQTZ", _beat_grid_return(2, bpm=140.0)),
    ]
    points, used = _extract_beat_grid(tags)

    # Falls through to PQTZ since PQT2's .get() blew up.
    assert used == "PQTZ"
    assert len(points) == 2


def test_waveform_prefers_richest_available_tag():
    tags = [
        _FakeTag("PWAV", (np.zeros(10), np.zeros(10))),
        _FakeTag("PWV3", (np.zeros(50), np.zeros(50))),
        _FakeTag("PWV5", (np.zeros(200), np.zeros((200, 3)))),
    ]
    tag_used, data = _extract_waveform(tags)

    assert tag_used == "PWV5"
    heights, colors = data
    assert len(heights) == 200


def test_waveform_falls_back_to_basic_preview_when_thats_all_there_is():
    tags = [_FakeTag("PWAV", (np.zeros(10, dtype=np.int8), np.zeros(10, dtype=np.int8)))]
    tag_used, data = _extract_waveform(tags)

    assert tag_used == "PWAV"
    assert data is not None


def test_waveform_returns_none_when_no_waveform_tag_present():
    tags = [_FakeTag("PQTZ", _beat_grid_return(4))]
    tag_used, data = _extract_waveform(tags)

    assert tag_used is None
    assert data is None