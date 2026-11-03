"""Check fixed-source capture on an explicitly configured, isolated Pulse server."""
import json
import os
import struct
import subprocess
import threading
import time
from uuid import uuid4

from cicada_linux.pulse import CaptureError, record


def pactl(*args, **kwargs):
    return subprocess.run(['pactl', *args], capture_output=True, timeout=5, **kwargs)


def main():
    if not os.environ.get('PULSE_SERVER'):
        raise SystemExit('Set PULSE_SERVER to an isolated test server.')
    name = 'cicada_test_' + uuid4().hex[:8]
    modules = []
    stop = threading.Event()
    ready = threading.Event()
    errors = []
    thread = None

    def capture():
        try:
            for block in record(name + '.monitor', stop, 16000):
                if any(block):
                    ready.set()
        except Exception as error:
            errors.append(error)

    try:
        for sink in (name, name + '_other'):
            result = pactl('load-module', 'module-null-sink', 'sink_name=' + sink,
                           'rate=16000', 'channels=1', 'channel_map=mono', check=True)
            modules.append(result.stdout.decode().strip())
        thread = threading.Thread(target=capture, daemon=True)
        thread.start()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and thread.is_alive():
            outputs = json.loads(pactl('--format=json', 'list', 'source-outputs', check=True).stdout)
            if any(output.get('properties', {}).get('media.name') == 'Cicada playback capture'
                   for output in outputs):
                break
            time.sleep(.05)
        else:
            raise AssertionError(f'Capture stream did not start: {errors!r}')
        tone = (struct.pack('<h', 1500) * 8 + struct.pack('<h', -1500) * 8) * 1000
        subprocess.run(['paplay', '--raw', '--format=s16le', '--rate=16000', '--channels=1',
                        '--device=' + name], input=tone, check=True, timeout=8)
        if not ready.wait(5):
            raise AssertionError(f'Capture did not deliver audio: {errors!r}')

        pactl('unload-module', modules[0], check=True)
        modules.pop(0)
        thread.join(timeout=5)
        if thread.is_alive() or not errors or not isinstance(errors[0], CaptureError):
            raise AssertionError(f'Capture did not fail on source removal: {errors!r}')
        print(f'Selected monitor captured PCM and stopped on removal: {errors[0]}')
    finally:
        stop.set()
        if thread:
            thread.join(timeout=5)
        for module in modules:
            pactl('unload-module', module)


if __name__ == '__main__':
    main()
