import json
import shutil
from pathlib import Path

from girder.models.folder import Folder
from girder.models.setting import Setting
from girder.models.user import User
from tests import base


class BaseTestCase(base.TestCase):
    def setUp(self):
        from girder.plugins.wholetale.models.image import Image
        from girder.plugins.wt_versioning.constants import PluginSettings

        super(BaseTestCase, self).setUp()

        asset_root = Path(self.assetstore["root"])
        self.versions_root = asset_root / "versions"
        self.versions_root.mkdir()
        Setting().set(PluginSettings.VERSIONS_DIRS_ROOT, self.versions_root.as_posix())
        self.runs_root = asset_root / "runs"
        self.runs_root.mkdir()
        Setting().set(PluginSettings.RUNS_DIRS_ROOT, self.runs_root.as_posix())

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

        self.image2 = Image().createImage(
            name="test other name",
            creator=self.user_one,
            public=True,
            config=dict(
                template="base.tpl",
                buildpack="OtherBuildPack",
                user="someUser",
                port=8888,
                urlPath="",
            ),
        )

        self.data_map = [
            {
                "dataId": "resource_map_doi:10.5065/D6862DM8",
                "doi": "10.5065/D6862DM8",
                "name": "Humans and Hydrology at High Latitudes: Water Use Information",
                "repository": "DataONE",
                "size": 28_856_295,
                "tale": False,
            },
            {
                "dataId": (
                    "https://dataverse.harvard.edu/dataset.xhtml?"
                    "persistentId=doi:10.7910/DVN/Q5PV4U"
                ),
                "doi": "doi:10.7910/DVN/Q5PV4U",
                "name": (
                    "Replication Data for: Misgovernance and Human Rights: "
                    "The Case of Illegal Detention without Intent"
                ),
                "repository": "Dataverse",
                "size": 6_326_512,
                "tale": False,
            },
        ]

        resp = self.request(
            path="/dataset/register",
            method="POST",
            params={"dataMap": json.dumps(self.data_map)},
            user=self.user_one,
        )
        self.assertStatusOk(resp)

    def _create_example_tale(self, dataset=None):
        if dataset is None:
            dataset = []
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
            "dataSet": dataset,
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
        tale = resp.json
        return tale

    def _remove_example_tale(self, tale, user=None):
        if not user:
            user = self.user_one
        resp = self.request(
            path="/tale/{_id}".format(**tale), method="DELETE", user=user
        )
        self.assertStatusOk(resp)

    def get_dataset(self, indices):
        user = User().load(self.user_one["_id"], force=True)
        dataSet = []
        for i in indices:
            _id = user["myData"][i]
            folder = Folder().load(_id, force=True)
            dataSet.append(
                {
                    "_modelType": "folder",
                    "itemId": str(_id),
                    "mountPath": folder["name"],
                }
            )
        return dataSet

    def tearDown(self):
        shutil.rmtree(self.runs_root)
        shutil.rmtree(self.versions_root)
        super().tearDown()
