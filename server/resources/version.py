import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

import pymongo
from bson import ObjectId
from girder import events, logger
from girder.api import access
from girder.api.describe import Description, autoDescribeRoute
from girder.api.rest import filtermodel
from girder.constants import AccessType, TokenScope
from girder.exceptions import RestException
from girder.models.folder import Folder
from girder.plugins.wholetale.lib.manifest import Manifest
from girder.plugins.wholetale.lib.manifest_parser import ManifestParser
from girder.plugins.wholetale.models.tale import Tale
from girder.plugins.wt_data_manager.models.session import Session

from ..constants import Constants
from ..lib import util
from .abstract_resource import AbstractVRResource

FIELD_CRITICAL_SECTION_FLAG = 'versionsCriticalSectionFlag'
FIELD_REFERENCE_COUNTER = 'versionsRefCount'
FIELD_SEQENCE_NUMBER = 'seq'
VERSION_NAME_FORMAT = '%c'


class Version(AbstractVRResource):
    root_tale_field = "versionsRootId"

    def __init__(self, tale_node):
        super().__init__('version', Constants.VERSIONS_ROOT_DIR_NAME)
        self.route('GET', (':id', 'dataSet'), self.getDataset)
        tale_node.route("GET", (":id", "restore"), self.restoreView)
        tale_node.route("PUT", (":id", "restore"), self.restore)
        events.bind("rest.get.tale/:id/export.before", "wt_versioning", self.ensure_version)
        events.bind("rest.put.tale/:id/publish.before", "wt_versioning", self.ensure_version)

    @access.user(TokenScope.DATA_WRITE)
    @filtermodel('folder')
    @autoDescribeRoute(
        Description('Rename a version. Returns the renamed version '
                    'folder')
        .modelParam('id', 'The ID of version', model=Folder, level=AccessType.WRITE,
                    destName='vfolder')
        .param('name', 'The new name', required=True, dataType='string')
        .param('allowRename', 'Allow to modify "name" if object with the same name'
               'already exists.', required=False, dataType='boolean', default=False)
        .errorResponse('Access was denied (if current user does not have write access to this '
                       'tale)', 403)
        .errorResponse('Illegal file name', 400)
        .errorResponse('Name already exists', 409)
    )
    def rename(self, vfolder: dict, name: str, allowRename: bool) -> dict:
        renamed_version = super().rename(vfolder, name, allow_rename=allowRename)
        user = self.getCurrentUser()

        root = Folder().load(vfolder["parentId"], user=user, level=AccessType.WRITE)
        tale = Tale().load(root["taleId"], user=user, level=AccessType.WRITE)
        manifest = Manifest(tale, user, versionId=renamed_version["_id"], expand_folders=False)
        version_path = Path(renamed_version["fsPath"])
        with open((version_path / "manifest.json").as_posix(), "w") as fp:
            fp.write(manifest.dump_manifest())
        Tale().updateTale(Tale().load(root["taleId"], force=True))
        return renamed_version

    @access.user(TokenScope.DATA_READ)
    @autoDescribeRoute(
        Description('Returns the dataset associated with a version, but with some additional '
                    'entries such as the type of object (folder/item) and the object dictionaries.')
        .modelParam('id', 'The ID of a version', model=Folder, level=AccessType.READ,
                    destName='version')
        .errorResponse('Access was denied (if current user does not have read access to the '
                       'respective version folder.', 403)
    )
    def getDataset(self, version: dict) -> dict:
        mp = ManifestParser(Path(version["fsPath"]) / "manifest.json")
        dataSet = mp.get_dataset()
        Session().loadObjects(dataSet)
        return dataSet

    @access.user(TokenScope.DATA_READ)
    @filtermodel("folder")
    @autoDescribeRoute(
        Description('Returns a version.')
        .modelParam('id', 'The ID of a version', model=Folder, level=AccessType.READ,
                    destName='vfolder')
        .errorResponse('Access was denied (if current user does not have read access to the '
                       'respective version folder.', 403)
    )
    def load(self, vfolder: dict) -> dict:
        return vfolder

    @access.user(TokenScope.DATA_WRITE)
    @filtermodel('folder')
    @autoDescribeRoute(
        Description('Creates a new version of a tale. Returns the new version folder.')
        .modelParam('taleId', 'A tale requesting the creation of a new version.',
                    model=Tale, level=AccessType.WRITE, destName='tale', paramType='query')
        .param('name', 'An optional name for the version. If not specified, a name will be '
                       'generated from the current date and time.', required=False,
               dataType='string')
        .param('force', 'Force creation of a version even if no files were modified in the '
                        'workspace since the last version was created.', required=False,
               dataType='boolean', default=False)
        .param('allowRename', 'Allow to modify "name" if object with the same name'
               'already exists.', required=False, dataType='boolean', default=False)
        .errorResponse('Access was denied (if current user does not have write access'
                       ' to this tale)', 403)
        .errorResponse('Another version is being created. Try again later.', 409)
        .errorResponse('Illegal file name', 400)
        .errorResponse('See other (if tale workspace has not been changed since the last '
                       'checkpoint). The response will contain a typical error message body, which '
                       'is a JSON object. This object will have an "extra" attribute containing'
                       'the id of the version that represents this last checkpoint.', 303)
    )
    def create(
        self,
        tale: dict,
        name: str = None,
        force: bool = False,
        allowRename: bool = False
    ) -> dict:
        if not name:
            name = self._generateName()
        user = self.getCurrentUser()

        root = self._getRootFromTale(tale, user=user, level=AccessType.WRITE)
        name = self._checkNameSanity(name, root, allow_rename=allowRename)

        if not Version._setCriticalSectionFlag(root):
            raise RestException('Another operation is in progress. Try again later.', 409)
        try:
            rootDir = util.getTaleVersionsDirPath(tale)
            return self._create(tale, name, rootDir, root, user=user, force=force)
        finally:
            # probably need a better way to deal with hard crashes here
            Version._resetCriticalSectionFlag(root)
            Tale().updateTale(tale)

    @access.user(TokenScope.DATA_WRITE)
    @filtermodel(model="tale", plugin="wholetale")
    @autoDescribeRoute(
        Description("Restores a version.")
        .modelParam(
            "id",
            "The ID of the Tale to be modified.",
            model=Tale,
            level=AccessType.WRITE,
            destName="tale"
        )
        .modelParam(
            "versionId",
            "The ID of version folder",
            model=Folder,
            level=AccessType.READ,
            destName="version",
            paramType="query"
        )
        .errorResponse("Access was denied (if current user does not have write access to this "
                       "tale)", 403)
        .errorResponse("Version is in use by a run and cannot be deleted.", 461)
    )
    def restore(self, tale: dict, version: dict):
        user = self.getCurrentUser()
        version_root = Folder().load(version["parentId"], user=user, level=AccessType.READ)

        workspace = Folder().load(tale["workspaceId"], force=True)
        workspace_path = Path(workspace["fsPath"])
        version = Folder().load(version["_id"], force=True, fields=["fsPath"])
        version_workspace_path = Path(version["fsPath"]) / "workspace"

        if not Version._setCriticalSectionFlag(version_root):
            raise RestException('Another operation is in progress. Try again later.', 409)
        try:
            # restore workspace
            shutil.rmtree(workspace_path)
            workspace_path.mkdir()
            self._snapshotRecursive(None, version_workspace_path, workspace_path)
            # restore Tale
            tale.update(self._restoreTaleFromVersion(version))
            return Tale().save(tale)
        finally:
            # probably need a better way to deal with hard crashes here
            Version._resetCriticalSectionFlag(version_root)

    @access.user(TokenScope.DATA_READ)
    @filtermodel(model="tale", plugin="wholetale")
    @autoDescribeRoute(
        Description("Returns a Tale object based on a version.")
        .notes("It does not modify the state of the Tale. It is just a 'mocked' view.")
        .modelParam(
            "id",
            "The ID of the Tale",
            model=Tale,
            level=AccessType.READ,
            destName="tale",
        )
        .modelParam(
            "versionId",
            "The ID of version folder",
            model=Folder,
            level=AccessType.READ,
            destName="version",
            paramType="query",
        )
        .errorResponse(
            "Access was denied (if current user does not have read access to this "
            "tale)",
            403,
        )
    )
    def restoreView(self, tale: dict, version: dict):
        version = Folder().load(version["_id"], force=True, fields=["fsPath"])
        tale.update(self._restoreTaleFromVersion(version))
        return tale

    def _restoreTaleFromVersion(self, version, annotate=True):
        version_path = Path(version["fsPath"])
        with open((version_path / "manifest.json").as_posix(), "r") as fp:
            manifest = json.load(fp)
        with open((version_path / "environment.json").as_posix(), "r") as fp:
            env = json.load(fp)
        restored_tale = Tale().restoreTale(manifest, env)
        if annotate:
            restored_tale["restoredFrom"] = version["_id"]
        return restored_tale

    @access.user(TokenScope.DATA_WRITE)
    @autoDescribeRoute(
        Description('Deletes a version.')
        .modelParam('id', 'The ID of version folder', model=Folder, level=AccessType.WRITE,
                    destName='vfolder')
        .errorResponse('Access was denied (if current user does not have write access to this '
                       'tale)', 403)
        .errorResponse('Version is in use by a run and cannot be deleted.', 461)
    )
    def delete(self, vfolder: dict) -> None:
        root = Folder().load(vfolder['parentId'], force=True)
        Version._setCriticalSectionFlag(root)
        try:
            # make sure we use information protected by the critical section
            vfolder = Folder().load(vfolder['_id'], force=True)
            if FIELD_REFERENCE_COUNTER in vfolder and vfolder[FIELD_REFERENCE_COUNTER] > 0:
                raise RestException('Version is in use by a run and cannot be deleted.', 461)
        finally:
            Version._resetCriticalSectionFlag(root)

        path = Path(vfolder['fsPath'])
        trashDir = path.parent / '.trash'
        Folder().remove(vfolder)

        shutil.move(path.as_posix(), trashDir)
        Tale().updateTale(Tale().load(root["taleId"], force=True))

    @access.user(TokenScope.DATA_READ)
    @filtermodel('folder')
    @autoDescribeRoute(
        Description('Lists versions.')
        .modelParam('taleId', 'The ID of a tale for which versions are to be listed.',
                    model=Tale, plugin='wholetale', level=AccessType.READ,
                    destName='tale', paramType='query')
        .pagingParams(defaultSort='created')
        .errorResponse('Access was denied (if current user does not have read access to this tale)',
                       403)
    )
    def list(self, tale: dict, limit, offset, sort):
        return super().list(tale, user=self.getCurrentUser(), limit=limit, offset=offset, sort=sort)

    @access.user(TokenScope.DATA_READ)
    @autoDescribeRoute(
        Description('Check if a version with the given name exists.')
        .modelParam('taleId', 'The ID of versions root folder.', model=Tale, level=AccessType.READ,
                    destName='tale', paramType='query')
        .param('name', 'Return the folder with this name or nothing if no such folder exists.',
               required=False, dataType='string')
        .errorResponse('Access was denied (if current user does not have read access to this tale)',
                       403)
    )
    def exists(self, tale: dict, name: str):
        return super().exists(tale, name)

    @access.user(scope=TokenScope.DATA_WRITE)
    def ensure_version(self, event: events.Event):
        params = event.info.get("params", {})
        taleId = event.info.get("id")
        version_id = params.get("versionId")
        if not version_id:
            try:
                version = self.create(taleId=taleId, allowRename=True, params={})
                # Above obj is filtered model so we need to reload it...
                version = Folder().load(version["_id"], force=True)
            except RestException as exc:
                if exc.code == 303:
                    version = Folder().load(exc.extra, force=True)
                else:
                    raise
            # We're using 'updated' field to bump the version to the top of
            # Folder().list(). We're gonna update it either way later on.
            Folder().updateFolder(version)

    @classmethod
    def _incrementReferenceCount(cls, vfolder):
        if FIELD_REFERENCE_COUNTER not in vfolder:
            vfolder[FIELD_REFERENCE_COUNTER] = 0
        cls._updateReferenceCount(vfolder, 1)

    @classmethod
    def _decrementReferenceCount(cls, vfolder):
        cls._updateReferenceCount(vfolder, -1)

    @classmethod
    def _updateReferenceCount(cls, vfolder: dict, n: int):
        root = Folder().load(vfolder['parentId'], force=True)
        cls._setCriticalSectionFlag(root)
        try:
            vfolder[FIELD_REFERENCE_COUNTER] += n
            vfolder = Folder().save(vfolder)
        except KeyError:
            pass
        finally:
            cls._resetCriticalSectionFlag(root)

    @classmethod
    def _setCriticalSectionFlag(cls, root: dict) -> bool:
        return cls._updateCriticalSectionFlag(root, True)

    @classmethod
    def _resetCriticalSectionFlag(cls, root: dict) -> bool:
        return cls._updateCriticalSectionFlag(root, False)

    @classmethod
    def _updateCriticalSectionFlag(cls, root: dict, value: bool) -> bool:
        result = Folder().update(
            query={
                '_id': root['_id'],
                FIELD_CRITICAL_SECTION_FLAG: {'$ne': value}
            },
            update={
                '$set': {
                    FIELD_CRITICAL_SECTION_FLAG: value
                },
                '$inc': {
                    FIELD_SEQENCE_NUMBER: 1
                }
            },
            multi=False)
        return result.matched_count > 0

    def _create(
        self, tale: dict, name: Optional[str], versionsDir: Path,
        versionsRoot: dict, user=None, force=False
    ) -> dict:
        last = self._getLastVersion(versionsRoot)
        last_restore = Folder().load(tale.get("restoredFrom", ObjectId()), force=True)
        workspace = Folder().load(tale["workspaceId"], force=True)
        crtWorkspace = Path(workspace["fsPath"])

        # NOTE: order is important, we want oldWorkspace -> last.workspace
        for version in (last_restore, last):
            oldWorkspace = None if version is None else Path(version["fsPath"]) / "workspace"
            if not force and self._is_same(tale, version, user) and \
                    self._sameTree(oldWorkspace, crtWorkspace):
                assert version is not None
                raise RestException('Not modified', code=303, extra=str(version['_id']))

        new_version = self._createSubdir(versionsDir, versionsRoot, name, user=user)

        try:
            self.snapshot(last, tale, new_version, user=user, force=force)
            return new_version
        except Exception:  # NOQA
            try:
                shutil.rmtree(new_version["fsPath"])
                Folder().remove(new_version)
            except Exception as ex:  # NOQA
                logger.warning('Exception caught while rolling back version ckeckpoint.', ex)
            raise

    def _getLastVersion(self, versionsFolder: dict) -> Optional[dict]:
        # The versions root folder is kept as a pure Girder folder.
        # This is because there is no efficient way to
        # say "give me the latest subdir" on a POSIX filesystem.
        return Folder().findOne(
            {'parentId': versionsFolder['_id']}, sort=[('created', pymongo.DESCENDING)]
        )

    def _generateName(self):
        now = datetime.now()
        return now.strftime(VERSION_NAME_FORMAT)

    def snapshot(
        self,
        version: Optional[dict],
        tale: dict,
        new_version: dict,
        user=None,
        force=False
    ) -> None:
        """Creates a new version from the current state and an old version. The implementation
        here differs a bit from
        https://docs.google.com/document/d/1b2xZtIYvgVXz7EVeV-C18So_a7QLGg59dPQMxvBcA5o since
        the document assumes traditional use of Girder objects to simulate a filesystem, whereas
        the current reality is that we are moving more towards Girder being a thin layer on top
        of an actual FS (i.e. virtual_resources). In particular, the data folder remains in the
        domain of the DMS, meaning that actual files are only downloaded on demand. The current
        implementation of the virtual objects does not seem to have a straightforward way of
        embedding pure girder folders inside a virtual tree. The solution currently adopted to
        address this issue involves storing the dataset in the version folder itself, which, for
        efficiency reasons remains a Girder folder (but also a virtual_resources root).

        It may be relevant to note that this implementation uses option (b) in the above document
        with respect to the meaning of "copy" in step 4.1.2.1. To be more precise, when a file is
        changed in the current workspace, the new version will hard link to the file in question
        instead of doing an actual copy. This allows for O(1) equality comparisons between files,
        but requires that modifications to files in the workspace always create a new file (which
        is the case if files are only modified through the WebDAV FS mounted in a tale container).
        """
        new_version_path = Path(new_version["fsPath"])
        manifest = Manifest(tale, user, versionId=new_version["_id"], expand_folders=False)
        with open((new_version_path / "manifest.json").as_posix(), "w") as fp:
            fp.write(manifest.dump_manifest())

        with open((new_version_path / "environment.json").as_posix(), "w") as fp:
            fp.write(manifest.dump_environment())

        oldWorkspace = None if version is None else Path(version["fsPath"]) / "workspace"
        workspace = Folder().load(tale["workspaceId"], force=True)
        crtWorkspace = Path(workspace["fsPath"])
        newWorkspace = new_version_path / 'workspace'
        newWorkspace.mkdir()
        self._snapshotRecursive(oldWorkspace, crtWorkspace, newWorkspace)

    def _is_same(self, tale, version, user):
        workspace = Folder().load(tale["workspaceId"], force=True)
        tale_workspace_path = Path(workspace["fsPath"])

        version_path = None if version is None else Path(version["fsPath"])
        version_workspace_path = None if version_path is None else version_path / "workspace"

        manifest_obj = Manifest(tale, user)
        manifest = json.loads(manifest_obj.dump_manifest())
        environment = json.loads(manifest_obj.dump_environment())
        tale_restored_from_wrk = Tale().restoreTale(manifest, environment)
        tale_restored_from_ver = \
            self._restoreTaleFromVersion(version, annotate=False) if version else None

        if self._sameTaleMetadata(tale_restored_from_ver, tale_restored_from_wrk) and \
                self._sameTree(version_workspace_path, tale_workspace_path):
            raise RestException('Not modified', code=303, extra=str(version["_id"]))

    def _sameTaleMetadata(self, old: Optional[dict], crt: dict):
        if old is None:
            return False
        return old == crt

    def _sameTree(self, old: Optional[Path], crt: Path) -> bool:
        if old is None:
            return False
        for c in crt.iterdir():
            oldc = old / c.name
            crtc = crt / c.name

            if not oldc.exists():
                return False

            if crtc.is_dir() != oldc.is_dir():
                return False

            if crtc.is_dir():
                if not self._sameTree(oldc, crtc):
                    return False
            else:
                if not oldc.samefile(crtc):
                    return False

        return True
