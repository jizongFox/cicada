"""PipeWire's PulseAudio compatibility interface. Owns capture and segmentation."""
import array
import json
import math
import selectors
import subprocess
import sys
from .core import Audio


def monitors():
    result = subprocess.run(['pactl', '--format=json', 'list', 'sources'],
                            capture_output=True, text=True, check=True, timeout=10)
    return [(s['name'], s.get('description', s['name']))
            for s in json.loads(result.stdout) if s['name'].endswith('.monitor')]


class Segmenter:
    """Energy gate: end after 600 ms quiet or 8 seconds. Retain every PCM byte."""
    def __init__(self, rate=16000):
        self.rate, self.position, self.start = rate, 0, 0
        self.buffer = bytearray()
        self.quiet = 0
        self.voice = False

    def feed(self, pcm):
        samples = array.array('h', pcm)
        if sys.byteorder != 'little':
            samples.byteswap()
        rms = math.sqrt(sum(s*s for s in samples) / max(1, len(samples)))
        if not self.buffer:
            self.start = self.position
        self.buffer.extend(pcm)
        self.position += len(samples)
        if rms > 180:
            self.voice, self.quiet = True, 0
        else:
            self.quiet += len(samples)
        if self.quiet >= self.rate * .6 or len(self.buffer) >= self.rate * 2 * 8:
            return self.flush()

    def flush(self):
        audio = Audio(bytes(self.buffer), self.start / self.rate, self.rate) if self.voice else None
        self.buffer.clear()
        self.quiet, self.voice = 0, False
        return audio


class PipeWireCapture:
    def __init__(self, source):
        self.source = source

    def chunks(self, stop):
        segmenter = Segmenter()
        proc = subprocess.Popen(['parec', '--device=' + self.source, '--format=s16le',
                                 '--rate=16000', '--channels=1', '--latency-msec=100'],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        pending = b''
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(proc.stdout, selectors.EVENT_READ)
                while not stop.is_set():
                    if not selector.select(.2):
                        if proc.poll() is not None:
                            raise RuntimeError('Audio capture stopped; check the selected monitor.')
                        continue
                    block = proc.stdout.read1(3200)
                    if not block:
                        raise RuntimeError('Audio capture disconnected.')
                    pending += block
                    while len(pending) >= 3200:
                        block, pending = pending[:3200], pending[3200:]
                        audio = segmenter.feed(block)
                        if audio:
                            yield audio
                if pending:
                    audio = segmenter.feed(pending[:len(pending)//2*2])
                    if audio:
                        yield audio
                audio = segmenter.flush()
                if audio:
                    yield audio
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            proc.stdout.close()
