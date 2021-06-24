import copy
import json
import os
import pathlib
import time

from girder.models.folder import Folder
from girder.models.setting import Setting
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


class VersionTestCase(BaseTestCase):
    def testBasicVersionOps(self):
        from girder.plugins.wt_versioning.constants import PluginSettings

        tale = self._create_example_tale(self.get_dataset([0]))
        workspace = Folder().load(tale["workspaceId"], force=True)

        file1_content = b"Hello World!"
        file1_name = "test_file.txt"
        file2_content = b"I'm in a directory!"
        file2_name = "file_in_a_dir.txt"
        dir_name = "some_directory"

        with open(os.path.join(workspace["fsPath"], file1_name), "wb") as f:
            f.write(file1_content)

        resp = self.request(
            path="/version/exists",
            method="GET",
            user=self.user_one,
            params={"name": "First Version", "taleId": tale["_id"]},
        )
        self.assertStatusOk(resp)
        self.assertEqual(resp.json, {"exists": False})

        resp = self.request(
            path="/version",
            method="POST",
            user=self.user_one,
            params={"name": "First Version", "taleId": tale["_id"]},
        )
        self.assertStatusOk(resp)
        version = resp.json

        resp = self.request(
            path="/version/exists",
            method="GET",
            user=self.user_one,
            params={"name": "First Version", "taleId": tale["_id"]},
        )
        self.assertStatusOk(resp)
        self.assertTrue(resp.json["exists"])
        self.assertEqual(resp.json["obj"]["_id"], version["_id"])

        version_root = Setting().get(PluginSettings.VERSIONS_DIRS_ROOT)
        version_path = pathlib.Path(version_root) / tale["_id"][:2] / tale["_id"]

        self.assertTrue(version_path.is_dir())
        should_be_a_file = version_path / version["_id"] / "workspace" / file1_name
        self.assertTrue(should_be_a_file.is_file())

        # Try to create a version with no changes (should fail)
        resp = self.request(
            path="/version",
            method="POST",
            user=self.user_one,
            params={"taleId": tale["_id"]},
        )
        self.assertStatus(resp, 303)
        self.assertEqual(
            resp.json,
            {"extra": str(version["_id"]), "message": "Not modified", "type": "rest"},
        )

        # Make some modification to the workspace
        workspace_path = pathlib.Path(workspace["fsPath"])
        workspace_dir = workspace_path / dir_name
        workspace_dir.mkdir()
        nested_file = workspace_dir / file2_name
        with open(nested_file.as_posix(), "wb") as f:
            f.write(file2_content)

        # Make some mods to Tale itself
        first_version_tale = copy.deepcopy(tale)
        tale = Tale().load(tale["_id"], force=True)
        tale["dataSet"] = self.get_dataset([1])
        tale["authors"].append(
            {
                "firstName": "Craig",
                "lastName": "Willis",
                "orcid": "https://orcid.org/0000-0002-6148-7196",
            }
        )
        tale.update(
            {
                "category": "rocket science",
                "config": {"foo": "bar"},
                "description": "A better description",
                "imageId": self.image2["_id"],
                "title": "New better title",
            }
        )
        tale = Tale().save(tale)

        # Try to create a 2nd version, but using old name (should fail)
        resp = self.request(
            path="/version",
            method="POST",
            user=self.user_one,
            params={"name": "First Version", "taleId": str(tale["_id"])},
        )
        self.assertStatus(resp, 409)
        self.assertEqual(
            resp.json,
            {"message": f"Name already exists: {version['name']}", "type": "rest"},
        )

        # Try to create a 2nd version providing no name (should work)
        resp = self.request(
            path="/version",
            method="POST",
            user=self.user_one,
            params={"taleId": tale["_id"]},
        )
        self.assertStatusOk(resp)
        new_version = resp.json
        year = new_version["created"][:4]
        self.assertTrue(year in new_version["name"])  # it's a date

        # Check that Tale has two versions
        resp = self.request(
            path="/version",
            method="GET",
            user=self.user_one,
            params={"taleId": tale["_id"]},
        )
        self.assertStatusOk(resp)
        self.assertTrue(len(resp.json), 2)
        self.assertTrue(
            (_["_id"] for _ in resp.json), (version["_id"], new_version["_id"])
        )

        # Rename 2nd version to something silly (should fail)
        resp = self.request(
            path=f"/version/{new_version['_id']}",
            method="PUT",
            user=self.user_one,
            params={"name": "*/*"},
        )
        self.assertStatus(resp, 400)

        # Rename 2nd version to 2nd version (should work)
        resp = self.request(
            path=f"/version/{new_version['_id']}",
            method="PUT",
            user=self.user_one,
            params={"name": "Second version"},
        )
        self.assertStatusOk(resp)
        new_version = resp.json

        # Check if GET /version/:id works
        resp = self.request(
            path=f"/version/{new_version['_id']}", method="GET", user=self.user_one
        )
        self.assertStatusOk(resp)
        new_version["updated"] = resp.json[
            "updated"
        ]  # There's a small drift between those
        self.assertEqual(new_version, resp.json)

        # Check if data is where it's supposed to be
        should_be_a_file = (
            version_path / new_version["_id"] / "workspace" / dir_name / file2_name
        )
        self.assertTrue(should_be_a_file.is_file())

        # Try to create a version with no changes (should fail) test recursion
        resp = self.request(
            path="/version",
            method="POST",
            user=self.user_one,
            params={"taleId": tale["_id"]},
        )
        self.assertStatus(resp, 303)
        self.assertEqual(
            resp.json,
            {
                "extra": str(new_version["_id"]),
                "message": "Not modified",
                "type": "rest",
            },
        )

        # Restore First Version
        resp = self.request(
            method="PUT",
            user=self.user_one,
            path=f"/tale/{tale['_id']}/restore",
            params={"versionId": version["_id"]},
        )
        self.assertStatusOk(resp)
        restored_tale = resp.json

        for key in restored_tale.keys():
            if key in ("created", "updated", "restoredFrom", "imageInfo"):
                continue
            try:
                self.assertEqual(restored_tale[key], first_version_tale[key])
            except AssertionError:
                print(key)
                raise

        workspace = Folder().load(restored_tale["workspaceId"], force=True)
        workspace_path = pathlib.Path(workspace["fsPath"])
        w_should_be_a_file = workspace_path / file1_name
        self.assertTrue(w_should_be_a_file.is_file())
        w_should_not_be_a_file = workspace_path / dir_name / file2_name
        self.assertFalse(w_should_not_be_a_file.is_file())

        # Remove and see if it's gone
        resp = self.request(
            path=f"/version/{new_version['_id']}", method="DELETE", user=self.user_one
        )
        self.assertStatusOk(resp)
        self.assertFalse(should_be_a_file.is_file())
        resp = self.request(
            path=f"/version/{new_version['_id']}", method="GET", user=self.user_one
        )
        self.assertStatus(resp, 400)
        self.assertEqual(
            resp.json,
            {"message": f"Invalid folder id ({new_version['_id']}).", "type": "rest"},
        )

        # Test allow rename
        resp = self.request(
            path="/version",
            method="POST",
            user=self.user_one,
            params={
                "name": "First Version",
                "taleId": tale["_id"],
                "allowRename": True,
                "force": True,
            },
        )
        self.assertStatusOk(resp)
        self.assertEqual(resp.json["name"], "First Version (1)")

        # Test copying Tale
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

        # 3. Check that copied Tale has two versions
        resp = self.request(
            path="/version",
            method="GET",
            user=self.user_two,
            params={"taleId": copied_tale["_id"]},
        )
        self.assertStatusOk(resp)
        self.assertTrue(len(resp.json), 2)

        # Clean up
        self._remove_example_tale(tale)

    def testDatasetHandling(self):
        tale = self._create_example_tale(dataset=self.get_dataset([0]))
        resp = self.request(
            path="/version",
            method="POST",
            user=self.user_one,
            params={"taleId": tale["_id"]},
        )
        self.assertStatusOk(resp)
        version = resp.json

        # Check if dataset was stored
        resp = self.request(
            path=f"/version/{version['_id']}/dataSet", method="GET", user=self.user_one
        )
        self.assertStatusOk(resp)
        self.assertTrue(len(resp.json), 1)
        self.assertEqual(resp.json[0]["itemId"], self.get_dataset([0])[0]["itemId"])

        self._remove_example_tale(tale)

    def test_force_version(self):
        tale = self._create_example_tale(dataset=self.get_dataset([0]))
        # Check that the tale has no versions.
        resp = self.request(
            path="/version",
            method="GET",
            user=self.user_one,
            params={"taleId": tale["_id"]},
        )
        self.assertStatusOk(resp)
        self.assertEqual(resp.json, [])

        # We're doing it twice to verify that only one version is created
        # if there are no changes to the Tale.
        for _ in range(2):
            # Export the Tale. This should trigger the event to create the new version
            resp = self.request(
                path=f"/tale/{tale['_id']}/export",
                method="GET",
                user=self.user_one,
                isJson=False,
            )
            self.assertStatusOk(resp)

            # Get the versions for this Tale; there should only by a single one
            # triggered by the export event
            resp = self.request(
                path="/version",
                method="GET",
                user=self.user_one,
                params={"taleId": tale["_id"]},
            )
            self.assertStatusOk(resp)
            self.assertTrue(len(resp.json), 1)
        self._remove_example_tale(tale)
