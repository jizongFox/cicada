"""Linux persistence: atomic JSON snapshots; credentials never enter sessions."""
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile


def data_root():
    return Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share')) / 'cicada'


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = None
    try:
        with NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            os.chmod(temporary, 0o600)
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


class Store:
    def __init__(self, root=None):
        self.root = Path(root) if root else data_root()

    def save(self, meeting):
        write_json(self.root / 'Sessions' / meeting['id'] / 'session.json', meeting)

    def history(self):
        meetings = []
        for path in (self.root / 'Sessions').glob('*/session.json'):
            try:
                meetings.append(json.loads(path.read_text()))
            except (ValueError, OSError):
                continue
        return sorted(meetings, key=lambda s: s['startedAt'], reverse=True)
