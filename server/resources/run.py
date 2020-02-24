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
from girder.api.rest import filtermodel
from girder.constants import TokenScope
from girder.exceptions import RestException
from girder.models.folder import Folder
from girder.plugins.wholetale.models.instance import Instance
from girder.plugins.wholetale.models.tale import Tale
from girder.plugins.wholetale.utils import getOrCreateRootFolder
from girder.plugins.wt_data_manager.models.session import Session
from .abstract_resource import AbstractVRResource
from ..constants import Constants, RunStatus
from ..lib import util


FIELD_SEQENCE_NUMBER = 'seq'
FIELD_STATUS_CODE = 'runStatusCode'
RUN_NAME_FORMAT = '%c'


class Run(AbstractVRResource):
    def __init__(self):
        super().__init__('run', Constants.RUNS_ROOT_DIR_NAME)
        self.route('PATCH', (':id', 'stream'), self.stream)
        self.route('PATCH', (':id', 'status'), self.setStatus)
        self.route('GET', (':id', 'status'), self.status)


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
        return super().getRoot(instance)

    @access.admin(TokenScope.DATA_WRITE)
    @autoDescribeRoute(
        Description('Clears all runs from an instance, but does not delete the respective '
                    'directories on disk. This is an administrative operation and should not be'
                    'used under normal circumstances.')
            .modelParam('rootId', 'The ID of the runs root folder', model=Folder, force=True,
                        destName='root')
    )
    def clear(self, root: dict) -> None:
        super().clear(root)

    @access.user(TokenScope.DATA_WRITE)
    @filtermodel('folder')
    @autoDescribeRoute(
        Description('Rename a run associated with a tale instance. Returns the renamed run folder')
            .modelParam('id', 'The ID of run folder', model=Folder, force=True,
                        destName='rfolder')
            .param('newName', 'The new name', required=True, dataType='string')
            .errorResponse(
            'Access was denied (if current user does not have write access to this tale '
            'instance)', 403)
            .errorResponse('Illegal file name', 400)
    )
    def rename(self, rfolder: dict, newName: str) -> dict:
        return super().rename(rfolder, newName)

    @access.user(TokenScope.DATA_READ)
    @autoDescribeRoute(
        Description('Returns a runs folder.')
            .modelParam('runId', 'The ID of a runs folder', model=Folder, force=True,
                        destName='rfolder')
            .errorResponse(
            'Access was denied (if current user does not have read access to the respective run '
            'folder.', 403)
    )
    def load(self, rfolder: dict) -> dict:
        return super().load(rfolder)

    @access.user(TokenScope.DATA_WRITE)
    @filtermodel('folder')
    @autoDescribeRoute(
        Description('Creates a new empty run associated with a given version and returns the new '
                    'run folder. This does not actually start any computation.')
        .modelParam('versionId', 'A version to create the run from.', model=Folder, force=True,
                    destName='version')
        .param('name', 'An optional name for the run. If not specified, a name will be '
                       'generated from the current date and time.', required=False,
               dataType='string')
        .errorResponse('Access was denied (if current user does not have write access to the tale '
                       'instance associated with this version)', 403)
        .errorResponse('Illegal file name', 400)
    )
    def create(self, version: dict, name: str = None) -> dict:
        versionsRoot = Folder().load(version['parentId'], force=True)
        instance = Instance().load(versionsRoot['instanceId'], force=True)

        (tale, root) = self._getTaleAndRoot(instance)
        self._checkAccess(root)
        self._checkNameSanity(name, root)

        rootDir = util.getTaleRootDirPath(tale)

        return self._create(version, name, root, rootDir)

    @access.user(TokenScope.DATA_WRITE)
    @autoDescribeRoute(
        Description('Deletes a run.')
            .modelParam('runId', 'The ID of run folder', model=Folder, force=True,
                        destName='rfolder')
            .errorResponse(
            'Access was denied (if current user does not have write access to this tale instance)',
            403)
    )
    def delete(self, rfolder: dict) -> None:
        self._checkAccess(rfolder)

        path = Path(rfolder['fsPath'])
        trashDir = path.parent / '.trash'
        Folder().remove(rfolder)

        shutil.move(path.as_posix(), trashDir)

    @access.user(TokenScope.DATA_READ)
    @filtermodel('folder')
    @autoDescribeRoute(
        Description('Lists all runs.')
            .modelParam('rootId', 'The ID of runs root folder.', model=Folder, force=True,
                        destName='root')
            .pagingParams(defaultSort='created')
            .errorResponse(
            'Access was denied (if current user does not have read access to this tale instance)',
            403)
    )
    def list(self, root: dict, limit, offset, sort):
        return super().list(root, limit, offset, sort)

    @access.user(TokenScope.DATA_READ)
    @filtermodel('folder')
    @autoDescribeRoute(
        Description('Check if a run exists.')
            .modelParam('rootId', 'The ID of runs root folder.', model=Folder, force=True,
                        destName='root')
            .param('name', 'Return the folder with this name or nothing if no such folder exists.',
                   required=False, dataType='string')
            .errorResponse(
            'Access was denied (if current user does not have read access to this tale instance)',
            403)
    )
    def exists(self, root: dict, name: str):
        return super().exists(root, name)

    @access.user(TokenScope.DATA_READ)
    @autoDescribeRoute(
        Description('Returns the status of a run in an object with two fields: status and '
                    'statusString. The possible values for status, an integer, are 0, 1, 2, 3, 4, '
                    '5, with statusString being, respectively, UNKNOWN, STARTING, RUNNING, '
                    'COMPLETED, FAILED, CANCELLED.')
            .modelParam('runId', 'The ID of a run.', model=Folder, force=True, destName='run')
            .errorResponse(
            'Access was denied (if current user does not have read access to this run)',
            403)
    )
    def status(self, run: dict) -> dict:
        self._checkAccess(run)
        if FIELD_STATUS_CODE in run:
            rs = RunStatus.get(run[FIELD_STATUS_CODE])
        else:
            rs = RunStatus.UNKNOWN
        return {'status': rs.code, 'statusString': rs.name}

    @access.user(TokenScope.DATA_WRITE)
    @autoDescribeRoute(
        Description('Sets the status of the run. See the status query endpoint for details about '
                    'the meaning of the code.')
            .modelParam('runId', 'The ID of a run.', model=Folder, force=True, destName='run')
            .param('status', 'The status code.', dataType='integer', required=True)
            .errorResponse(
            'Access was denied (if current user does not have read access to this run)',
            403)
    )
    def setStatus(self, run: dict, status: int) -> None:
        self._checkAccess(run)
        run[FIELD_STATUS_CODE] = status
        Folder().save(run)

    @access.user(TokenScope.DATA_WRITE)
    @autoDescribeRoute(
        Description('Appends data to the .stdout and .stderr files. One of stdoutData and '
                    'stderrData parameters is required.')
            .modelParam('runId', 'The ID of a run.', model=Folder, force=True, destName='run')
            .param('stdoutData', 'Data to append to .stdout', dataType='string', required=False)
            .param('stderrData', 'Data to append to .stderr', dataType='string', required=False)
            .errorResponse(
            'Access was denied (if current user does not have read access to this run)',
            403)
    )
    def stream(self, run: dict, stdoutData: str = None, stderrData: str = None) -> None:
        runDir = Path(run['fsPath'])
        if stdoutData is not None:
            self._append(runDir, '.stdout', stdoutData)
        if stderrData is not None:
            self._append(runDir, '.stderr', stderrData)

    def _append(self, dir: Path, filename: str, data: str):
        file = dir / filename
        with open(file.as_posix(), 'a') as f:
            f.write(data)

    def _create(self, version: dict, name: str, root: dict, rootDir: Path) -> None:
        ro = True
        if name is None:
            ro = False
            name = self._generateName()

        (runFolder, runDir) = self._createSubdir(rootDir, root, name)

        runFolder['runVersionId'] = version['_id']
        runFolder['runStatus'] = RunStatus.UNKNOWN.code
        Folder().save(runFolder, False)

        # Structure is:
        #  @version -> ../Versions/<version> (link handled manually by FS)
        #  @data -> version/data (link handled manualy by FS)
        #  @workspace -> version/workspace (same)
        #  output
        #  .status (faked by the run FS)
        #  .stdout (created by the run itself)
        #  .stderr (same)

        (runDir / 'version').mkdir()
        (runDir / 'data').symlink_to('version/data', True)
        (runDir / 'workspace').symlink_to('version/workspace', True)
        (runDir / 'output').mkdir()

        return runFolder

    def _generateName(self):
        now = datetime.now()
        return now.strftime(RUN_NAME_FORMAT)

