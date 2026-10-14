"""Kiểm tra setup portable và tài nguyên được phân phối với notebook."""
import hashlib
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import AmazingHand_Setup as setup


class SetupTests(unittest.TestCase):
    def setUp(self):
        redirect = redirect_stdout(io.StringIO())
        redirect.__enter__()
        self.addCleanup(redirect.__exit__, None, None, None)

    def test_installed_control_profile_does_not_reinstall(self):
        with patch.object(setup,'_pip_install') as install:
            setup.ensure_dependencies(Path(__file__).resolve().parents[2]/'requirements-control.txt')
        install.assert_not_called()

    def test_auto_port_is_unambiguous_and_does_not_assume_com3(self):
        from serial.tools import list_ports
        with patch.object(list_ports,'comports',return_value=[NS(device='COM8',vid=1,description='CH343')]):
            self.assertEqual(setup.choose_serial_port(),'COM8')
        with patch.object(list_ports,'comports',return_value=[]):
            with self.assertRaises(RuntimeError):
                setup.choose_serial_port()
        self.assertEqual(setup.choose_serial_port('COM12'),'COM12')

    def test_bundled_model_checksum_is_valid(self):
        root=Path(__file__).resolve().parents[2]
        with patch.object(setup,'_download') as download:
            self.assertEqual(setup.ensure_rps_model(root),root/'models/rps.h5')
        download.assert_not_called()

    def test_hand_adapter_is_preferred_over_other_usb_serial_devices(self):
        from serial.tools import list_ports
        devices=[NS(device='COM7',vid=123,description='USB Serial CP210'),
                 NS(device='COM19',vid=456,description='USB-Enhanced-SERIAL CH343')]
        with patch.object(list_ports,'comports',return_value=devices):
            self.assertEqual(setup.choose_serial_port(),'COM19')

    def test_multiple_hand_adapters_are_not_selected_arbitrarily(self):
        from serial.tools import list_ports
        devices=[NS(device=f'COM{i}',vid=1,description='CH343') for i in (5,9)]
        with patch.object(list_ports,'comports',return_value=devices):
            with self.assertRaises(RuntimeError):setup.choose_serial_port()

    def test_missing_model_is_downloaded_once_and_verified(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'models').mkdir()
            content=b'checkpoint-test'
            (root/'models/rps.metadata.json').write_text(json.dumps({
                'sha256':hashlib.sha256(content).hexdigest(),'download_url':'https://example.invalid/rps.h5'}))
            def download(url,destination):
                temporary=destination.with_suffix('.h5.part')
                temporary.write_bytes(content)
                return temporary
            with patch.object(setup,'_download',side_effect=download) as fetch:
                setup.ensure_rps_model(root)
                setup.ensure_rps_model(root)
                fetch.assert_called_once()

    def test_corrupt_download_does_not_replace_existing_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'models').mkdir()
            target=root/'models/rps.h5';target.write_bytes(b'old')
            (root/'models/rps.metadata.json').write_text(json.dumps({
                'sha256':hashlib.sha256(b'correct').hexdigest(),'download_url':'https://example.invalid'}))
            def corrupt(url,destination):
                temporary=destination.with_suffix('.part');temporary.write_bytes(b'corrupt');return temporary
            with patch.object(setup,'_download',side_effect=corrupt):
                with self.assertRaises(RuntimeError):setup.ensure_rps_model(root)
            self.assertEqual(target.read_bytes(),b'old')

    def test_all_notebooks_have_bootstrap_and_no_saved_output(self):
        import nbformat
        root=Path(__file__).resolve().parents[2]
        paths=list(root.glob('*.ipynb'))+list((root/'PythonExample').glob('*.ipynb'))
        self.assertEqual(len(paths),4)
        for path in paths:
            notebook=nbformat.read(path,4);nbformat.validate(notebook)
            code=[c for c in notebook.cells if c.cell_type=='code']
            self.assertTrue(any('ensure_dependencies(' in c.source for c in code),path)
            self.assertTrue(all(not c.outputs and c.execution_count is None for c in code),path)
