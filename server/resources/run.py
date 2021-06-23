import math
import random
import shutil
import time as t
from datetime import datetime
from pathlib import Path
from threading import Thread
from typing import Union, Optional

import cherrypy

from girder import logger
from girder.api import access
from girder.api.describe import autoDescribeRoute, Description
from girder.api.rest import filtermodel
from girder.constants import AccessType, TokenScope
from girder.models.folder import Folder
from girder.plugins.wholetale.models.tale import Tale
from .version import Version
from .abstract_resource import AbstractVRResource
from ..constants import Constants, RunStatus, RunState
from ..lib import util

FIELD_SEQENCE_NUMBER = 'seq'
FIELD_STATUS_CODE = 'runStatusCode'
RUN_NAME_FORMAT = '%c'


class Run(AbstractVRResource):
    root_tale_field = "runsRootId"

    def __init__(self):
        super().__init__('run', Constants.RUNS_ROOT_DIR_NAME)
        self.route('PATCH', (':id', 'stream'), self.stream)
        self.route('PATCH', (':id', 'status'), self.setStatus)
        self.route('GET', (':id', 'status'), self.status)
        self.route('GET', (':id', 'fakeAnActualRun'), self.fakeAnActualRun)

    @access.user()
    @filtermodel('folder')
    @autoDescribeRoute(
        Description('Retrieves the runs root folder for this tale.')
        .modelParam('taleId', 'The ID of a tale', model=Tale, level=AccessType.READ,
                    paramType='query', destName='tale')
        .errorResponse('Access was denied (if current user does not have write access to this '
                       'tale)', 403)
    )
    def getRoot(self, tale: dict) -> dict:
        return super().getRoot(tale)

    @access.user
    @autoDescribeRoute(
        Description('Clears all runs from a tale, but does not delete the respective '
                    'directories on disk. This is an administrative operation and should not be'
                    'used under normal circumstances.')
        .modelParam('taleId', 'The ID of the runs root folder', model=Tale, level=AccessType.ADMIN,
                    destName='tale', paramType='query')
    )
    def clear(self, tale: dict) -> None:
        super().clear(tale)

    @access.user(TokenScope.DATA_WRITE)
    @filtermodel('folder')
    @autoDescribeRoute(
        Description('Rename a run associated with a tale. Returns the renamed run folder')
        .modelParam('id', 'The ID of a run', model=Folder, level=AccessType.WRITE,
                    destName='rfolder')
        .param('name', 'The new name', required=True, dataType='string', paramType='query')
        .errorResponse('Access was denied (if current user does not have write access to this '
                       'tale)', 403)
        .errorResponse('Illegal file name', 400)
    )
    def rename(self, rfolder: dict, name: str) -> dict:
        return super().rename(rfolder, name)

    @access.user(TokenScope.DATA_READ)
    @autoDescribeRoute(
        Description('Returns a run.')
        .modelParam('id', 'The ID of a run.', model=Folder, level=AccessType.READ,
                    destName='rfolder')
        .errorResponse('Access was denied (if current user does not have read access to the '
                       'respective run folder.', 403)
    )
    def load(self, rfolder: dict) -> dict:
        return rfolder

    @access.user(TokenScope.DATA_WRITE)
    @filtermodel('folder')
    @autoDescribeRoute(
        Description('Creates a new empty run associated with a given version and returns the new '
                    'run folder. This does not actually start any computation.')
        .modelParam('versionId', 'A version to create the run from.',
                    model=Folder, level=AccessType.WRITE,
                    destName='version', paramType='query')
        .param('name', 'An optional name for the run. If not specified, a name will be '
                       'generated from the current date and time.', required=False,
               dataType='string', paramType='query')
        .errorResponse('Access was denied (if current user does not have write access to the tale '
                       'associated with this version)', 403)
        .errorResponse('Illegal file name', 400)
    )
    def create(self, version: dict, name: str = None) -> dict:
        user = self.getCurrentUser()
        versionsRoot = Folder().load(version['parentId'], user=user, level=AccessType.WRITE)
        taleId = versionsRoot['taleId']
        tale = Tale().load(taleId, user=user, level=AccessType.WRITE)

        root = self._getRootFromTale(tale, user=user, level=AccessType.WRITE)
        self._checkNameSanity(name, root)

        rootDir = util.getTaleRunsDirPath(tale)

        run = self._create(version, name, root, rootDir)
        Version._incrementReferenceCount(version)

        return run

    @access.user(TokenScope.DATA_WRITE)
    @autoDescribeRoute(
        Description('Deletes a run.')
        .modelParam('id', 'The ID of run', model=Folder, level=AccessType.WRITE,
                    destName='rfolder')
        .errorResponse('Access was denied (if current user does not have write access to this '
                       'tale)', 403)
    )
    def delete(self, rfolder: dict) -> None:
        path = Path(rfolder['fsPath'])
        trashDir = path.parent / '.trash'

        version = Folder().load(
            rfolder['runVersionId'], level=AccessType.WRTITE, user=self.getCurrentUser()
        )

        Folder().remove(rfolder)
        shutil.move(path.as_posix(), trashDir)
        Version._decrementReferenceCount(version)

    @access.user(TokenScope.DATA_READ)
    @filtermodel('folder')
    @autoDescribeRoute(
        Description('Lists runs.')
        .modelParam('taleId', 'The ID of the tale to which the runs belong.', model=Tale,
                    level=AccessType.READ, destName='tale')
        .pagingParams(defaultSort='created')
        .errorResponse('Access was denied (if current user does not have read access to this '
                       'tale)', 403)
    )
    def list(self, tale: dict, limit, offset, sort):
        return super().list(tale, limit, offset, sort)

    @access.user(TokenScope.DATA_READ)
    @autoDescribeRoute(
        Description('Check if a run exists.')
        .modelParam('taleId', 'The ID of a tale.', model=Tale, level=AccessType.READ,
                    destName='tale', paramType='query')
        .param('name', 'Return the folder with this name or nothing if no such folder exists.',
               required=False, dataType='string')
        .errorResponse('Access was denied (if current user does not have read access to this '
                       'tale)', 403)
    )
    def exists(self, tale: dict, name: str):
        return super().exists(tale, name)

    @access.user(TokenScope.DATA_READ)
    @autoDescribeRoute(
        Description('Returns the status of a run in an object with two fields: status and '
                    'statusString. The possible values for status, an integer, are 0, 1, 2, 3, 4, '
                    '5, with statusString being, respectively, UNKNOWN, STARTING, RUNNING, '
                    'COMPLETED, FAILED, CANCELLED.')
        .modelParam('id', 'The ID of a run.', model=Folder,
                    level=AccessType.READ, destName='rfolder')
        .errorResponse('Access was denied (if current user does not have read access to '
                       'this run)', 403)
    )
    def status(self, rfolder: dict) -> dict:
        if FIELD_STATUS_CODE in rfolder:
            rs = RunStatus.get(rfolder[FIELD_STATUS_CODE])
        else:
            rs = RunStatus.UNKNOWN
        return {'status': rs.code, 'statusString': rs.name}

    @access.user(TokenScope.DATA_WRITE)
    @autoDescribeRoute(
        Description('Sets the status of the run. See the status query endpoint for details about '
                    'the meaning of the code.')
        .modelParam('id', 'The ID of a run.', model=Folder,
                    level=AccessType.WRITE, destName='rfolder')
        .param('status', 'The status code.', dataType='integer', required=True)
        .errorResponse('Access was denied (if current user does not have read access to '
                       'this run)', 403)
    )
    def setStatus(self, rfolder: dict, status: Union[int, RunState]) -> None:
        self._setStatus(rfolder, status)

    def _setStatus(self, rfolder: dict, status: Union[int, RunState]) -> None:
        # TODO: add heartbeats (runs must regularly update status, otherwise they are considered
        # failed)
        if isinstance(status, int):
            _status = RunState.ALL[status]
        else:
            _status = status
        rfolder[FIELD_STATUS_CODE] = _status.code
        Folder().save(rfolder)
        runDir = Path(rfolder['fsPath'])
        self._write_status(runDir, _status)

    @access.user(TokenScope.DATA_WRITE)
    @autoDescribeRoute(
        Description('Appends data to the .stdout and .stderr files. One of stdoutData and '
                    'stderrData parameters is required.')
        .modelParam('id', 'The ID of a run.', model=Folder,
                    level=AccessType.WRITE, destName='rfolder')
        .param('stdoutData', 'Data to append to .stdout', dataType='string', required=False)
        .param('stderrData', 'Data to append to .stderr', dataType='string', required=False)
        .errorResponse('Access was denied (if current user does not have read access to '
                       'this run)', 403)
    )
    def stream(self, rfolder: dict, stdoutData: str = None, stderrData: str = None) -> None:
        self._stream(rfolder, stdoutData, stderrData)

    def _stream(self, rfolder: dict, stdoutData: str = None, stderrData: str = None) -> None:
        runDir = Path(rfolder['fsPath'])
        new = False
        if stdoutData is not None:
            new |= self._append(runDir, '.stdout', stdoutData)
        if stderrData is not None:
            new |= self._append(runDir, '.stderr', stderrData)
        if new:
            # Girder does not change the 'updated' attribute on a parent folder when a child
            # is added. This is a bit different here, since runDir is the root of a virtual object
            # hierarchy and, while there is an actual folder on disk corresponding to it, which
            # does have a proper modified/updated time, this does not get 'propagated' to the
            # girder object, so we manually set the updated field when a new file appears.
            Folder().updateFolder(rfolder)

    def _append(self, dir: Path, filename: str, data: str):
        file = dir / filename
        new = not file.exists()
        with open(file.as_posix(), 'a') as f:
            f.write(data)
        return new

    def _create(self, version: dict, name: Optional[str], root: dict, rootDir: Path) -> dict:
        if not name:
            name = self._generateName()

        runFolder = self._createSubdir(rootDir, root, name, user=self.getCurrentUser())

        runFolder['runVersionId'] = version['_id']
        runFolder['runStatus'] = RunStatus.UNKNOWN.code
        Folder().save(runFolder, False)

        # Structure is:
        #  @version -> ../Versions/<version> (link handled manually by FS)
        #  @data -> version/data (link handled manualy by FS)
        #  @workspace -> version/workspace (same)
        #  results
        #  .status
        #  .stdout (created using stream() above)
        #  .stderr (-''-)
        runDir = Path(runFolder["fsPath"])
        tale_id = runDir.parts[-2]
        # TODO: a lot assumptions hardcoded below...
        (runDir / 'version').symlink_to(
            f"../../../../versions/{tale_id[:2]}/{tale_id}/{version['_id']}", True
        )
        (runDir / 'data').symlink_to('version/data', True)
        # (runDir / 'workspace').symlink_to('version/workspace', True)  # used to be...
        self._snapshotRecursive(
            None,
            (runDir / "version" / "workspace"),
            (runDir / "workspace")
        )
        (runDir / 'results').mkdir()
        self._write_status(runDir, RunStatus.UNKNOWN)

        return runFolder

    def _write_status(self, runDir: Path, status: RunState):
        with open(runDir / '.status', 'w') as f:
            f.write('%s %s' % (status.code, status.name))

    def _generateName(self):
        now = datetime.now()
        return now.strftime(RUN_NAME_FORMAT)

    @access.user()
    @filtermodel('folder')
    @autoDescribeRoute(
        Description('Fakes a run. Slowly updates the status, adds text to stdout/stderr, and puts'
                    'files in the results dir.')
        .modelParam('id', 'The ID of a run.', model=Folder, level=AccessType.WRITE,
                    destName='rfolder')
        .errorResponse('Access was denied (if current user does not have write access to '
                       'this run)', 403)
    )
    def fakeAnActualRun(self, rfolder: dict) -> None:
        t = Thread(target=self._fakeRun, args=(rfolder, self.getCurrentToken()))
        t.start()

    def _fakeRun(self, rfolder: dict, token: dict) -> None:
        cherrypy.request.girderToken = token
        cherrypy.request.params = {}
        try:
            self._setStatus(rfolder, RunStatus.STARTING)
            self._wait(5)
            rdir = Path(rfolder['fsPath'])
            resultsDir = rdir / 'results'

            self._setStatus(rfolder, RunStatus.RUNNING)
            with open(resultsDir / 'output.dat', 'w') as fo:
                for _ in range(200):
                    fo.write('data')
                    fo.flush()
                    self._stream(rfolder, '%s: Step %s\n' % (datetime.now(), _))
                    self._wait(1)

            self._setStatus(rfolder, RunStatus.COMPLETED)
        except Exception as ex:  # NOQA
            logger.warn('Exception faking run', ex)

    def _wait(self, secs):
        t.sleep(max(0.1, random.normalvariate(secs, math.sqrt(secs))))
