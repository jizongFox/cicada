"""Playback monitor discovery and audio segmentation."""
import array
from contextlib import closing
import json
import math
import subprocess
import sys

from .core import Audio
from .pulse import CaptureError, record


def monitors():
    result = subprocess.run(['pactl', '--format=json', 'list', 'sources'],
                            capture_output=True, text=True, check=True, timeout=10)
    return [(s['name'], s.get('description', s['name']))
            for s in json.loads(result.stdout) if s['name'].endswith('.monitor')]


def rms(pcm):
    samples = array.array('h', pcm)
    if sys.byteorder != 'little':
        samples.byteswap()
    return math.sqrt(sum(s*s for s in samples) / len(samples)) if samples else 0


class Segmenter:
    """Use relative energy to place boundaries. Discard only digital silence."""
    def __init__(self, rate=16000):
        self.rate, self.start = rate, 0
        self.buffer = bytearray()
        self.quiet = self.pause_end = 0
        self.peak = 0

    def feed(self, pcm):
        if not pcm:
            return None
        frames = len(pcm) // 2
        energy = rms(pcm)
        self.peak = max(energy, self.peak * math.exp(-frames / (self.rate * .3)))
        self.buffer.extend(pcm)
        if energy <= self.peak * .05:
            self.quiet += frames
            if self.quiet >= self.rate * .12:
                self.pause_end = len(self.buffer)
        else:
            self.quiet = 0
        if self.quiet >= self.rate * .6:
            return self.flush()
        if len(self.buffer) >= self.rate * 16:
            # Prefer a recent pause to cutting a word at the eight-second limit.
            if self.pause_end >= len(self.buffer) - self.rate * 3:
                return self.take(self.pause_end)
            return self.flush()
        return None

    def take(self, size):
        pcm = bytes(self.buffer[:size])
        del self.buffer[:size]
        start = self.start / self.rate
        self.start += size // 2
        self.quiet = self.pause_end = 0
        self.peak = rms(self.buffer)
        return Audio(pcm, start, self.rate) if any(pcm) else None

    def flush(self):
        return self.take(len(self.buffer))


class PipeWireCapture:
    def __init__(self, source):
        self.source = source

    def chunks(self, stop):
        segmenter = Segmenter()
        frame_bytes = segmenter.rate // 50 * 2
        pending = bytearray()
        failure = None
        try:
            with closing(record(self.source, stop, segmenter.rate)) as blocks:
                for block in blocks:
                    pending.extend(block)
                    for offset in range(0, len(pending) - frame_bytes + 1, frame_bytes):
                        audio = segmenter.feed(pending[offset:offset + frame_bytes])
                        if audio:
                            yield audio
                    del pending[:len(pending) // frame_bytes * frame_bytes]
        except CaptureError as error:
            failure = error

        # Bytes already accepted from the selected source remain valid after a
        # disconnect. Emit them before surfacing the capture failure.
        if pending:
            audio = segmenter.feed(pending[:len(pending) // 2 * 2])
            if audio:
                yield audio
        audio = segmenter.flush()
        if audio:
            yield audio
        if failure:
            raise failure
