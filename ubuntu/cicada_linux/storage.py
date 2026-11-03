"""Linux persistence: atomic JSON snapshots; credentials never enter sessions."""
import json
import os
from pathlib import Path
import sys
from tempfile import NamedTemporaryFile


def data_root():
    return Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share')) / 'cicada'


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = None
    try:
        with NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            os.chmod(temporary, 0o600)
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


class Store:
    def __init__(self, root=None):
        self.root = Path(root) if root else data_root()

    def save(self, meeting):
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        sessions = self.root / 'Sessions'
        sessions.mkdir(exist_ok=True, mode=0o700)
        write_json(sessions / meeting['id'] / 'session.json', meeting)

    def history(self):
        meetings = []
        for path in (self.root / 'Sessions').glob('*/session.json'):
            try:
                meeting = json.loads(path.read_text(encoding='utf-8'))
            except (ValueError, OSError):
                continue
            if valid_history_record(meeting):
                meetings.append(meeting)
        return sorted(meetings, key=lambda s: s['startedAt'], reverse=True)


def valid_history_record(meeting):
    if not isinstance(meeting, dict):
        return False
    if not all(isinstance(meeting.get(key), str) for key in ('title', 'startedAt')):
        return False
    if not isinstance(meeting.get('notesText', ''), str) or not isinstance(meeting.get('lines'), list):
        return False
    return all(
        isinstance(item, dict)
        and isinstance(item.get('src'), str)
        and (item.get('dst') is None or isinstance(item['dst'], str))
        and isinstance(item.get('t'), (float, int))
        and 0 <= item['t'] <= sys.float_info.max
        for item in meeting['lines']
    )
