import json
import mock
import os
import time

from girder.models.folder import Folder
from tests import base

from .utils import BaseTestCase

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


class CopyVersionAndRunsTestCase(BaseTestCase):

    @mock.patch("girder.plugins.wholetale.lib.manifest.ImageBuilder")
    def testCopyVersion(self, mock_builder):
        mock_builder.return_value.container_config.repo2docker_version = \
            "craigwillis/repo2docker:latest"
        mock_builder.return_value.get_tag.return_value = \
            "some_image_digest"
        tale = self._create_example_tale(self.get_dataset([0]))
        workspace = Folder().load(tale["workspaceId"], force=True)

        with open(os.path.join(workspace["fsPath"], "version1"), "wb") as fp:
            fp.write(b"This belongs to version1")

        resp = self.request(
            path="/version",
            method="POST",
            user=self.user_one,
            params={"name": "First Version", "taleId": tale["_id"]},
        )
        self.assertStatusOk(resp)
        version = resp.json

        with open(os.path.join(workspace["fsPath"], "current_file"), "wb") as fp:
            fp.write(b"This belongs to current unversioned state")
        os.remove(os.path.join(workspace["fsPath"], "version1"))

        resp = self.request(
            path=f"/tale/{tale['_id']}/copy",
            method="POST",
            user=self.user_one,
            params={"versionId": version["_id"]},
        )
        self.assertStatusOk(resp)
        copied_tale = resp.json

        retries = 10
        while copied_tale["status"] < TaleStatus.READY or retries > 0:
            time.sleep(0.5)
            resp = self.request(
                path=f"/tale/{copied_tale['_id']}", method="GET", user=self.user_one
            )
            self.assertStatusOk(resp)
            copied_tale = resp.json
            retries -= 1
        self.assertEqual(copied_tale["status"], TaleStatus.READY)
        workspace = Folder().load(copied_tale["workspaceId"], force=True)
        self.assertTrue(os.path.exists(os.path.join(workspace["fsPath"], "version1")))
        self.assertFalse(os.path.exists(os.path.join(workspace["fsPath"], "current_file")))

        # Clean up
        resp = self.request(
            path=f"/tale/{copied_tale['_id']}",
            method="DELETE",
            user=self.user_one,
        )
        self.assertStatusOk(resp)
        self._remove_example_tale(tale)

    @mock.patch("girder.plugins.wholetale.lib.manifest.ImageBuilder")
    def testFullCopy(self, mock_builder):
        mock_builder.return_value.container_config.repo2docker_version = \
            "craigwillis/repo2docker:latest"
        mock_builder.return_value.get_tag.return_value = \
            "some_image_digest"
        tale = self._create_example_tale(self.get_dataset([0]))
        workspace = Folder().load(tale["workspaceId"], force=True)

        with open(os.path.join(workspace["fsPath"], "entrypoint.sh"), "wb") as fp:
            fp.write(b"echo 'Performed a run!'")

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
            params={"versionId": version["_id"], "name": "test run (failed)"},
        )
        self.assertStatusOk(resp)
        run = resp.json

        resp = self.request(
            path=f"/run/{run['_id']}/status",
            method="PATCH",
            user=self.user_one,
            params={"status": 4},
        )

        resp = self.request(
            path="/run",
            method="POST",
            user=self.user_one,
            params={"versionId": version["_id"], "name": "test run (success)"},
        )
        self.assertStatusOk(resp)
        run = resp.json

        resp = self.request(
            path=f"/run/{run['_id']}/status",
            method="PATCH",
            user=self.user_one,
            params={"status": 3},
        )

        # 1. Make it public
        resp = self.request(
            path=f"/tale/{tale['_id']}/access", method="GET", user=self.user_one
        )
        self.assertStatusOk(resp)
        tale_access = resp.json

        resp = self.request(
            path=f"/tale/{tale['_id']}/access",
            method="PUT",
            user=self.user_one,
            params={"access": json.dumps(tale_access), "public": True},
        )
        self.assertStatusOk(resp)

        # 2. Perform copy as user2
        resp = self.request(
            path=f"/tale/{tale['_id']}/copy", method="POST", user=self.user_two
        )
        self.assertStatusOk(resp)
        copied_tale = resp.json

        retries = 10
        while copied_tale["status"] < TaleStatus.READY or retries > 0:
            time.sleep(0.5)
            resp = self.request(
                path=f"/tale/{copied_tale['_id']}", method="GET", user=self.user_two
            )
            self.assertStatusOk(resp)
            copied_tale = resp.json
            retries -= 1
        self.assertEqual(copied_tale["status"], TaleStatus.READY)

        resp = self.request(
            path="/version",
            method="GET",
            user=self.user_two,
            params={"taleId": copied_tale["_id"]},
        )
        self.assertStatusOk(resp)
        self.assertTrue(len(resp.json), 1)
        copied_version = resp.json[0]
        self.assertEqual(copied_version["name"], version["name"])

        resp = self.request(
            path="/run",
            method="GET",
            user=self.user_two,
            params={"taleId": copied_tale["_id"]},
        )
        self.assertStatusOk(resp)
        self.assertTrue(len(resp.json), 2)
        copied_runs = resp.json
        print(copied_runs)

        self.assertEqual(
            {_["runVersionId"] for _ in copied_runs}, {copied_version["_id"]}
        )
        self.assertEqual(
            {_["name"] for _ in copied_runs},
            {"test run (success)", "test run (failed)"},
        )
        self.assertEqual({_["runStatus"] for _ in copied_runs}, {3, 4})

        # Clean up
        resp = self.request(
            path=f"/tale/{copied_tale['_id']}",
            method="DELETE",
            user=self.user_two,
        )
        self.assertStatusOk(resp)
        self._remove_example_tale(tale)
