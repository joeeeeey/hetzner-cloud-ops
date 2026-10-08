import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from hetzner_cloud_ops.backend import HybridBackend
from hetzner_cloud_ops.errors import BackendError
from hetzner_cloud_ops.command_router import CommandRouter, _build_parser, _find_server
from hetzner_cloud_ops.utils import atomic_write_text
class Behavior(unittest.TestCase):
    def test_failed_create_never_replayed(self):
        with patch('hetzner_cloud_ops.backend.detect_hcloud') as detect:
            detect.return_value.available=True
            b=HybridBackend(token='synthetic');b._cli=MagicMock();b._api=MagicMock()
            b._cli.create_server.side_effect=BackendError('timeout')
            with self.assertRaises(BackendError):b.create_server(name='x',image='ubuntu',server_type='cx',location=None,ssh_keys=None,user_data=None,user_data_from_file=None)
            b._api.create_server.assert_not_called()
    def test_power_dry_run(self):
        args=_build_parser().parse_args(['power','stop','123']);b=MagicMock()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(CommandRouter()._cmd_power({'resources':{'servers':[{'id':123,'name':'synthetic'}]}},b,args,secrets=[]),0)
        b.server_power_action.assert_not_called()
    def test_no_partial_target_match(self):
        self.assertIsNone(_find_server({'resources':{'servers':[{'id':123,'name':'production'}]}},'prod'))
    def test_private_snapshot(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'state.json';atomic_write_text(p,'{}')
            self.assertEqual(p.read_text(),'{}')
            if os.name!='nt':self.assertEqual(p.stat().st_mode&0o777,0o600)
