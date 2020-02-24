import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Tuple, List

import pathvalidate
import pymongo

from girder import logger
from girder.api import access
from girder.api.describe import autoDescribeRoute, Description
from girder.api.rest import Resource, filtermodel
from girder.constants import TokenScope
from girder.exceptions import RestException
from girder.models.folder import Folder
from girder.plugins.wholetale.models.instance import Instance
from girder.plugins.wholetale.models.tale import Tale
from girder.plugins.wt_data_manager.models.session import Session
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

    @access.user()
    @filtermodel('folder')
    @autoDescribeRoute(
        Description('Retrieves the versions root folder for this instance.')
            .modelParam('instanceId', 'The ID of a tale instance', model=Instance, force=True)
            .errorResponse(
            'Access was denied (if current user does not have write access to this tale '
            'instance)', 403)
    )
    def getRoot(self, instance: dict) -> dict:
        # So we're overriding this because the description above has 'version' in it.
        # This is also where we see the trouble with over-reliance on decorators: doesn't work
        #   too well with inheritance.
        # On the other hand, this could be solved by a modified decorator and some voodoo, but
        # that's probably less maintainable than just copying and pasting descriptions
        return super().getRoot(instance)

    @access.admin(TokenScope.DATA_WRITE)
    @autoDescribeRoute(
        Description('Clears all versions from an instance, but does not delete the respective '
                    'directories on disk. This is an administrative operation and should not be'
                    'used under normal circumstances.')
            .modelParam('rootId', 'The ID of the versions root folder', model=Folder, force=True,
                        destName='root')
    )
    def clear(self, root: dict) -> None:
        super().clear(root)

    @access.user(TokenScope.DATA_WRITE)
    @filtermodel('folder')
    @autoDescribeRoute(
        Description('Rename a version associated with a tale instance. Returns the renamed version '
                    'folder')
            .modelParam('id', 'The ID of version folder', model=Folder, force=True,
                        destName='vfolder')
            .param('newName', 'The new name', required=True, dataType='string')
            .errorResponse(
            'Access was denied (if current user does not have write access to this tale '
            'instance)', 403)
            .errorResponse('Illegal file name', 400)
    )
    def rename(self, vfolder: dict, newName: str) -> dict:
        return super().rename(vfolder, newName)

    @access.user(TokenScope.DATA_READ)
    @autoDescribeRoute(
        Description('Returns the dataset associated with a version folder, but with some additional'
                    'entries such as the type of object (folder/item) and the object dictionaries.')
            .modelParam('id', 'The ID of a version folder', model=Folder, force=True,
                        destName='vfolder')
            .errorResponse(
            'Access was denied (if current user does not have read access to the respective version '
            'folder.', 403)
    )
    def getDataset(self, vfolder: dict) -> dict:
        self._checkAccess(vfolder, model='folder', model_plugin=None)
        dataSet = vfolder['dataSet']
        Session().loadObjects(dataSet)
        return dataSet

    @access.user(TokenScope.DATA_READ)
    @autoDescribeRoute(
        Description('Returns a version folder.')
            .modelParam('versionId', 'The ID of a version folder', model=Folder, force=True,
                        destName='vfolder')
            .errorResponse(
            'Access was denied (if current user does not have read access to the respective version '
            'folder.', 403)
    )
    def load(self, vfolder: dict) -> dict:
        return super().load(vfolder)

    @access.user(TokenScope.DATA_WRITE)
    @filtermodel('folder')
    @autoDescribeRoute(
        Description('Creates a new version of a tale. Returns the new version folder.')
        .modelParam('instanceId', 'A tale instance requesting the creation of a new version.',
                    model=Instance, force=True, destName='instance')
        .param('name', 'An optional name for the version. If not specified, a name will be '
                       'generated from the current date and time.', required=False,
               dataType='string')
        .param('force', 'Force creation of a version even if no files were modified in the '
                        'workspace since the last version was created.', required=False,
               dataType='boolean', default=False)
        .errorResponse('Access was denied (if current user does not have write access to this tale '
                       'instance)', 403)
        .errorResponse('Another version is being created. Try again later.', 409)
        .errorResponse('Illegal file name', 400)
        .errorResponse('See other (if tale workspace has not been changed since the last '
                       'checkpoint). The response will contain a typical error message body, which '
                       'is a JSON object. This object will have an "extra" attribute containing'
                       'the id of the version that represents this last checkpoint.', 303)
    )
    def create(self, instance: dict, name: str = None, force: bool = False) -> dict:
        self._checkAccess(instance, model='instance', model_plugin='wholetale')
        (tale, root) = self._getTaleAndRoot(instance)
        self._checkNameSanity(name, root)

        if not self._setCriticalSectionFlag(root):
            raise RestException('Another operation is in progress. Try again later.', 409)
        try:
            rootDir = util.getTaleVersionsDirPath(tale)
            return self._create(instance, tale, name, rootDir, root, force)
        finally:
            # probably need a better way to deal with hard crashes here
            self._resetCriticalSectionFlag(root)

    @access.user(TokenScope.DATA_WRITE)
    @autoDescribeRoute(
        Description('Deletes a version.')
            .modelParam('versionId', 'The ID of version folder', model=Folder, force=True,
                        destName='vfolder')
            .errorResponse('Access was denied (if current user does not have write access to this '
                           'tale instance)', 403)
            .errorResponse('Version is in use by a run and cannot be deleted.', 461)
    )
    def delete(self, vfolder: dict) -> None:
        self._checkAccess(vfolder)

        root = Folder().load(vfolder['parentId'], force=True)
        self._setCriticalSectionFlag(root)
        try:
            # make sure we use information protected by the critical section
            vfolder = Folder().load(vfolder['_id'], Force=True)
            if FIELD_REFERENCE_COUNTER in vfolder and vfolder[FIELD_REFERENCE_COUNTER] > 0:
                raise RestException('Version is in use by a run and cannot be deleted.', 461)
        finally:
            self._resetCriticalSectionFlag(root)


        path = Path(vfolder['fsPath'])
        trashDir = path.parent / '.trash'
        Folder().remove(vfolder)

        shutil.move(path.as_posix(), trashDir)

    @access.user(TokenScope.DATA_READ)
    @filtermodel('folder')
    @autoDescribeRoute(
        Description('Lists all versions.')
            .modelParam('rootId', 'The ID of versions root folder.', model=Folder, force=True,
                        destName='root')
            .pagingParams(defaultSort='created')
            .errorResponse(
            'Access was denied (if current user does not have read access to this tale '
            'instance)', 403)
    )
    def list(self, root: dict, limit, offset, sort):
        return super().list(root, limit, offset, sort)

    @access.user(TokenScope.DATA_READ)
    @filtermodel('folder')
    @autoDescribeRoute(
        Description('Check if a version exists.')
            .modelParam('rootId', 'The ID of versions root folder.', model=Folder, force=True,
                        destName='root')
            .param('name', 'Return the folder with this name or nothing if no such folder exists.',
                   required=False, dataType='string')
            .errorResponse(
            'Access was denied (if current user does not have read access to this tale '
            'instance)', 403)
    )
    def exists(self, root: dict, name: str):
        return super().exists(root, name)

    def _setCriticalSectionFlag(self, root: dict) -> bool:
        return self._updateCriticalSectionFlag(root, True)

    def _resetCriticalSectionFlag(self, root: dict) -> bool:
        return self._updateCriticalSectionFlag(root, False)

    def _updateCriticalSectionFlag(self, root: dict, value: bool) -> bool:
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

    def _create(self, instance: dict, tale: dict, name: str, versionsDir: Path,
                versionsRoot: dict, force: bool) -> None:
        ro = True
        if name is None:
            ro = False
            name = self._generateName()

        last = self._getLastVersion(versionsRoot)

        if last is not None:
            oldVersion = Path(last['fsPath'])
            oldDataset = last['dataSet']
        else:
            oldVersion = None
            oldDataset = None

        (newVersionFolder, newVersionDir) = self._createSubDir(versionsDir, versionsRoot, name)

        session = Session().findOne({'_id': instance['sessionId']})
        dataSet = session['dataSet']

        taleWorkspaceDir = util.getTaleWorkspaceDirPath(tale)

        self.snapshot(last, oldVersion, oldDataset, dataSet, taleWorkspaceDir, newVersionDir,
                      newVersionFolder, force)
        return newVersionFolder

    def _getLastVersion(self, versionsFolder: dict) -> dict:
        # The versions root folder is kept as a pure Girder folder. This is because there is no
        # efficient way to say "give me the latest subdir" on a POSIX filesystem.
        try:
            return Folder().find({'parentId': versionsFolder['_id']}, limit=1,
                                 sort=[('created', pymongo.DESCENDING)])[0]
        except IndexError:
            return None

    def _generateName(self):
        now = datetime.now()
        return now.strftime(VERSION_NAME_FORMAT)

    def snapshot(self, oldVersionFolder: dict, oldVersion: Path, oldData: List[dict],
                 crtData: List[dict], crtWorkspace: Path, newVersion: Path, newVersionFolder: dict,
                 force: bool) -> None:
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
        efficiency reasons remains a Girder folder (but also a virtual_resources root).'''

        oldWorkspace = None if oldVersion is None else oldVersion / 'workspace'
        try:
            if not force and self._sameData(oldData, crtData) and \
                    self._sameTree(oldWorkspace, crtWorkspace):
                raise RestException('Not modified', 303, str(oldVersionFolder['_id']))
            dataDir = newVersion / 'data'
            dataDir.mkdir()

            # TODO: may want to have a dataSet model and avoid all the duplication
            newVersionFolder['dataSet'] = crtData.copy()
            Folder().save(newVersionFolder, False)

            newWorkspace = newVersion / 'workspace'
            newWorkspace.mkdir()

            self._snapshotRecursive(oldWorkspace, crtWorkspace, newWorkspace)
        except:
            try:
                shutil.rmtree(newVersion.absolute().as_posix())
                Folder().remove(newVersionFolder)
            except Exception as ex:
                logger.warning('Exception caught while rolling back version ckeckpoint.', ex)
            raise

    def _snapshotRecursive(self, old: Path, crt: Path, new: Path) -> None:
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
                os.link(crtcstr, newcstr)
                shutil.copystat(crtcstr, newcstr)

    def _sameData(self, old: List[dict], crt: List[dict]):
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

    def _sameTree(self, old: Path, crt: Path) -> bool:
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
