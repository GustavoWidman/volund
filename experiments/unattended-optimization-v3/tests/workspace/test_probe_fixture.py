import asyncio
from pathlib import Path
import tempfile
import unittest
from runtime.probe_workspace_router import setup_actor
from runtime.workspace import WorkspaceRouter
from owner.measurement import MeasurementCoordinator

class ProbeFixtureTests(unittest.TestCase):
    def test_setup_actor_provenance_exercises_real_router_before_cli_probe(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as td:
                root=Path(td);actor_path=root/'actor';actor_path.mkdir()
                actor=setup_actor(actor_path)
                router=WorkspaceRouter(object(),MeasurementCoordinator(),root)
                try:
                    result=await router.dispatch(actor,'study_workspace_write',{'path':'sample.cpp','content':'int main(){return 0;}\n'})
                    self.assertEqual(result['status'],'ok')
                    result=await router.dispatch(actor,'study_workspace_read',{'path':'sample.cpp'})
                    self.assertEqual(result['status'],'ok')
                    self.assertIn('int main',result['content'])
                finally:await router.close()
        asyncio.run(scenario())
