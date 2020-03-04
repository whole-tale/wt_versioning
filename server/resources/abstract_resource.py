from pathlib import Path
from typing import Tuple

import pathvalidate

from girder import logger
from girder.api import access
from girder.api.describe import autoDescribeRoute, Description
from girder.api.rest import filtermodel
from girder.api.v1.resource import Resource
from girder.constants import AccessType
from girder.exceptions import RestException
from girder.models.folder import Folder
from girder.plugins.wholetale.models.instance import Instance
from girder.plugins.wholetale.models.tale import Tale
from girder.plugins.wholetale.utils import getOrCreateRootFolder
from girder.utility.model_importer import ModelImporter


class AbstractVRResource(Resource):
    def __init__(self, resourceName, rootDirName):
        Resource.__init__(self)
        self.resourceName = resourceName
        self.rootDirName = rootDirName
        self.route('GET', ('getRoot',), self.getRoot)
        self.route('GET', ('clear',), self.clear)
        self.route('POST', (), self.create)
        self.route('GET', ('list',), self.list)
        self.route('GET', ('exists',), self.exists)
        # Resource has its own handler here and whoever designed girder figured that if somebody
        # says route() in a subclass, that's totally OK to ignore and use the superclass stuff
        # instead.
        self.removeRoute('GET', (':id',))
        self.route('GET', (':id',), self.load)
        self.route('GET', (':id', 'rename'), self.rename)
        self.route('DELETE', (':id',), self.delete)

    def _checkAccess(self, instance: dict, model='folder', model_plugin=None):
        user = self.getCurrentUser()

        if not ModelImporter.model(model, model_plugin).hasAccess(instance, user, AccessType.WRITE):
            raise RestException('Access denied', code=403)

    def _getTaleAndRoot(self, instance: dict) -> Tuple[dict, dict]:
        tale = Tale().findOne({'_id': instance['taleId']})
        global_root = getOrCreateRootFolder(self.rootDirName)
        root = Folder().findOne({'parentId': global_root['_id'], 'name': str(tale['_id'])})
        return (tale, root)

    def _checkNameSanity(self, name: str, parentFolder: dict) -> None:
        if name is None:
            return
        try:
            pathvalidate.validate_filename(name, platform='Linux')
        except pathvalidate.ValidationError:
            raise ValueError('Invalid file name: ' + name, 400)
        try:
            Folder().find({'parentId': parentFolder['_id'], 'name': name}, limit=1).next()
            raise ValueError('Name already exists: ' + name, 400)
        except StopIteration:
            pass

    def _createSubdir(self, rootDir: Path, rootFolder: dict, name: str) -> Tuple[dict, Path]:
        '''Create both Girder folder and corresponding directory. The name is stored in the Girder
        folder, whereas the name of the directory is taken from the folder ID. This is a
        deliberate step to discourage renaming of directories directly on disk, which would mess
        up the mapping between Girder folders and directories'''
        folder = Folder().createFolder(rootFolder, name, creator=self.getCurrentUser())
        dirname = str(folder['_id'])
        dir = rootDir / dirname
        dir.mkdir()
        folder.update({'fsPath': dir.absolute().as_posix(), 'isMapping': True})
        Folder().save(folder, validate=False, triggerEvents=False)
        return (folder, dir)

    def getRoot(self, instance: dict) -> dict:
        (tale, root) = self._getTaleAndRoot(instance)

        return root

    def clear(self, root: dict) -> None:
        self._checkAccess(root)
        versions = Folder().find({'parentId': root['_id']})
        n = 0
        for v in versions:
            n += 1
            path = v['fsPath']
            Folder().remove(v)
            logger.info('Directory not removed: %s' % path)
        return 'Deleted %s versions' % n

    def rename(self, vrfolder: dict, newName: str) -> dict:
        self._checkAccess(vrfolder)

        root = Folder().load(vrfolder['parentId'], force=True)
        self._checkNameSanity(newName, root)

        vrfolder.update({'name': newName})
        Folder().save(vrfolder)

        return vrfolder

    def load(self, vrfolder: dict) -> dict:
        self._checkAccess(vrfolder, model='folder', model_plugin=None)
        return vrfolder

    def list(self, root: dict, limit, offset, sort):
        self._checkAccess(root)
        folders = Folder().find({'parentId': root['_id']}, limit=limit, sort=sort, offset=offset)
        return list(folders)

    def exists(self, root: dict, name: str):
        self._checkAccess(root)
        return Folder().findOne({'parentId': root['_id'], 'name': name})
