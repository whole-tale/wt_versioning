#!/usr/bin/env python
# -*- coding: utf-8 -*-
from bson import ObjectId
import copy
import pathlib
import shutil

from girder import events
from girder.constants import AccessType, SettingDefault
from girder.models.folder import Folder
from girder.models.user import User
from girder.utility import setting_utilities
from girder.plugins.wholetale.lib.manifest import Manifest
from girder.plugins.wholetale.models.tale import Tale
from .lib.version_hierarchy import VersionHierarchyModel
from .resources.version import Version
from .resources.run import Run
from .constants import PluginSettings, Constants, FIELD_STATUS_CODE
from .lib import util


@setting_utilities.validator({
    PluginSettings.VERSIONS_DIRS_ROOT,
    PluginSettings.RUNS_DIRS_ROOT
})
def validateOtherSettings(event):
    pass


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
    tale = Tale().save(tale)
    event.addResponse(tale)


def removeVersionsAndRuns(event: events.Event) -> None:
    tale = event.info
    for folder_id in (tale["runsRootId"], tale["versionsRootId"]):
        root = Folder().load(folder_id, force=True)
        Folder().remove(root)
    shutil.rmtree(util.getTaleVersionsDirPath(tale))
    shutil.rmtree(util.getTaleRunsDirPath(tale))


def copyVersionsAndRuns(event: events.Event) -> None:

    def get_dir_path(root_id_key, tale):
        if root_id_key == "versionsRootId":
            return util.getTaleVersionsDirPath(tale)
        elif root_id_key == "runsRootId":
            return util.getTaleRunsDirPath(tale)

    old_tale, new_tale, target_version_id, shallow = event.info
    if shallow and not target_version_id:
        return
    creator = User().load(new_tale["creatorId"], force=True)
    versions_map = {}
    for root_id_key in ("versionsRootId", "runsRootId"):
        old_root = Folder().load(
            old_tale[root_id_key], user=creator, level=AccessType.READ
        )
        new_root = Folder().load(
            new_tale[root_id_key], user=creator, level=AccessType.WRITE
        )
        old_root_path = get_dir_path(root_id_key, old_tale)
        new_root_path = get_dir_path(root_id_key, new_tale)
        for src in Folder().childFolders(old_root, "folder", user=creator):
            if shallow and str(src["_id"]) != target_version_id:
                continue
            dst = Folder().createFolder(
                new_root, src["name"], creator=creator
            )
            if root_id_key == "versionsRootId":
                versions_map[str(src["_id"])] = str(dst["_id"])
            filtered_folder = Folder().filter(dst, creator)
            for key in src:
                if key not in filtered_folder and key not in dst:
                    dst[key] = copy.deepcopy(src[key])

            src_path = old_root_path / str(src["_id"])
            dst_path = new_root_path / str(dst["_id"])
            dst_path.mkdir(parents=True)
            shutil.copytree(src_path, dst_path, dirs_exist_ok=True, symlinks=True)
            dst.update(
                {
                    "fsPath": dst_path.absolute().as_posix(),
                    "isMapping": True,
                    "created": src["created"],  # preserve timestamps
                    "updated": src["updated"],
                }
            )
            if root_id_key == "runsRootId":
                current_version = dst_path / "version"
                new_version_id = versions_map[current_version.resolve().name]
                new_version_path = (
                    "../../../../versions/"
                    f"{str(new_tale['_id'])[:2]}/{new_tale['_id']}/{new_version_id}"
                )
                current_version.unlink()
                current_version.symlink_to(new_version_path, True)
                dst["runVersionId"] = ObjectId(new_version_id)
            dst = Folder().save(dst, validate=False, triggerEvents=False)
        # update the time on root
        Folder().updateFolder(new_root)

    versions_root = Folder().load(
        new_tale["versionsRootId"], user=creator, level=AccessType.WRITE
    )
    for version in Folder().childFolders(versions_root, "folder", user=creator):
        tale = copy.deepcopy(new_tale)
        tale.update(VersionHierarchyModel().restoreTaleFromVersion(version))
        manifest = Manifest(
            tale, creator, versionId=version["_id"], expand_folders=False
        )
        dst_path = pathlib.Path(version["fsPath"])
        with open(dst_path / "manifest.json", "w") as fp:
            fp.write(manifest.dump_manifest())

    Folder().updateFolder(versions_root)
    if target_version_id:
        new_version_id = versions_map[str(target_version_id)]
        target_version = Folder().load(new_version_id, level=AccessType.READ, user=creator)
        VersionHierarchyModel().restore(new_tale, target_version, creator)


def load(info):
    SettingDefault.defaults[PluginSettings.VERSIONS_DIRS_ROOT] = '/tmp/wt/versions'
    SettingDefault.defaults[PluginSettings.RUNS_DIRS_ROOT] = '/tmp/wt/runs'
    Folder().ensureIndex('created')
    VersionHierarchyModel().resetCrashedCriticalSections()

    events.bind('model.tale.save.created', 'wt_versioning', addVersionsAndRuns)
    events.bind('model.tale.remove', 'wt_versioning', removeVersionsAndRuns)
    events.bind('wholetale.tale.copied', 'wt_versioning', copyVersionsAndRuns)
    Tale().exposeFields(
        level=AccessType.READ, fields={"versionsRootId", "runsRootId", "restoredFrom"}
    )
    Folder().exposeFields(
        level=AccessType.READ, fields={"runVersionId", FIELD_STATUS_CODE}
    )

    info['apiRoot'].version = Version(info["apiRoot"].tale)
    info['apiRoot'].run = Run()
