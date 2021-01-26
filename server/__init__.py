#!/usr/bin/env python
# -*- coding: utf-8 -*-
from girder.plugins.wholetale.models.tale import Tale

from girder import events
from girder.constants import AccessType, SettingDefault
from girder.models.folder import Folder
from girder.models.user import User
from girder.utility import setting_utilities
from .resources.version import Version, FIELD_CRITICAL_SECTION_FLAG
from .resources.run import Run
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
    tale = Tale().save(tale)
    event.addResponse(tale)


def createIndex() -> None:
    Folder().ensureIndex('created')


def resetCrashedCriticalSections():
    Folder().update(
        {FIELD_CRITICAL_SECTION_FLAG: True}, {'$set': {FIELD_CRITICAL_SECTION_FLAG: False}}
    )


def load(info):
    setDefaults()
    createIndex()
    resetCrashedCriticalSections()

    events.bind('model.tale.save.created', 'wt_versioning', addVersionsAndRuns)
    Tale().exposeFields(level=AccessType.READ, fields={"versionsRootId", "runsRootId"})

    info['apiRoot'].version = Version()
    info['apiRoot'].run = Run()
