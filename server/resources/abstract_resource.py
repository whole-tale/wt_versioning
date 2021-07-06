import os
from pathlib import Path
import shutil
from typing import Optional

import pathvalidate

from girder import logger
from girder.constants import AccessType
from girder.api.v1.resource import Resource
from girder.exceptions import RestException
from girder.models.folder import Folder


class AbstractVRResource(Resource):
    root_tale_field = None

    def __init__(self, resourceName, rootDirName):
        Resource.__init__(self)
        self.resourceName = resourceName
        self.rootDirName = rootDirName
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

    def _getRootFromTale(self, tale: dict, user=None, level=AccessType.READ) -> dict:
        if user:
            kwargs = dict(user=user, level=level)
        else:
            kwargs = dict(force=True)
        return Folder().load(tale[self.root_tale_field], exc=True, **kwargs)

    def _checkNameSanity(
        self,
        name: Optional[str],
        parentFolder: dict,
        allow_rename: bool = False,
    ) -> None:
        if not name:
            raise RestException('Name cannot be empty.', code=400)

        try:
            pathvalidate.validate_filename(name, platform='Linux')
        except pathvalidate.ValidationError:
            raise RestException('Invalid file name: ' + name, code=400)

        q = {'parentId': parentFolder['_id'], 'name': name}
        if not allow_rename and Folder().findOne(q, fields=["_id"]):
            raise RestException('Name already exists: ' + name, code=409)

        n = 0
        while Folder().findOne(q, fields=["_id"]):
            n += 1
            q["name"] = f"{name} ({n})"
            if n > 100:
                break
        return q["name"]

    def _createSubdir(
        self, rootDir: Path, rootFolder: dict, name: str, user=None
    ) -> dict:
        """Create both Girder folder and corresponding directory. The name is stored in the Girder
        folder, whereas the name of the directory is taken from the folder ID. This is a
        deliberate step to discourage renaming of directories directly on disk, which would mess
        up the mapping between Girder folders and directories
        """
        folder = Folder().createFolder(rootFolder, name, creator=user)
        dirname = str(folder['_id'])
        dir = rootDir / dirname
        dir.mkdir(parents=True)
        folder.update({'fsPath': dir.absolute().as_posix(), 'isMapping': True})
        folder = Folder().save(folder, validate=False, triggerEvents=False)

        # update the time
        Folder().updateFolder(rootFolder)
        return folder

    def rename(self, vrfolder: dict, newName: str, allow_rename: bool = False) -> dict:
        user = self.getCurrentUser()
        if not newName:
            raise RestException('New name cannot be empty.', code=400)
        root = Folder().load(vrfolder['parentId'], user=user, level=AccessType.WRITE)
        newName = self._checkNameSanity(newName, root, allow_rename=allow_rename)
        vrfolder.update({'name': newName})
        os.utime(vrfolder["fsPath"])
        os.utime(os.path.dirname(vrfolder["fsPath"]))
        return Folder().updateFolder(vrfolder)  # Filtering done by non abstract resource

    def load(self, vrfolder: dict) -> dict:
        raise NotImplementedError

    def list(
        self,
        tale: dict,
        user=None,
        limit=0,
        offset=0,
        sort=None,
        filters=None,
        **kwargs
    ):
        root = self._getRootFromTale(tale, user=user, level=AccessType.READ)
        return Folder().childFolders(
            root,
            "folder",
            user=user,
            limit=limit,
            offset=offset,
            sort=sort,
            filters=filters,
            **kwargs
        )

    def exists(self, tale: dict, name: str):
        user = self.getCurrentUser()
        root = self._getRootFromTale(tale, user=user, level=AccessType.READ)
        obj = Folder().findOne({'parentId': root['_id'], 'name': name})
        if obj is None:
            return {'exists': False}
        else:
            return {'exists': True, 'obj': Folder().filter(obj, self.getCurrentUser())}

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
