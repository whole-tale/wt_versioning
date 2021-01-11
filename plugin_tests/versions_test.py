import json
import os
import pathlib
from girder.models.folder import Folder
from girder.models.setting import Setting
from girder.models.user import User

from tests import base


Image = None
Tale = None


def setUpModule():
    base.enabledPlugins.append("virtual_resources")
    base.enabledPlugins.append("wholetale")
    base.enabledPlugins.append("wt_home_dir")
    base.enabledPlugins.append("wt_versioning")
    base.startServer()

    global Image, Tale
    from girder.plugins.wholetale.models.image import Image
    from girder.plugins.wholetale.models.tale import Tale


def tearDownModule():
    base.stopServer()


class VersionTestCase(base.TestCase):
    def setUp(self):
        super(VersionTestCase, self).setUp()

        users = (
            {
                "email": "root@dev.null",
                "login": "admin",
                "firstName": "Root",
                "lastName": "van Klompf",
                "password": "secret",
                "admin": True,
            },
            {
                "email": "joe@dev.null",
                "admin": False,
                "login": "joeregular",
                "firstName": "Joe",
                "lastName": "Regular",
                "password": "secret",
            },
            {
                "firstName": "Barbara",
                "lastName": "Smith",
                "login": "basia",
                "email": "basia@localhost.com",
                "admin": False,
                "password": "password",
            },
        )

        self.admin, self.user_one, self.user_two = (
            User().createUser(**user) for user in users
        )
        self.image = Image().createImage(
            name="test my name",
            creator=self.user_one,
            public=True,
            config=dict(
                template="base.tpl",
                buildpack="SomeBuildPack",
                user="someUser",
                port=8888,
                urlPath="",
            ),
        )

    def _create_example_tale(self):
        tale = {
            "authors": [
                {
                    "firstName": "Kacper",
                    "lastName": "Kowalik",
                    "orcid": "https://orcid.org/0000-0003-1709-3744",
                }
            ],
            "category": "science",
            "config": {},
            "dataSet": [],
            "description": "Something something...",
            "imageId": str(self.image["_id"]),
            "public": False,
            "published": False,
            "title": "Some tale with dataset and versions",
        }

        resp = self.request(
            path="/tale",
            method="POST",
            user=self.user_one,
            type="application/json",
            body=json.dumps(tale),
        )
        self.assertStatusOk(resp)
        return resp.json

    def _remove_example_tale(self, tale, user=None):
        if not user:
            user = self.user_one
        resp = self.request(
            path="/tale/{_id}".format(**tale), method="DELETE", user=user
        )
        self.assertStatusOk(resp)

    def testBasicVersionOps(self):
        from girder.plugins.wt_versioning.constants import PluginSettings

        tale = self._create_example_tale()
        workspace = Folder().load(tale["workspaceId"], force=True)

        file1_content = b"Hello World!"
        file1_name = "test_file.txt"
        file2_content = b"I'm in a directory!"
        file2_name = "file_in_a_dir.txt"
        dir_name = "some_directory"

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

        # Try to create a 2nd version, but using old name (should fail)
        resp = self.request(
            path="/version",
            method="POST",
            user=self.user_one,
            params={"name": "First Version", "taleId": tale["_id"]},
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
        self.assertTrue(new_version["name"].endswith(year))  # it's a date

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
        self.assertEqual(new_version, resp.json)

        # Check if data is where it's supposed to be
        should_be_a_file = (
            version_path / new_version["_id"] / "workspace" / dir_name / file2_name
        )
        self.assertTrue(should_be_a_file.is_file())

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

        # Clean up
        self._remove_example_tale(tale)
