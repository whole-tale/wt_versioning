import shutil
from pathlib import Path
from typing import Optional, Union

from girder.constants import AccessType
from girder.models.folder import Folder
from girder.plugins.wholetale.models.tale import Tale
from . import util
from .hierarchy import AbstractHierarchyModel
from .version_hierarchy import VersionHierarchyModel
from ..constants import FIELD_STATUS_CODE, RunStatus, RunState


class RunHierarchyModel(AbstractHierarchyModel):
    root_tale_field = "runsRootId"

    def getStatus(self, rfolder: dict) -> dict:
        if FIELD_STATUS_CODE in rfolder:
            rs = RunStatus.get(rfolder[FIELD_STATUS_CODE])
        else:
            rs = RunStatus.UNKNOWN
        return {"status": rs.code, "statusString": rs.name}

    def setStatus(self, rfolder: dict, status: Union[int, RunState]) -> None:
        # TODO: add heartbeats (runs must regularly update status, otherwise they are considered
        # failed)
        if isinstance(status, int):
            _status = RunState.ALL[status]
        else:
            _status = status
        rfolder[FIELD_STATUS_CODE] = _status.code
        Folder().save(rfolder)
        runDir = Path(rfolder["fsPath"])
        self.write_status(runDir, _status)

    def create(
        self, version: dict, name: Optional[str], user: dict, allowRename: bool = False
    ) -> dict:
        if not name:
            name = self.generateName()

        versionsRoot = Folder().load(
            version["parentId"], user=user, level=AccessType.WRITE
        )
        taleId = versionsRoot["taleId"]
        tale = Tale().load(taleId, user=user, level=AccessType.WRITE)
        root = self.getRootFromTale(tale, user=user, level=AccessType.WRITE)
        name = self.checkNameSanity(name, root, allow_rename=allowRename)

        rootDir = util.getTaleRunsDirPath(tale)

        runFolder = self.createSubdir(rootDir, root, name, user=user)

        runFolder["runVersionId"] = version["_id"]
        runFolder[FIELD_STATUS_CODE] = RunStatus.UNKNOWN.code
        Folder().save(runFolder, False)

        # Structure is:
        #  @version -> ../Versions/<version> (link handled manually by FS)
        #  @workspace -> version/workspace (same)
        #  .status
        #  .stdout (created using stream() above)
        #  .stderr (-''-)
        runDir = Path(runFolder["fsPath"])
        tale_id = runDir.parts[-2]
        # TODO: a lot assumptions hardcoded below...
        (runDir / "version").symlink_to(
            f"../../../../versions/{tale_id[:2]}/{tale_id}/{version['_id']}", True
        )
        (runDir / "workspace").mkdir()
        self.write_status(runDir, RunStatus.UNKNOWN)

        Tale().updateTale(tale)
        VersionHierarchyModel().incrementReferenceCount(version)

        return runFolder

    @staticmethod
    def write_status(runDir: Path, status: RunState):
        with open(runDir / ".status", "w") as f:
            f.write("%s %s" % (status.code, status.name))

    def remove(self, rfolder: dict, user: dict) -> None:
        path = Path(rfolder["fsPath"])
        trashDir = path.parent / ".trash"
        version = Folder().load(
            rfolder["runVersionId"], level=AccessType.WRITE, user=user
        )
        Folder().remove(rfolder)
        shutil.move(path.as_posix(), trashDir)
        VersionHierarchyModel().decrementReferenceCount(version)
