import os

from girder.models.folder import Folder
from tests import base

from .utils import BaseTestCase

Image = None
Tale = None
TaleStatus = None


def setUpModule():
    base.enabledPlugins.append("virtual_resources")
    base.enabledPlugins.append("wholetale")
    base.enabledPlugins.append("wt_home_dir")
    base.enabledPlugins.append("wt_versioning")
    base.startServer()

    global Tale, TaleStatus
    from girder.plugins.wholetale.constants import TaleStatus
    from girder.plugins.wholetale.models.tale import Tale


def tearDownModule():
    base.stopServer()


class RunsTestCase(BaseTestCase):
    def testBasicRunsOps(self):
        tale = self._create_example_tale(self.get_dataset([0]))
        workspace = Folder().load(tale["workspaceId"], force=True)

        file1_content = b"Hello World!"
        file1_name = "test_file.txt"

        with open(os.path.join(workspace["fsPath"], file1_name), "wb") as f:
            f.write(file1_content)

        resp = self.request(
            path="/version",
            method="POST",
            user=self.user_one,
            params={"name": "First Version", "taleId": tale["_id"]},
        )
        self.assertStatusOk(resp)
        version = resp.json

        resp = self.request(
            path="/run",
            method="POST",
            user=self.user_one,
            params={"versionId": version["_id"], "name": "test run"},
        )
        self.assertStatusOk(resp)
        run = resp.json

        resp = self.request(path=f"/run/{run['_id']}", method="GET", user=self.user_one)
        self.assertStatusOk(resp)
        refreshed_run = resp.json
        for key in ("created", "updated"):
            run.pop(key)
            refreshed_run.pop(key)
        self.assertEqual(refreshed_run, run)

        run = Folder().load(run["_id"], force=True)  # Need fsPath
        self.assertTrue(
            os.path.isfile(os.path.join(run["fsPath"], "workspace", file1_name))
        )

        # Try to delete version with an existing run.
        # It should fail.
        resp = self.request(
            path=f"/version/{version['_id']}", method="DELETE", user=self.user_one
        )
        self.assertStatus(resp, 461)

        # Rename run
        resp = self.request(
            path=f"/run/{run['_id']}",
            method="PUT",
            params={"name": "a better name"},
            user=self.user_one,
        )
        self.assertStatusOk(resp)
        self.assertEqual(resp.json["name"], "a better name")
        run = Folder().load(run["_id"], force=True)
        self.assertEqual(run["name"], resp.json["name"])

        resp = self.request(
            path="/run/exists",
            method="GET",
            params={"name": "test run", "taleId": tale["_id"]},
            user=self.user_one,
        )
        self.assertStatusOk(resp)
        self.assertEqual(resp.json, {"exists": False})

        resp = self.request(
            path="/run/exists",
            method="GET",
            params={"name": "a better name", "taleId": tale["_id"]},
            user=self.user_one,
        )
        self.assertStatusOk(resp)
        self.assertTrue(resp.json["exists"])
        self.assertEqual(resp.json["obj"]["_id"], str(run["_id"]))

        # Get current status, should be UNKNOWN
        resp = self.request(
            path=f"/run/{run['_id']}/status", method="GET", user=self.user_one
        )
        self.assertStatusOk(resp)
        self.assertEqual(resp.json, dict(status=0, statusString="UNKNOWN"))

        # Set status to RUNNING
        resp = self.request(
            path=f"/run/{run['_id']}/status",
            method="PATCH",
            user=self.user_one,
            params={"status": 2},
        )
        self.assertStatusOk(resp)

        # Get current status, should be RUNNING
        resp = self.request(
            path=f"/run/{run['_id']}/status", method="GET", user=self.user_one
        )
        self.assertStatusOk(resp)
        self.assertEqual(resp.json, dict(status=2, statusString="RUNNING"))

        resp = self.request(
            path=f"/run/{run['_id']}", method="DELETE", user=self.user_one
        )
        self.assertFalse(
            os.path.exists(os.path.join(run["fsPath"], "workspace", file1_name))
        )
        self.assertStatusOk(resp)

        resp = self.request(
            path=f"/version/{version['_id']}", method="DELETE", user=self.user_one
        )
        self.assertStatusOk(resp)
