import pathlib

from girder.models.setting import Setting
from ..constants import PluginSettings


def getTaleVersionsDirPath(tale: dict) -> pathlib.Path:
    return getTaleDirPath(tale, PluginSettings.VERSIONS_DIRS_ROOT)


def getTaleRunsDirPath(tale: dict) -> pathlib.Path:
    return getTaleDirPath(tale, PluginSettings.RUNS_DIRS_ROOT)


def getTaleDirPath(tale: dict, rootProp: str) -> pathlib.Path:
    settings = Setting()
    root = settings.get(rootProp)
    taleId = str(tale['_id'])
    return pathlib.Path(root) / taleId[0:2] / taleId
