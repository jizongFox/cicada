"""Headless widget construction/history smoke check; does not prove Wayland support."""
import os
import tempfile
from unittest.mock import patch
from PySide6.QtWidgets import QApplication

with tempfile.TemporaryDirectory() as root:
    os.environ['XDG_DATA_HOME'] = root
    from cicada_linux.ui import Window
    app = QApplication([])
    with patch('cicada_linux.ui.monitors', return_value=[('test.monitor', 'Test output')]):
        window = Window()
    assert window.source.currentData() == 'test.monitor'
    assert window.fields['backend'].currentText() == 'local'
    window.show()
    app.processEvents()
    window.close()
