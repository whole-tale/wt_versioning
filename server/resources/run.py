import shutil
from datetime import datetime
from pathlib import Path
from typing import Union, Optional

from girder.api import access
from girder.api.describe import autoDescribeRoute, Description
from girder.api.rest import filtermodel
from girder.constants import AccessType, TokenScope
from girder.models.folder import Folder
from girder.plugins.jobs.models.job import Job
from girder.plugins.wholetale.models.tale import Tale
from girder.models.token import Token
from girder.plugins.wholetale.utils import init_progress
from gwvolman.tasks import recorded_run, RECORDED_RUN_STEP_TOTAL
from .version import Version
from .abstract_resource import AbstractVRResource
from ..constants import Constants, RunStatus, RunState
from ..lib import util

FIELD_SEQENCE_NUMBER = 'seq'
FIELD_STATUS_CODE = 'runStatus'
RUN_NAME_FORMAT = '%c'


class Run(AbstractVRResource):
    root_tale_field = "runsRootId"

    def __init__(self):
        super().__init__('run', Constants.RUNS_ROOT_DIR_NAME)
        self.route('PATCH', (':id', 'status'), self.setStatus)
        self.route('GET', (':id', 'status'), self.status)
        self.route('POST', (':id', 'start'), self.startRun)

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
    @filtermodel('folder')
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
        .param('allowRename', 'Allow to modify "name" if object with the same name '
                              'already exists.', required=False, dataType='boolean',
               default=False)
        .errorResponse('Access was denied (if current user does not have write access to the tale '
                       'associated with this version)', 403)
        .errorResponse('Illegal file name', 400)
    )
    def create(self, version: dict, name: str = None, allowRename: bool = False) -> dict:
        if not name:
            name = self._generateName()
        user = self.getCurrentUser()
        versionsRoot = Folder().load(version['parentId'], user=user, level=AccessType.WRITE)
        taleId = versionsRoot['taleId']
        tale = Tale().load(taleId, user=user, level=AccessType.WRITE)

        root = self._getRootFromTale(tale, user=user, level=AccessType.WRITE)
        name = self._checkNameSanity(name, root, allow_rename=allowRename)

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
            rfolder['runVersionId'], level=AccessType.WRITE, user=self.getCurrentUser()
        )

        Folder().remove(rfolder)
        shutil.move(path.as_posix(), trashDir)
        Version._decrementReferenceCount(version)

    @access.user(TokenScope.DATA_READ)
    @filtermodel('folder')
    @autoDescribeRoute(
        Description('Lists runs.')
        .modelParam('taleId', 'The ID of the tale to which the runs belong.', model=Tale,
                    level=AccessType.READ, destName='tale', paramType="query")
        .pagingParams(defaultSort='created')
        .errorResponse('Access was denied (if current user does not have read access to this '
                       'tale)', 403)
    )
    def list(self, tale: dict, limit, offset, sort):
        return super().list(
            tale, user=self.getCurrentUser(), limit=limit, offset=offset, sort=sort
        )

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

    def _create(self, version: dict, name: Optional[str], root: dict, rootDir: Path) -> dict:
        if not name:
            name = self._generateName()

        runFolder = self._createSubdir(rootDir, root, name, user=self.getCurrentUser())

        runFolder['runVersionId'] = version['_id']
        runFolder[FIELD_STATUS_CODE] = RunStatus.UNKNOWN.code
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
        (runDir / 'workspace').mkdir()
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

    @access.user
    @autoDescribeRoute(
        Description('Start the recorded_run job')
        .modelParam('id', 'The ID of a run.', model=Folder, level=AccessType.WRITE,
                    destName='run')
        .errorResponse('Access was denied (if current user does not have write access to '
                       'this run)', 403)
    )
    def startRun(self, run):
        user = self.getCurrentUser()

        runRoot = Folder().load(run['parentId'], user=user, level=AccessType.WRITE)
        tale = Tale().load(runRoot['meta']['taleId'], user=user, level=AccessType.READ)

        resource = {
            'type': 'wt_recorded_run',
            'tale_id': tale['_id'],
            'tale_title': tale['title']
        }

        token = Token().createToken(user=user, days=0.5)

        notification = init_progress(
            resource, user, 'Recorded run',
            'Initializing', RECORDED_RUN_STEP_TOTAL)

        rrTask = recorded_run.signature(
            args=[str(run['_id']), str(tale['_id'])],
            girder_job_other_fields={
                'wt_notification_id': str(notification['_id']),
            },
            girder_client_token=str(token['_id']),
        ).apply_async()

        return Job().filter(rrTask.job, user=user)
