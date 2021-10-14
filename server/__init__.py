#!/usr/bin/env python
# -*- coding: utf-8 -*-
import copy
import shutil

from girder import events
from girder.constants import AccessType, SettingDefault
from girder.models.folder import Folder
from girder.models.user import User
from girder.utility import setting_utilities
from girder.plugins.wholetale.lib.manifest import Manifest
from girder.plugins.wholetale.models.tale import Tale
from .resources.version import Version, FIELD_CRITICAL_SECTION_FLAG
from .resources.run import Run, FIELD_STATUS_CODE
from .constants import PluginSettings, Constants
from .lib import util


@setting_utilities.validator({
    PluginSettings.VERSIONS_DIRS_ROOT,
    PluginSettings.RUNS_DIRS_ROOT
})
def validateOtherSettings(event):
    pass


def setDefaults() -> None:
    SettingDefault.defaults[PluginSettings.VERSIONS_DIRS_ROOT] = '/tmp/wt-versions-dirs'
    SettingDefault.defaults[PluginSettings.RUNS_DIRS_ROOT] = '/tmp/wt-runs-dirs'


def _createAuxFolder(tale, name, rootProp, creator):
    folder = Tale()._createAuxFolder(tale, name, creator=creator)
    folder.update({'seq': 0, 'taleId': tale['_id']})
    Folder().save(folder, False)
    rootDir = util.getTaleDirPath(tale, rootProp)
    rootDir.mkdir(parents=True, exist_ok=True)
    trashDir = rootDir / '.trash'
    trashDir.mkdir(exist_ok=True)
    return (folder, rootDir)


def addVersionsAndRuns(event: events.Event) -> None:
    tale = event.info
    creator = User().load(tale['creatorId'], force=True)
    versions_root, _ = _createAuxFolder(
        tale, Constants.VERSIONS_ROOT_DIR_NAME,
        PluginSettings.VERSIONS_DIRS_ROOT, creator
    )
    tale["versionsRootId"] = versions_root["_id"]
    runs_root, _ = _createAuxFolder(
        tale, Constants.RUNS_ROOT_DIR_NAME,
        PluginSettings.RUNS_DIRS_ROOT, creator
    )
    tale["runsRootId"] = runs_root["_id"]
    tale = Tale().save(tale, triggerEvents=False, validate=False)


def removeVersionsAndRuns(event: events.Event) -> None:
    tale = event.info
    for folder_id in (tale["runsRootId"], tale["versionsRootId"]):
        root = Folder().load(folder_id, force=True)
        Folder().remove(root)
    shutil.rmtree(util.getTaleVersionsDirPath(tale))
    shutil.rmtree(util.getTaleRunsDirPath(tale))


def createIndex() -> None:
    Folder().ensureIndex('created')


def resetCrashedCriticalSections():
    Folder().update(
        {FIELD_CRITICAL_SECTION_FLAG: True}, {'$set': {FIELD_CRITICAL_SECTION_FLAG: False}}
    )


def copyVersions(event: events.Event) -> None:
    old_tale, new_tale = event.info
    creator = User().load(new_tale["creatorId"], force=True)
    old_root = Folder().load(
        old_tale["versionsRootId"], user=creator, level=AccessType.READ
    )
    new_root = Folder().load(
        new_tale["versionsRootId"], user=creator, level=AccessType.WRITE
    )
    old_root_path = util.getTaleVersionsDirPath(old_tale)
    new_root_path = util.getTaleVersionsDirPath(new_tale)
    for src_version in Folder().childFolders(old_root, "folder", user=creator):
        new_version = Folder().createFolder(
            new_root, src_version["name"], creator=creator
        )
        filtered_folder = Folder().filter(new_version, creator)
        for key in src_version:
            if key not in filtered_folder and key not in new_version:
                new_version[key] = copy.deepcopy(src_version[key])

        src_version_path = old_root_path / str(src_version["_id"])
        new_version_path = new_root_path / str(new_version["_id"])
        new_version_path.mkdir(parents=True)
        new_version.update(
            {
                "fsPath": new_version_path.absolute().as_posix(),
                "isMapping": True,
                "created": src_version["created"],  # preserve timestamps
                "updated": src_version["updated"],
            }
        )
        new_version = Folder().save(new_version, validate=False, triggerEvents=False)
        shutil.copytree(src_version_path, new_version_path, dirs_exist_ok=True)
        manifest = Manifest(
            new_tale, creator, versionId=new_version["_id"], expand_folders=False
        )
        with open(new_version_path / "manifest.json", "w") as fp:
            fp.write(manifest.dump_manifest())

    # update the time on root
    Folder().updateFolder(new_root)


def load(info):
    setDefaults()
    createIndex()
    resetCrashedCriticalSections()

    events.bind('model.tale.save.created', 'wt_versioning', addVersionsAndRuns)
    events.bind('model.tale.remove', 'wt_versioning', removeVersionsAndRuns)
    events.bind('wholetale.tale.copied', 'wt_versioning', copyVersions)
    Tale().exposeFields(
        level=AccessType.READ, fields={"versionsRootId", "runsRootId", "restoredFrom"}
    )
    Folder().exposeFields(
        level=AccessType.READ, fields={"runVersionId", FIELD_STATUS_CODE}
    )

    info['apiRoot'].version = Version(info["apiRoot"].tale)
    info['apiRoot'].run = Run()
