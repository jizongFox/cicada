"""Portable session rules and ports. No desktop, OS audio or ML imports."""
from dataclasses import dataclass
from typing import Protocol, Generator
from uuid import uuid4
from datetime import datetime, timezone


@dataclass(frozen=True)
class Audio:
    pcm: bytes
    seconds: float
    rate: int = 16000


class Capture(Protocol):
    def chunks(self, stop) -> Generator[Audio, None, None]: ...


class ASR(Protocol):
    def transcribe(self, audio: Audio) -> str: ...


class Intelligence(Protocol):
    def translate(self, text: str, target: str) -> str: ...
    def notes(self, lines: list[dict], target: str) -> str: ...


def now():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def session():
    return dict(id=uuid4().hex, title='Meeting ' + now(), startedAt=now(),
                endedAt=None, lines=[], hasAudio=False, notes=None)


def line(audio, text, translated, source, target):
    return dict(id=uuid4().hex, t=audio.seconds, speaker='them', src=text,
                dst=translated, srcLang=source, dstLang=target)


def markdown(meeting):
    rows = [f"# {meeting['title']}", '', meeting.get('notesText', ''), '']
    for item in meeting['lines']:
        rows += [f"[{item['t']:.1f}s] {item['src']}", item.get('dst') or '', '']
    return '\n'.join(rows)
