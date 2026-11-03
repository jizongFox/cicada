"""One session owner. Capture/provider/storage implementations are injected."""
from contextlib import closing
import time
import queue
import threading
from .core import session, line, now


class Meeting:
    def __init__(self, capture, asr, intelligence, store, source='auto', target='Chinese'):
        self.capture, self.asr, self.intelligence, self.store = capture, asr, intelligence, store
        self.source, self.target = source, target
        self.value = session()

    def audio_stream(self, stop):
        # Read continuously while inference or HTTP is busy; bounded memory.
        inbox = queue.Queue(maxsize=32)
        failure = []
        def produce():
            try:
                with closing(self.capture.chunks(stop)) as capture:
                    for audio in capture:
                        try:
                            inbox.put_nowait(audio)
                        except queue.Full:
                            raise RuntimeError('Recognition cannot keep up with capture. Session stopped.') from None
            except Exception as error:
                failure.append(error)
                stop.set()
        thread = threading.Thread(target=produce, daemon=True)
        thread.start()
        try:
            while thread.is_alive() or not inbox.empty():
                try:
                    yield inbox.get(timeout=.2)
                except queue.Empty:
                    if stop.is_set():
                        # Allow the recorder to deliver its final fragment, then
                        # bound waiting even if an adapter ignores Stop.
                        thread.join(timeout=5)
                        if thread.is_alive() and inbox.empty():
                            raise RuntimeError('Audio capture did not stop.')
            if failure:
                raise failure[0]
        finally:
            stop.set()
            thread.join(timeout=5)
            if thread.is_alive():
                raise RuntimeError('Audio capture did not stop.')

    def run(self, stop, changed, warning):
        last_notes = time.monotonic()
        self.store.save(self.value)
        stream = self.audio_stream(stop)
        try:
            for audio in stream:
                text = self.asr.transcribe(audio)
                if not text:
                    continue
                item = line(audio, text, None, self.source, self.target)
                self.value['lines'].append(item)
                self.store.save(self.value)
                changed(self.value)
                if self.intelligence:
                    try:
                        item['dst'] = self.intelligence.translate(text, self.target)
                    except Exception:
                        warning('Translation failed; original speech was saved. Check the text provider settings.')
                    if time.monotonic() - last_notes >= 45:
                        self.update_notes(warning)
                        last_notes = time.monotonic()
                    self.store.save(self.value)
                    changed(self.value)
            if self.intelligence and self.value['lines']:
                self.update_notes(warning)
        finally:
            try:
                stream.close()
            finally:
                self.value['endedAt'] = now()
                self.store.save(self.value)
                changed(self.value)

    def update_notes(self, warning):
        try:
            self.value['notesText'] = self.intelligence.notes(self.value['lines'], self.target)
        except Exception:
            warning('Notes failed; previous notes and transcript are retained.')
