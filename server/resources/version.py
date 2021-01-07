import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import pymongo

from girder import logger
from girder.api import access
from girder.api.describe import autoDescribeRoute, Description
from girder.api.rest import filtermodel
from girder.constants import TokenScope
from girder.exceptions import RestException
from girder.models.folder import Folder
from girder.plugins.wt_data_manager.models.session import Session
from girder.plugins.wholetale.models.tale import Tale
from .abstract_resource import AbstractVRResource
from ..constants import Constants
from ..lib import util

FIELD_CRITICAL_SECTION_FLAG = 'versionsCriticalSectionFlag'
FIELD_REFERENCE_COUNTER = 'versionsRefCount'
FIELD_SEQENCE_NUMBER = 'seq'
VERSION_NAME_FORMAT = '%c'


class Version(AbstractVRResource):
    def __init__(self):
        super().__init__('version', Constants.VERSIONS_ROOT_DIR_NAME)
        self.route('GET', (':id', 'dataSet'), self.getDataset)

    @access.admin(TokenScope.DATA_WRITE)
    @autoDescribeRoute(
        Description('Clears all versions from a tale, but does not delete the respective '
                    'directories on disk. This is an administrative operation and should not be'
                    'used under normal circumstances.')
        .modelParam('taleId', 'The ID of the tale for which the versions should be cleared', model=Tale,
               force=True, destName='tale', paramType='query')
    )
    def clear(self, tale: dict) -> None:
        super().clear(tale)

    @access.user(TokenScope.DATA_WRITE)
    @filtermodel('folder')
    @autoDescribeRoute(
        Description('Rename a version. Returns the renamed version '
                    'folder')
        .modelParam('id', 'The ID of version', model=Folder, force=True,
                    destName='vfolder')
        .param('name', 'The new name', required=True, dataType='string')
        .errorResponse('Access was denied (if current user does not have write access to this '
                       'tale)', 403)
        .errorResponse('Illegal file name', 400)
        .errorResponse('Name already exists', 409)
    )
    def rename(self, vfolder: dict, name: str) -> dict:
        return super().rename(vfolder, name)

    @access.user(TokenScope.DATA_READ)
    @autoDescribeRoute(
        Description('Returns the dataset associated with a version, but with some additional '
                    'entries such as the type of object (folder/item) and the object dictionaries.')
        .modelParam('id', 'The ID of a version', model=Folder, force=True,
                    destName='vfolder')
        .errorResponse('Access was denied (if current user does not have read access to the '
                       'respective version folder.', 403)
    )
    def getDataset(self, vfolder: dict) -> dict:
        self._checkAccess(vfolder, model='folder', model_plugin=None)
        dataSet = vfolder['dataSet']
        Session().loadObjects(dataSet)
        return dataSet

    @access.user(TokenScope.DATA_READ)
    @filtermodel("folder")
    @autoDescribeRoute(
        Description('Returns a version.')
        .modelParam('id', 'The ID of a version', model=Folder, force=True,
                    destName='vfolder')
        .errorResponse('Access was denied (if current user does not have read access to the '
                       'respective version folder.', 403)
    )
    def load(self, vfolder: dict) -> dict:
        return super().load(vfolder)

    @access.user(TokenScope.DATA_WRITE)
    @filtermodel('folder')
    @autoDescribeRoute(
        Description('Creates a new version of a tale. Returns the new version folder.')
        .modelParam('taleId', 'A tale requesting the creation of a new version.',
                    model=Tale, force=True, destName='tale', paramType='query')
        .param('name', 'An optional name for the version. If not specified, a name will be '
                       'generated from the current date and time.', required=False,
               dataType='string')
        .param('force', 'Force creation of a version even if no files were modified in the '
                        'workspace since the last version was created.', required=False,
               dataType='boolean', default=False)
        .errorResponse('Access was denied (if current user does not have write access to this tale)',
                       403)
        .errorResponse('Another version is being created. Try again later.', 409)
        .errorResponse('Illegal file name', 400)
        .errorResponse('See other (if tale workspace has not been changed since the last '
                       'checkpoint). The response will contain a typical error message body, which '
                       'is a JSON object. This object will have an "extra" attribute containing'
                       'the id of the version that represents this last checkpoint.', 303)
    )
    def create(self, tale: dict, name: str = None, force: bool = False) -> dict:
        self._checkAccess(tale, model='tale', model_plugin='wholetale')
        root = self._getRootFromTale(tale)
        self._checkNameSanity(name, root)

        if not Version._setCriticalSectionFlag(root):
            raise RestException('Another operation is in progress. Try again later.', 409)
        try:
            rootDir = util.getTaleVersionsDirPath(tale)
            return self._create(tale, name, rootDir, root, force)
        finally:
            # probably need a better way to deal with hard crashes here
            Version._resetCriticalSectionFlag(root)

    @access.user(TokenScope.DATA_WRITE)
    @autoDescribeRoute(
        Description('Deletes a version.')
        .modelParam('id', 'The ID of version folder', model=Folder, force=True,
                    destName='vfolder')
        .errorResponse('Access was denied (if current user does not have write access to this '
                       'tale)', 403)
        .errorResponse('Version is in use by a run and cannot be deleted.', 461)
    )
    def delete(self, vfolder: dict) -> None:
        self._checkAccess(vfolder)

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

    @access.user(TokenScope.DATA_READ)
    @filtermodel('folder')
    @autoDescribeRoute(
        Description('Lists versions.')
        .modelParam('taleId', 'The ID of a tale for which versions are to be listed.',
                    model=Tale, plugin='wholetale', force=True, destName='tale', paramType='query')
        .pagingParams(defaultSort='created')
        .errorResponse('Access was denied (if current user does not have read access to this tale)',
                       403)
    )
    def list(self, tale: dict, limit, offset, sort):
        return super().list(tale, limit, offset, sort)

    @access.user(TokenScope.DATA_READ)
    @autoDescribeRoute(
        Description('Check if a version with the given name exists.')
        .modelParam('taleId', 'The ID of versions root folder.', model=Tale, force=True,
                    destName='tale', paramType='query')
        .param('name', 'Return the folder with this name or nothing if no such folder exists.',
               required=False, dataType='string')
        .errorResponse('Access was denied (if current user does not have read access to this tale)',
                       403)
    )
    def exists(self, tale: dict, name: str):
        return super().exists(tale, name)

    @classmethod
    def _incrementReferenceCount(cls, vfolder):
        cls._updateReferenceCount(vfolder, 1)

    @classmethod
    def _decrementReferenceCount(cls, vfolder):
        cls._updateReferenceCount(vfolder, -1)

    @classmethod
    def _updateReferenceCount(cls, vfolder: dict, n: int):
        root = Folder().load(vfolder['parentId'])
        cls._setCriticalSectionFlag(root)
        try:
            vfolder = Folder().load(vfolder['_id'], force=True)
            if FIELD_REFERENCE_COUNTER in vfolder:
                vfolder[FIELD_REFERENCE_COUNTER] += n
                Folder().save(vfolder)
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

    def _create(self, tale: dict, name: Optional[str], versionsDir: Path,
                versionsRoot: dict, force: bool) -> dict:
        if not name:
            name = self._generateName()

        last = self._getLastVersion(versionsRoot)

        if last is not None:
            oldVersion = Path(last['fsPath'])  # type: Optional[Path]
            oldDataset = last['dataSet']  # type: Optional[List[dict]]
        else:
            oldVersion = None
            oldDataset = None

        (newVersionFolder, newVersionDir) = self._createSubdir(versionsDir, versionsRoot, name)

        try:
            dataSet = tale['dataSet']

            taleWorkspaceDir = util.getTaleWorkspaceDirPath(tale)

            self.snapshot(last, oldVersion, oldDataset, dataSet, taleWorkspaceDir, newVersionDir,
                          newVersionFolder, force)
            return newVersionFolder
        except Exception:
            try:
                shutil.rmtree(newVersionDir)
                Folder().remove(newVersionFolder)
            except Exception as ex:
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

    def snapshot(self, oldVersionFolder: Optional[dict], oldVersion: Optional[Path],
                 oldData: Optional[List[dict]], crtData: List[dict], crtWorkspace: Path,
                 newVersion: Path, newVersionFolder: dict, force: bool) -> None:
        '''Creates a new version from the current state and an old version. The implementation
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
        '''

        oldWorkspace = None if oldVersion is None else oldVersion / 'workspace'

        if not force and self._sameData(oldData, crtData) and \
                self._sameTree(oldWorkspace, crtWorkspace):
            assert oldVersionFolder is not None
            raise RestException('Not modified', 303, str(oldVersionFolder['_id']))
        dataDir = newVersion / 'data'
        dataDir.mkdir()

        # TODO: may want to have a dataSet model and avoid all the duplication
        newVersionFolder['dataSet'] = crtData.copy()
        Folder().save(newVersionFolder, False)

        newWorkspace = newVersion / 'workspace'
        newWorkspace.mkdir()

        self._snapshotRecursive(oldWorkspace, crtWorkspace, newWorkspace)

    def _snapshotRecursive(self, old: Optional[Path], crt: Path, new: Path) -> None:
        for c in crt.iterdir():
            newc = new / c.name
            oldc = None if old is None else old / c.name
            crtc = crt / c.name

            if oldc is not None:
                if not oldc.exists():
                    oldc = None
                else:
                    if crtc.is_dir() != oldc.is_dir():
                        # either oldc was a dir and is now a file or the other way around
                        oldc = None

            if c.is_dir():
                newc.mkdir()
                self._snapshotRecursive(oldc, crtc, newc)
            else:
                crtcstr = crtc.absolute().as_posix()
                newcstr = newc.absolute().as_posix()
                try:
                    os.link(crtcstr, newcstr)
                except:  # noqa: E722
                    logger.warn('link %s -> %s' % (crtcstr, newcstr))
                    raise
                shutil.copystat(crtcstr, newcstr)

    def _sameData(self, old: Optional[List[dict]], crt: List[dict]):
        if old is None:
            return False
        if len(old) != len(crt):
            return False

        for i in range(len(old)):
            oldc = old[i]
            crtc = crt[i]

            if oldc['itemId'] != crtc['itemId']:
                return False
            if oldc['mountPath'] != oldc['mountPath']:
                return False

        return True

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
                if not self._isSame(oldc, crtc):
                    return False
            else:
                if not oldc.samefile(crtc):
                    return False

        return True
