from pathlib import Path
from typing import Tuple, Optional

import pathvalidate

from girder import logger
from girder.api.v1.resource import Resource
from girder.exceptions import RestException
from girder.models.folder import Folder
from girder.plugins.wholetale.utils import getOrCreateRootFolder


class AbstractVRResource(Resource):
    def __init__(self, resourceName, rootDirName):
        Resource.__init__(self)
        self.resourceName = resourceName
        self.rootDirName = rootDirName
        self.route('GET', ('clear',), self.clear)
        self.route('POST', (), self.create)
        self.route('GET', (), self.list)
        self.route('GET', ('exists',), self.exists)
        # Resource has its own handler here and whoever designed girder figured that if somebody
        # says route() in a subclass, that's totally OK to ignore and use the superclass stuff
        # instead.
        self.removeRoute('GET', (':id',))
        self.route('GET', (':id',), self.load)
        self.route('PUT', (':id',), self.rename)
        self.route('DELETE', (':id',), self.delete)

    def _getRootFromTale(self, tale: dict) -> dict:
        global_root = getOrCreateRootFolder(self.rootDirName)
        root = Folder().findOne({'parentId': global_root['_id'], 'name': str(tale['_id'])})
        return root

    def _checkNameSanity(self, name: Optional[str], parentFolder: dict) -> None:
        if not name:
            raise RestException('Name cannot be empty.', code=400)

        try:
            pathvalidate.validate_filename(name, platform='Linux')
        except pathvalidate.ValidationError:
            raise RestException('Invalid file name: ' + name, code=400)

        if Folder().findOne({'parentId': parentFolder['_id'], 'name': name}) is not None:
            raise RestException('Name already exists: ' + name, code=409)

    def _createSubdir(self, rootDir: Path, rootFolder: dict, name: str) -> Tuple[dict, Path]:
        """Create both Girder folder and corresponding directory. The name is stored in the Girder
        folder, whereas the name of the directory is taken from the folder ID. This is a
        deliberate step to discourage renaming of directories directly on disk, which would mess
        up the mapping between Girder folders and directories
        """
        folder = Folder().createFolder(rootFolder, name, creator=self.getCurrentUser())
        dirname = str(folder['_id'])
        dir = rootDir / dirname
        dir.mkdir(parents=True)
        folder.update({'fsPath': dir.absolute().as_posix(), 'isMapping': True})
        Folder().save(folder, validate=False, triggerEvents=False)

        # update the time
        Folder().updateFolder(rootFolder)
        return (folder, dir)

    def clear(self, tale: dict) -> None:
        root = self._getRootFromTale(tale)
        subdirs = Folder().find({'parentId': root['_id']})
        n = 0
        for v in subdirs:
            n += 1
            if 'fsPath' in v:
                path = v['fsPath']
            else:
                path = 'Unknown'
                logger.warn('Missing fspath: %s' % v)
            Folder().remove(v)
            logger.info('Directory not removed: %s' % path)
        return 'Deleted %s versions' % n

    def rename(self, vrfolder: dict, newName: str) -> dict:
        if not newName:
            raise RestException('New name cannot be empty.', code=400)

        root = Folder().load(vrfolder['parentId'], force=True)
        self._checkNameSanity(newName, root)

        vrfolder.update({'name': newName})
        Folder().save(vrfolder)

        return vrfolder

    def load(self, vrfolder: dict) -> dict:
        raise NotImplementedError

    def list(self, tale: dict, limit, offset, sort):
        root = self._getRootFromTale(tale)
        folders = Folder().find({'parentId': root['_id']}, limit=limit, sort=sort, offset=offset)
        return list(folders)

    def exists(self, tale: dict, name: str):
        root = self._getRootFromTale(tale)
        obj = Folder().findOne({'parentId': root['_id'], 'name': name})
        if obj is None:
            return {'exists': False}
        else:
            return {'exists': True, 'obj': Folder().filter(obj, self.getCurrentUser())}
