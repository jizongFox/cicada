import json
from pathlib import Path
import struct
import tempfile
import threading
import unittest
from unittest.mock import patch

from cicada_linux.core import session
from cicada_linux.pipewire import CaptureError, PipeWireCapture, Segmenter
from cicada_linux.providers import ProviderError, request
from cicada_linux.storage import Store


def segment(frames):
    segmenter = Segmenter()
    segments = [audio for frame in frames if (audio := segmenter.feed(frame))]
    if audio := segmenter.flush():
        segments.append(audio)
    return segments


class AudioTests(unittest.TestCase):
    def test_quiet_signal_retained_and_forced_cut_prefers_pause(self):
        quiet_speech = struct.pack('<h', 32) * 320
        silence = bytes(640)
        # The old absolute gate discarded this entire signal. The short pause
        # gives the eight-second window a boundary before the next utterance.
        frames = [quiet_speech] * 350 + [silence] * 10 + [quiet_speech] * 90
        segments = segment(frames)
        self.assertEqual(b''.join(audio.pcm for audio in segments), b''.join(frames))
        self.assertEqual([audio.seconds for audio in segments], [0, 7.2])
        self.assertEqual(segment([silence] * 75), [])

    def test_disconnect_emits_accepted_tail_before_error(self):
        pcm = struct.pack('<h', 32) * 840

        def record(*args):
            yield pcm
            raise CaptureError('disconnected')

        with patch('cicada_linux.pipewire.record', record):
            capture = PipeWireCapture('test.monitor').chunks(threading.Event())
            self.assertEqual(next(capture).pcm, pcm)
            with self.assertRaisesRegex(CaptureError, 'disconnected'):
                next(capture)


class StorageTests(unittest.TestCase):
    def test_history_skips_invalid_records_and_preserves_valid_sessions(self):
        with tempfile.TemporaryDirectory() as root:
            store = Store(Path(root) / 'cicada')
            saved = session()
            saved['title'] = '会议'
            store.save(saved)
            for idx, value in enumerate((None, [], {'startedAt': 'x'}, {**saved, 'lines': [{'t': 'bad'}]})):
                folder = store.root / 'Sessions' / str(idx)
                folder.mkdir()
                (folder / 'session.json').write_text(json.dumps(value), encoding='utf-8')
            self.assertEqual(store.history(), [saved])
            for directory in (store.root, store.root / 'Sessions', store.root / 'Sessions' / saved['id']):
                self.assertEqual(directory.stat().st_mode & 0o777, 0o700)


class EndpointTests(unittest.TestCase):
    def test_rejects_remote_http_disguised_as_loopback(self):
        with patch('urllib.request.build_opener') as opener:
            with self.assertRaises(ProviderError):
                request('http://localhost:80@remote.invalid/v1', 'dummy', b'{}', 'application/json')
        opener.assert_not_called()
