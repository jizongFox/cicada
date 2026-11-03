"""Qt presentation and composition root. Workers own blocking audio/network work."""
import copy
import json
import threading
from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QFormLayout,
    QLineEdit, QComboBox, QPushButton, QTextEdit, QLabel, QListWidget, QFileDialog,
    QSplitter, QDialog)
from .storage import Store, data_root, write_json
from .core import markdown
from .pipewire import CaptureError, monitors, PipeWireCapture
from .providers import LocalASR, CloudASR, ProviderError, TextService
from .workflow import Meeting


DEFAULTS = dict(backend='local', local_model='small', device='auto', language='auto',
                target='Chinese', asr_url='https://api.openai.com/v1', asr_model='whisper-1',
                asr_key='', text_url='https://api.openai.com/v1', text_model='gpt-4o-mini', text_key='')


class Worker(QThread):
    changed = Signal(object)
    warning = Signal(str)
    listening = Signal(str)

    def __init__(self, config, source, store):
        super().__init__()
        self.config, self.source, self.store = config, source, store
        self.stop = threading.Event()
        self.result = 'Stopped. Meeting saved.'

    def run(self):
        c = self.config
        try:
            asr = (LocalASR(c['local_model'], c['device'], c['language']) if c['backend'] == 'local'
                   else CloudASR(c['asr_url'], c['asr_key'], c['asr_model'], c['language']))
            if self.stop.is_set():
                self.result = 'Stopped before capture started.'
                return
            self.listening.emit('Listening with cloud audio upload' if c['backend'] == 'cloud'
                                else 'Listening with local speech recognition')
            service = TextService(c['text_url'], c['text_key'], c['text_model']) if c['text_key'] else None
            meeting = Meeting(PipeWireCapture(self.source), asr, service, self.store, c['language'], c['target'])
            meeting.run(self.stop, lambda value: self.changed.emit(copy.deepcopy(value)), self.warning.emit)
        except (CaptureError, ProviderError) as error:
            self.result = str(error)
        except Exception as error:
            # Provider exceptions must not reveal response bodies or credentials.
            self.result = f'{type(error).__name__}: processing stopped. Verify dependencies and provider configuration.'


class Window(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Cicada — Ubuntu')
        self.resize(1000, 760)
        self.store, self.worker, self.current = Store(), None, None
        config = DEFAULTS.copy()
        try:
            saved = json.loads((data_root() / 'settings.json').read_text(encoding='utf-8'))
            if isinstance(saved, dict):
                config.update({key: saved[key] for key in config if isinstance(saved.get(key), str)})
        except (OSError, ValueError):
            pass
        layout = QVBoxLayout(self)
        self.status = QLabel('Select a playback monitor. Local ASR keeps audio local; cloud ASR uploads speech to your endpoint. Text translation and notes send transcripts to the text endpoint.')
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.PlainText)
        layout.addWidget(self.status)
        form = QFormLayout()
        self.fields = {}
        for key, value in config.items():
            if key in ('backend', 'device'):
                field = QComboBox()
                field.addItems(['local', 'cloud'] if key == 'backend' else ['auto', 'cpu', 'cuda'])
                field.setCurrentText(value)
            else:
                field = QLineEdit(value)
                if key.endswith('key'):
                    field.setEchoMode(QLineEdit.Password)
            self.fields[key] = field
            form.addRow(key.replace('_', ' ').title(), field)
        self.form_widget = QWidget()
        self.form_widget.setLayout(form)
        layout.addWidget(self.form_widget)
        self.source = QComboBox()
        layout.addWidget(self.source)
        refresh = QPushButton('Refresh playback monitors')
        refresh.clicked.connect(self.refresh)
        layout.addWidget(refresh)
        self.toggle = QPushButton('Start')
        self.toggle.clicked.connect(self.toggle_listening)
        layout.addWidget(self.toggle)
        self.overlay = QDialog(self, Qt.Tool)
        self.overlay.setWindowTitle('Cicada captions')
        caption_layout = QVBoxLayout(self.overlay)
        self.caption = QLabel('Waiting for speech')
        self.caption.setWordWrap(True)
        self.caption.setTextFormat(Qt.PlainText)
        caption_layout.addWidget(self.caption)
        self.overlay.resize(700, 150)
        captions = QPushButton('Show captions window')
        captions.clicked.connect(self.overlay.show)
        layout.addWidget(captions)
        splitter = QSplitter()
        self.history = QListWidget()
        self.history.currentRowChanged.connect(self.select_history)
        self.transcript = QTextEdit()
        self.transcript.setReadOnly(True)
        splitter.addWidget(self.history)
        splitter.addWidget(self.transcript)
        layout.addWidget(splitter, 1)
        export = QPushButton('Export selected meeting as Markdown')
        export.clicked.connect(self.export)
        layout.addWidget(export)
        self.reload_history()
        self.refresh()

    def refresh(self):
        self.source.clear()
        try:
            for name, description in monitors():
                self.source.addItem(description, name)
        except Exception:
            self.status.setText('Monitor discovery failed. Install pulseaudio-utils and check that pipewire-pulse is running.')

    def reload_history(self):
        self.saved = self.store.history()
        self.history.clear()
        self.history.addItems([s['title'] for s in self.saved])

    def select_history(self, index):
        if 0 <= index < len(self.saved):
            self.display(self.saved[index])

    def display(self, meeting):
        self.current = meeting
        self.transcript.setPlainText(markdown(meeting))
        if meeting['lines']:
            last = meeting['lines'][-1]
            self.caption.setText(last['src'] + '\n' + (last.get('dst') or ''))

    def toggle_listening(self):
        if self.worker:
            self.worker.stop.set()
            self.toggle.setEnabled(False)
            self.status.setText('Finishing queued speech and saving notes…')
            return
        if not self.source.currentData():
            self.status.setText('Select an available playback monitor first.')
            return
        config = {k: f.currentText() if isinstance(f, QComboBox) else f.text().strip() for k, f in self.fields.items()}
        if config['backend'] == 'cloud' and not config['asr_key']:
            self.status.setText('Cloud ASR requires an API key.')
            return
        try:
            write_json(data_root() / 'settings.json', config)
        except OSError:
            self.status.setText('Could not save settings. Check permissions on the Cicada data directory.')
            return
        self.worker = Worker(config, self.source.currentData(), self.store)
        self.worker.changed.connect(self.display)
        self.worker.warning.connect(self.status.setText)
        self.worker.listening.connect(self.show_listening)
        self.worker.finished.connect(self.finished)
        self.form_widget.setEnabled(False)
        self.toggle.setText('Stop')
        self.caption.setText('Waiting for speech')
        self.status.setText('Starting speech recognition and audio capture…')
        self.worker.start()

    def show_listening(self, message):
        if self.worker and not self.worker.stop.is_set():
            self.status.setText(message)

    def finished(self):
        self.status.setText(self.worker.result)
        self.worker.deleteLater()
        self.worker = None
        self.toggle.setEnabled(True)
        self.toggle.setText('Start')
        self.form_widget.setEnabled(True)
        self.reload_history()

    def export(self):
        if self.current:
            path, _ = QFileDialog.getSaveFileName(self, 'Export', 'meeting.md', 'Markdown (*.md)')
            if path:
                from pathlib import Path
                try:
                    Path(path).write_text(markdown(self.current), encoding='utf-8')
                except OSError:
                    self.status.setText('Could not export the meeting. Choose a writable location.')

    def closeEvent(self, event):
        if self.worker:
            self.worker.stop.set()
            self.status.setText('Finishing the session. Close again after processing stops.')
            event.ignore()
        else:
            event.accept()


def main():
    app = QApplication([])
    window = Window()
    window.show()
    app.exec()
