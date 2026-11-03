import array
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from cicada_linux.core import Audio
from cicada_linux.pipewire import Segmenter
from cicada_linux.providers import CloudASR
from cicada_linux.storage import Store
from cicada_linux.workflow import Meeting


class PipelineTests(unittest.TestCase):
    def test_segmentation_preserves_continuous_audio_and_timestamps(self):
        segmenter = Segmenter()
        pcm = array.array('h', [1000] * 1600).tobytes()
        out = [a for _ in range(90) if (a := segmenter.feed(pcm))]
        out.append(segmenter.flush())
        self.assertEqual(b''.join(a.pcm for a in out), pcm * 90)
        self.assertEqual([a.seconds for a in out], [0, 8])

    def test_translation_failure_retains_original_and_finalizes(self):
        class Capture:
            def chunks(self, stop):
                yield Audio(b'\0\0' * 1600, 2)
        class Recognizer:
            def transcribe(self, audio):
                return 'a decision'
        class Service:
            def translate(self, *args):
                raise RuntimeError('secret provider body')
            def notes(self, *args):
                return 'Summary'
        with tempfile.TemporaryDirectory() as root:
            store = Store(root)
            meeting = Meeting(Capture(), Recognizer(), Service(), store)
            warnings = []
            meeting.run(threading.Event(), lambda s: None, warnings.append)
            saved = store.history()[0]
            self.assertEqual(saved['lines'][0]['src'], 'a decision')
            self.assertIsNone(saved['lines'][0]['dst'])
            self.assertIsNotNone(saved['endedAt'])
            self.assertEqual(saved['notesText'], 'Summary')
            self.assertNotIn('secret', str(warnings))
            path = next(Path(root).glob('Sessions/*/session.json'))
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_capture_failure_still_saves_partial_session(self):
        class Capture:
            def chunks(self, stop):
                yield Audio(b'\0\0', 0)
                raise RuntimeError('disconnected')
        class ASR:
            def transcribe(self, audio):
                return 'saved'
        with tempfile.TemporaryDirectory() as root:
            store = Store(root)
            meeting = Meeting(Capture(), ASR(), None, store)
            with self.assertRaises(RuntimeError):
                meeting.run(threading.Event(), lambda s: None, lambda s: None)
            self.assertEqual(store.history()[0]['lines'][0]['src'], 'saved')
            self.assertIsNotNone(store.history()[0]['endedAt'])

    def test_cloud_multipart_contains_valid_wav_and_language(self):
        calls = []
        def request(url, key, body, content_type):
            calls.append((url, key, body, content_type))
            return {'text': ' hello '}
        with patch('cicada_linux.providers.request', request):
            text = CloudASR('https://example.test/v1/', 'secret', 'whisper-1', 'en').transcribe(Audio(b'\0\0' * 100, 0))
        self.assertEqual(text, 'hello')
        url, key, body, content_type = calls[0]
        self.assertTrue(url.endswith('/v1/audio/transcriptions'))
        self.assertIn(b'RIFF', body)
        self.assertIn(b'name="language"\r\n\r\nen', body)
        self.assertIn('boundary=', content_type)


if __name__ == '__main__':
    unittest.main()
