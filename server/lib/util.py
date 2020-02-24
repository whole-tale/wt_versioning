import pathlib

from girder.models.setting import Setting
from girder.plugins.wt_home_dir.lib.PathMapper import TalePathMapper
from ..constants import PluginSettings
from girder.plugins.wt_home_dir.constants import PluginSettings as WTHomesPluginSettings


def getTaleVersionsDirPath(tale: dict) -> pathlib.Path:
    return getTaleDirPath(tale, PluginSettings.VERSIONS_DIRS_ROOT)


def getTaleRunsDirPath(tale: dict) -> pathlib.Path:
    return getTaleDirPath(tale, PluginSettings.RUNS_DIRS_ROOT)


def getTaleWorkspaceDirPath(tale: dict) -> pathlib.Path:
    settings = Setting()
    root = settings.get(WTHomesPluginSettings.TALE_DIRS_ROOT)
    taleId = str(tale['_id'])
    return pathlib.Path(root) / TalePathMapper().davToPhysical('/' + taleId)[1:]


def getTaleDirPath(tale: dict, rootProp: str) -> pathlib.Path:
    settings = Setting()
    root = settings.get(rootProp)
    taleId = str(tale['_id'])
    return pathlib.Path(root) / taleId[0:2] / taleId
