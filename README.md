# The WholeTale Versioning Plugin
<!-- TOC depthFrom:1 depthTo:4 withLinks:1 updateOnSave:1 orderedList:0 -->

- [The WholeTale Versioning Plugin](#the-wholetale-versioning-plugin)
	- [The backend API {#backend-api}](#the-backend-api-backend-api)
		- [Settings](#settings)
			- [wtversioning.versions_root](#wtversioningversionsroot)
			- [wtversioning.runs_root](#wtversioningrunsroot)
		- [The API](#the-api)
			- [Create Version](#create-version)
			- [Get Version](#get-version)
			- [Rename Version](#rename-version)
			- [Get Dataset](#get-dataset)
			- [Delete Version](#delete-version)
			- [Get Versions Root {#get-root}](#get-versions-root-get-root)
			- [Get Latest Version](#get-latest-version)
			- [List Versions](#list-versions)
			- [Version Exists](#version-exists)
			- [Clear Versions](#clear-versions)
			- [Create Run](#create-run)
			- [Get Run {#get-run}](#get-run-get-run)
			- [Rename Run](#rename-run)
			- [Get Run Status {#get-run-status}](#get-run-status-get-run-status)
			- [Set Run Status](#set-run-status)
			- [Stream Run Output](#stream-run-output)
			- [Delete Run](#delete-run)
			- [Get Runs Root {#get-runs-root}](#get-runs-root-get-runs-root)
			- [List Runs](#list-runs)
			- [Run Exists](#run-exists)
			- [Clear Runs](#clear-runs)
	- [FUSE Filesystems {#fuse-fss}](#fuse-filesystems-fuse-fss)

<!-- /TOC -->

<!--
        self.route('POST', (), self.create)
        self.route('GET', (':id',), self.load)
        self.route('GET', (':id', 'rename'), self.rename)
        self.route('GET', (':id', 'dataSet'), self.getDataset)
        self.route('DELETE', (':id',), self.delete)
        self.route('GET', ('getRoot',), self.getRoot)
        self.route('GET', ('latest',), self.getLatestVersion)
        self.route('GET', ('list',), self.list)
        self.route('GET', ('exists',), self.exists)
        self.route('GET', ('clear',), self.clear)




-->

This (Girder) plugin implements the backend functionality needed for versioning and runs. For some background information about the problem in general, see the following (possibly non-public) documents: [Recorded Run](https://docs.google.com/document/d/1GcWDs8FwnWDA-DJKu3z24ojNVKl5JnJ4liYZgLHZIDg/edit#heading=h.axlxcwto6mlq), [WT Versioning Design Notes](https://docs.google.com/document/d/1b2xZtIYvgVXz7EVeV-C18So_a7QLGg59dPQMxvBcA5o/edit#heading=h.5812f5vdczzl).

The current implementation uses a linear versioning scheme, in which each version is a snapshot-in-time of the tale. The versions can therefore be logically mapped to a collection of subfolders in a main version folder. Furthermore, the versionning can be done automatically by the system, without the need for the user to perform any (complex or otherwise) steps. More complex solutions are possible, such as a git-backed system, but the implications in terms of how much of the complexity is pushed to the user are not clear to the author.

It is perhaps worth mentioning that versions and runs do not have special Girder models associated with them. Instead, standard Girder folders are used for both versions and runs.

This plugin depends on the [Virtual Resources](https://github.com/whole-tale/virtual_resources) plugin, which uses a POSIX directory structure as an underlying store for Girder items and folders, bypassing the database. The precise scheme used by the versioning plugin is that of a root folder (one for a tale's versions and one for its runs), which is a standard Girder folder. Its sub-folders, the actual versions and runs, are then each mapped to a directory on disk. That is, versions and runs root folders are database backed. This is done because certain operations, such as retrieving the last version or retrieving a subset of versions, can be done much more efficiently using database queries than filesystem queries.

There are two main components to the versioning plugin: the [backend API](#backend-api) and the [FUSE filesystems](#fuse-fss).

## The backend API {#backend-api}

The backend API, implemented as a Girder plugin, contains all the relevant REST calls needed for versioning and run management. The basic idea behind versions is that a UI implementing an editing component for a tale would, either periodically or in response to certain user actions (such as the saving of a file), trigger the creation of a new version. A separate UI component would list and display the existing versions and allow a user to interact with them to the extent allowed by, for example, implementing browsing, deletion, and renaming of versions and runs.

### Settings

These are the settings for the wt_versioning plugin, available through the standard Girder configuration management mechanism:

#### wtversioning.versions_root

A filesystem directory where the versions directory hierarchy is stored. The actual versions for a tale will then be stored in `<versions_root>/<first_two_chars_of_tale_id>/<tale_id>`.

#### wtversioning.runs_root

Same as above, except for tale runs.

### The API

A `<girder_url>/api/v1` prefix is assumed.

<!-- ********************************************************************* -->
<!-- ********************************************************************* -->

#### Create Version
```
POST /version
```

Creates a new version in the version chain for this tale and returns the resulting version folder.

##### Parameters:
```python
instanceId: string
[name: string]
[force: boolean = false]
```

An `instanceId` must be specified. While versions are associated with tales, they are also created with respect to an active instance. A good question is what should happen if more than one active instance of the same tale exist. An optional `name` can be specified, wich must be a valid filename.

If a `name` is not specified, the current date and time are used formatted according to `%c` in the 1989 C standard (in en_US, this would be, for example, *Mon Jan 10 22:01:05 2019*)

Normally, if no files belonging to the tale workspace<sup>*</sup> have changed since the last call to this operation, the call will fail with HTTP code `303`. Setting the `force` flag to `true`, disables this behavior and allows creation of a new version even if no workspace files have been changed.

<sup>*</sup> TODO: This should include a check on the dataset associated with the tale; if we change the imported data but no files, we should still be able to create a new version.

##### Errors:

`403 Access Denied` - returned when the calling user does not have write access to the tale instance.

`409 Try Again Later` - another version is being created and concurrent version creation is not supported.

`400 Illegal File Name` - a `name` was specified, but is not a legal file name.

`303 See Other` - returned when no workspace file has been modified since the last call to this operation. If this error code is returned, the body will consist of a JSON object whose `extra` attribute will contain the `id` (not name) of the previous version.

##### Example:
```
curl -X POST\
    --header 'Girder-Token: Z8Kaa0rIY98FMxlipOOCnsdBYEG290BhkPQk7JuxA9oen86DkEw5fIhp6hxtWL2A'\
    --header 'Content-Length: 0' --header 'Content-Type: application/json'\
    --header 'Accept: application/json'\
    'http://localhost:8080/api/v1/version?instanceId=5e5d855ec6efca74a8cacf26&force=false'
```

##### Example response:
```json
{
    "_accessLevel": 2,
    "_id": "5ea0dcfef445d91fe4acdb07",
    "_modelType": "folder",
    "baseParentId": "5e4b8a343b2f6c31462128aa",
    "baseParentType": "collection",
    "created": "2020-04-23T00:10:38.828219+00:00",
    "creatorId": "582f621ccbb11e75430a89ae",
    "description": "",
    "fsPath": "/home/mike/work/wt/wt_dirs/version/5e/5e5d8541c6efca74a8cacf1f/5ea0dcfef445d91fe4acdb07",
    "isMapping": true,
    "name": "Wed Apr 22 17:10:38 2020",
    "parentCollection": "folder",
    "parentId": "5e5d8541c6efca74a8cacf20",
    "public": true,
    "size": 0,
    "updated": "2020-04-23T00:10:38.828219+00:00"
}
```

<!-- ********************************************************************* -->
<!-- ********************************************************************* -->


#### Get Version

```
GET /version/{id}
```

Returns the folder representing the version with `id == {id}`. In addition to the standard folder attributes, the response will also contain a `dataSet` attribute whose value is the [DMS](https://github.com/whole-tale/girder_wt_data_manager) data set associated with the version.

##### Parameters:
```python
id: string
```

##### Errors:
`403 Access Denied`

##### Example:
```
curl -X GET\
    --header 'Girder-Token: Z8Kaa0rIY98FMxlipOOCnsdBYEG290BhkPQk7JuxA9oen86DkEw5fIhp6hxtWL2A'\
    --header 'Accept: application/json' 'http://localhost:8080/api/v1/version/5ea0dcfef445d91fe4acdb07'
```

##### Example response:
```json
{
    "_id": "5ea0dcfef445d91fe4acdb07",
    "access": {...},
    "baseParentId": "5e4b8a343b2f6c31462128aa",
    "baseParentType": "collection",
    "created": "2020-04-23T00:10:38.828000+00:00",
    "creatorId": "582f621ccbb11e75430a89ae",
    "dataSet": [
        {"_modelType": "item", "itemId": "5e48743c2d022856c3a6cd00", "mountPath": "BBH_events_v3.json"},
        {"_modelType": "item", "itemId": "5e48743e2d022856c3a6cd14", "mountPath": "L-L1_LOSC_4_V1-1167559920-32.hdf5"}, ...
    ],
    "description": "",
    "fsPath": "/home/mike/work/wt/wt_dirs/version/5e/5e5d8541c6efca74a8cacf1f/5ea0dcfef445d91fe4acdb07",
    "isMapping": true,
    "lowerName": "wed apr 22 17:10:38 2020",
    "name": "Wed Apr 22 17:10:38 2020",
    "parentCollection": "folder",
    "parentId": "5e5d8541c6efca74a8cacf20",
    "public": true,
    "size": 0,
    "updated": "2020-04-23T00:10:38.828000+00:00"
}
```

#### Rename Version

```
GET /version/{id}/rename
```

Renames a version

##### Parameters:
```python
id: string
newName: string
```

The `id` is the version id and `newName` is, unsurprisingly, the new name.

##### Errors:
`400 Illegal File Name` - if the name is not a valid POSIX filename
`403 Access Denied`


##### Example:
```
curl -X GET\
    --header 'Girder-Token: Z8Kaa0rIY98FMxlipOOCnsdBYEG290BhkPQk7JuxA9oen86DkEw5fIhp6hxtWL2A'\
    --header 'Accept: application/json'\
    'http://localhost:8080/api/v1/version/5ea0dcfef445d91fe4acdb07/rename?newName=The%20Version'
```

##### Example response:
```json
{
    "_accessLevel": 2,
    "_id": "5ea0dcfef445d91fe4acdb07",
    "_modelType": "folder",
    "baseParentId": "5e4b8a343b2f6c31462128aa",
    "baseParentType": "collection",
    "created": "2020-04-23T00:10:38.828000+00:00",
    "creatorId": "582f621ccbb11e75430a89ae",
    "description": "",
    "fsPath": "/home/mike/work/wt/wt_dirs/version/5e/5e5d8541c6efca74a8cacf1f/5ea0dcfef445d91fe4acdb07",
    "isMapping": true,
    "name": "The Version",
    "parentCollection": "folder",
    "parentId": "5e5d8541c6efca74a8cacf20",
    "public": true,
    "size": 0,
    "updated": "2020-04-23T00:10:38.828000+00:00"
}
```

<!-- ********************************************************************* -->
<!-- ********************************************************************* -->

#### Get Dataset

```
GET /version/{id}/dataSet
```

Retrieves the [DMS](https://github.com/whole-tale/girder_wt_data_manager) data set associated with a version.

<desc>

##### Parameters:
```python
id: string
```

The `id` path parameter must be the id of a version folder.

##### Errors:
`403 Access Denied`

##### Example:
```
curl -X GET\
    --header 'Girder-Token: Z8Kaa0rIY98FMxlipOOCnsdBYEG290BhkPQk7JuxA9oen86DkEw5fIhp6hxtWL2A'\
     --header 'Accept: application/json'\
     'http://localhost:8080/api/v1/version/5ea0dcfef445d91fe4acdb07/dataSet'

```

##### Example Response:
```json
[
    {
        "_modelType": "item",
        "itemId": "5e48743c2d022856c3a6cd00",
        "mountPath": "BBH_events_v3.json",
        "obj": {...},
        "type": "item"
    },
    {
        "_modelType": "item",
        "itemId": "5e48743e2d022856c3a6cd14",
        "mountPath": "L-L1_LOSC_4_V1-1167559920-32.hdf5",
        "obj": {...},
        "type": "item"
    },
    ...
]
```

<!-- ********************************************************************* -->
<!-- ********************************************************************* -->

#### Delete Version

```
DELETE /version/{id}
```

<desc>

##### Parameters:
```python
id: string
```

The `id` parameter is the id the version folder to be deleted.

<param desc>

##### Errors:
`403 Permission Denied`
`461 In Use` - This error is returned when the version is in use by a run and cannot be deleted.

##### Example:
```
curl -X DELETE\
    --header 'Girder-Token: Z8Kaa0rIY98FMxlipOOCnsdBYEG290BhkPQk7JuxA9oen86DkEw5fIhp6hxtWL2A'\
    'http://localhost:8080/api/v1/version/5ea0dcfef445d91fe4acdb07'
```

##### Example Response:

An empty response is generated if the operation is successful.

<!-- ********************************************************************* -->
<!-- ********************************************************************* -->

#### Get Versions Root {#get-root}

```
GET /version/getRoot
```

Returns the versions root folder for an instance. The versions root folder is the parent folder to all the versions.


##### Parameters:
```python
instanceId: string
```

The `instanceId` parameter points to the instance of the tale whose versions root folder will be returned.

##### Example:
```
curl -X GET\
    --header 'Girder-Token: Z8Kaa0rIY98FMxlipOOCnsdBYEG290BhkPQk7JuxA9oen86DkEw5fIhp6hxtWL2A'\
    --header 'Accept: application/json'\
    'http://localhost:8080/api/v1/version/getRoot?instanceId=5e5d855ec6efca74a8cacf26'
```

##### Example Response:
```json
{
    "_id": "5e5d8541c6efca74a8cacf20",
    "access": {...},
    "baseParentId": "5e4b8a343b2f6c31462128aa",
    "baseParentType": "collection",
    "created": "2020-03-02T22:14:25.745000+00:00",
    "creatorId": null,
    "description": "",
    "lowerName": "5e5d8541c6efca74a8cacf1f",
    "meta": {"taleId": "5e5d8541c6efca74a8cacf1f"},
    "name": "5e5d8541c6efca74a8cacf1f",
    "parentCollection": "folder",
    "parentId": "5e4b8a343b2f6c31462128ab",
    "public": true,
    "seq": 3,
    "size": 0,
    "taleId": "5e5d8541c6efca74a8cacf1f",
    "updated": "2020-04-23T00:10:38.830000+00:00",
    "versionsCriticalSectionFlag": false
}
```

<!-- ********************************************************************* -->
<!-- ********************************************************************* -->

#### Get Latest Version

```
GET /version/latest
```

Returns the most recent version for a tale.

##### Parameters:
```python
rootId: string
```

The `rootId` parameter points to the versions root folder for a Tale (see [Get Root](#get-root)).

##### Errors:
`403 Access Denied`

##### Example:
```
curl -X GET\
    --header 'Girder-Token: Z8Kaa0rIY98FMxlipOOCnsdBYEG290BhkPQk7JuxA9oen86DkEw5fIhp6hxtWL2A'\
    --header 'Accept: application/json'\
    'http://localhost:8080/api/v1/version/latest?rootId=5e5d8541c6efca74a8cacf20'
```

##### Example Response:
```json
{
    "_accessLevel": 2,
    "_id": "5ea0dcfef445d91fe4acdb07",
    "_modelType": "folder",
    "baseParentId": "5e4b8a343b2f6c31462128aa",
    "baseParentType": "collection",
    "created": "2020-04-23T00:10:38.828000+00:00",
    "creatorId": "582f621ccbb11e75430a89ae",
    "description": "",
    "fsPath": "/home/mike/work/wt/wt_dirs/version/5e/5e5d8541c6efca74a8cacf1f/5ea0dcfef445d91fe4acdb07",
    "isMapping": true,
    "name": "The Version",
    "parentCollection": "folder",
    "parentId": "5e5d8541c6efca74a8cacf20",
    "public": true,
    "size": 0,
    "updated": "2020-04-23T00:10:38.828000+00:00"
}
```

<!-- ********************************************************************* -->
<!-- ********************************************************************* -->

#### List Versions

```
GET /version/list
```

Returns all versions for a tale.

##### Parameters:
```python
rootId: string
[limit: int = 50]
[offset: int]
[sort: string = 'created']
[sortdir: int = 1]
```

The `rootId` parameter points to the versions root folder for a Tale (see [Get Root](#get-root)).

The optional parameters are standard paging and sorting parameters.

##### Errors:
`403 Access Denied`

##### Example:
```
curl -X GET\
    --header 'Girder-Token: Z8Kaa0rIY98FMxlipOOCnsdBYEG290BhkPQk7JuxA9oen86DkEw5fIhp6hxtWL2A'\
    --header 'Accept: application/json'\
    'http://localhost:8080/api/v1/version/list?rootId=5e5d8541c6efca74a8cacf20&limit=50&sort=created&sortdir=1'
```

##### Example Response:
```json
[
    {
        "_accessLevel": 2,
        "_id": "5e5df7a0e2c48f2e00a465e5",
        "_modelType": "folder",
        "baseParentId": "5e4b8a343b2f6c31462128aa",
        "baseParentType": "collection",
        "created": "2020-03-03T06:22:24.681000+00:00",
        "creatorId": "582f621ccbb11e75430a89ae",
        "description": "",
        "fsPath": "/home/mike/work/wt/wt_dirs/version/5e/5e5d8541c6efca74a8cacf1f/5e5df7a0e2c48f2e00a465e5",
        "isMapping": true,
        "name": "Mon Mar  2 22:22:24 2020",
        "parentCollection": "folder",
        "parentId": "5e5d8541c6efca74a8cacf20",
        "public": true,
        "size": 0,
        "updated": "2020-03-03T06:22:24.681000+00:00"
    },
    {
        "_accessLevel": 2,
        "_id": "5ea0dcfef445d91fe4acdb07",
        "_modelType": "folder",
        "baseParentId": "5e4b8a343b2f6c31462128aa",
        "baseParentType": "collection",
        "created": "2020-04-23T00:10:38.828000+00:00",
        "creatorId": "582f621ccbb11e75430a89ae",
        "description": "",
        "fsPath": "/home/mike/work/wt/wt_dirs/version/5e/5e5d8541c6efca74a8cacf1f/5ea0dcfef445d91fe4acdb07",
        "isMapping": true,
        "name": "The Version",
        "parentCollection": "folder",
        "parentId": "5e5d8541c6efca74a8cacf20",
        "public": true,
        "size": 0,
        "updated": "2020-04-23T00:10:38.828000+00:00"
    }
]
```

<!-- ********************************************************************* -->
<!-- ********************************************************************* -->

#### Version Exists

```
GET /version/exists
```

Checks if a version with the specified *name* exists and return it if it does. The returned object is an object with a mandatory field named `exists`, which is a boolean value indicating whether the specified version exists, and an optional field named `obj` which contains the relevant version if found.

##### Parameters:
```python
rootId: string
name: string
```

The `rootId` parameter points to the versions root folder for a Tale (see [Get Root](#get-root)). The `name` parameter is the name to check for.

##### Errors:
`403 Access Denied`

##### Example:
```
curl -X GET\
    --header 'Girder-Token: Z8Kaa0rIY98FMxlipOOCnsdBYEG290BhkPQk7JuxA9oen86DkEw5fIhp6hxtWL2A'\
    --header 'Accept: application/json'\
    'http://localhost:8080/api/v1/version/exists?rootId=5e5d8541c6efca74a8cacf20&name=Mon%20Mar%20%202%2022%3A22%3A24%202020'
```

##### Example Response:
```json
{
    "exists": true,
    "version": {
        "_accessLevel": 2,
        "_id": "5e5df7a0e2c48f2e00a465e5",
        "_modelType": "folder",
        "baseParentId": "5e4b8a343b2f6c31462128aa",
        "baseParentType": "collection",
        "created": "2020-03-03T06:22:24.681000+00:00",
        "creatorId": "582f621ccbb11e75430a89ae",
        "description": "",
        "fsPath": "/home/mike/work/wt/wt_dirs/version/5e/5e5d8541c6efca74a8cacf1f/5e5df7a0e2c48f2e00a465e5",
        "isMapping": true,
        "name": "Mon Mar  2 22:22:24 2020",
        "parentCollection": "folder",
        "parentId": "5e5d8541c6efca74a8cacf20",
        "public": true,
        "size": 0,
        "updated": "2020-03-03T06:22:24.681000+00:00"
    }
}
```

<!-- ********************************************************************* -->
<!-- ********************************************************************* -->

#### Clear Versions

```
GET /version/clear
```

Clears all versions from a tale by removing all Girder folders that have a certain version root, but does not delete the corresponding directories on disk. This operation requires administrative access and is mostly indetnded for testing environments.

##### Parameters:
```python
rootId: string
```

The `rootId` parameter points to the versions root folder for a Tale (see [Get Root](#get-root)).

##### Errors:
`403 Access Denied`

##### Example:
```
curl -X GET\
    --header 'Girder-Token: Z8Kaa0rIY98FMxlipOOCnsdBYEG290BhkPQk7JuxA9oen86DkEw5fIhp6hxtWL2A'\
    'http://localhost:8080/api/v1/version/clear?rootId=5e5d8541c6efca74a8cacf20'
```

##### Example Response:

This operation does not have a response.

<!-- ********************************************************************* -->
<!-- ********************************************************************* -->

#### Create Run
```
POST /run
```

Creates a new run folder.

##### Parameters:
```python
versionId: string
[name: string]
```

An `versionId` must be specified, which is the version that will be associated with this run. Specifically, this association means that, if run and version filesystems are mounted properly, this run will contain a symbolic link to the version in question.

The optional `name` parameter allows a specfic name to be given to this run. Absend this parameter, the run will be named according to the current date and time using the `%c` format in the 1989 C standard (in en_US, this would be, for example, *Mon Jan 10 22:01:05 2019*).

##### Errors:

`403 Access Denied` - returned when the calling user does not have write access to the tale instance.

`400 Illegal File Name` - a `name` was specified, but is not a legal file name.

##### Example:
```
curl -X POST\
    --header 'Girder-Token: Z8Kaa0rIY98FMxlipOOCnsdBYEG290BhkPQk7JuxA9oen86DkEw5fIhp6hxtWL2A'\
    --header 'Content-Length: 0' --header 'Content-Type: application/json'\
    --header 'Accept: application/json'\
    'http://localhost:8080/api/v1/run?versionId=5e5df7a0e2c48f2e00a465e5'
```

##### Example response:
```json
{
    "_accessLevel": 2,
    "_id": "5ea6603a50d4f540f61f78b0",
    "_modelType": "folder",
    "baseParentId": "5e4b8ad832b7c36c2ec8f782",
    "baseParentType": "collection",
    "created": "2020-04-27T04:31:54.188564+00:00",
    "creatorId": "582f621ccbb11e75430a89ae",
    "description": "",
    "fsPath": "/home/mike/work/wt/wt_dirs/run/5e/5e5d8541c6efca74a8cacf1f/5ea6603a50d4f540f61f78b0",
    "isMapping": true,
    "name": "Sun Apr 26 21:31:54 2020",
    "parentCollection": "folder",
    "parentId": "5e5d8541c6efca74a8cacf21",
    "public": true,
    "size": 0,
    "updated": "2020-04-27T04:31:54.188564+00:00"
}
```

<!-- ********************************************************************* -->
<!-- ********************************************************************* -->

#### Get Run {#get-run}

```
GET /run/{id}
```

Returns the folder representing the run with `id == {id}`. In addition to the standard folder attributes, a run folder will also contain a `runStatus` attribute, which can take one of the following values:

`0` - Unknown

`1` - Starting

`2` - Running

`3` - Completed

`4` - Failed

`5` - Cancelled


##### Parameters:
```python
id: string
```

##### Errors:
`403 Access Denied`

##### Example:
```
curl -X GET\
    --header 'Girder-Token: Z8Kaa0rIY98FMxlipOOCnsdBYEG290BhkPQk7JuxA9oen86DkEw5fIhp6hxtWL2A'\
    --header 'Accept: application/json' 'http://localhost:8080/api/v1/run/5ea6603a50d4f540f61f78b0'
```

##### Example response:
```json
{
    "_id": "5ea6603a50d4f540f61f78b0",
    "access": {...},
    "baseParentId": "5e4b8ad832b7c36c2ec8f782",
    "baseParentType": "collection",
    "created": "2020-04-27T04:31:54.188000+00:00",
    "creatorId": "582f621ccbb11e75430a89ae",
    "description": "",
    "fsPath": "/home/mike/work/wt/wt_dirs/run/5e/5e5d8541c6efca74a8cacf1f/5ea6603a50d4f540f61f78b0",
    "isMapping": true,
    "lowerName": "sun apr 26 21:31:54 2020",
    "name": "Sun Apr 26 21:31:54 2020",
    "parentCollection": "folder",
    "parentId": "5e5d8541c6efca74a8cacf21",
    "public": true,
    "runStatus": 0,
    "runVersionId": "5e5df7a0e2c48f2e00a465e5",
    "size": 0,
    "updated": "2020-04-27T04:31:54.188000+00:00"
}
```

#### Rename Run

```
GET /run/{id}/rename
```

Renames a run

##### Parameters:
```python
id: string
newName: string
```

The `id` is the run id and `newName` is, again, unsurprisingly, the new name.

##### Errors:
`400 Illegal File Name` - if the name is not a valid POSIX filename
`403 Access Denied`


##### Example:
```
curl -X GET\
    --header 'Girder-Token: Z8Kaa0rIY98FMxlipOOCnsdBYEG290BhkPQk7JuxA9oen86DkEw5fIhp6hxtWL2A'\
    --header 'Accept: application/json'\
    'http://localhost:8080/api/v1/run/5ea6603a50d4f540f61f78b0/rename?newName=My%20Run'
```

##### Example response:
```json
{
    "_accessLevel": 2,
    "_id": "5ea6603a50d4f540f61f78b0",
    "_modelType": "folder",
    "baseParentId": "5e4b8ad832b7c36c2ec8f782",
    "baseParentType": "collection",
    "created": "2020-04-27T04:31:54.188000+00:00",
    "creatorId": "582f621ccbb11e75430a89ae",
    "description": "",
    "fsPath": "/home/mike/work/wt/wt_dirs/run/5e/5e5d8541c6efca74a8cacf1f/5ea6603a50d4f540f61f78b0",
    "isMapping": true,
    "name": "My Run",
    "parentCollection": "folder",
    "parentId": "5e5d8541c6efca74a8cacf21",
    "public": true,
    "size": 0,
    "updated": "2020-04-27T04:31:54.188000+00:00"
}
```

<!-- ********************************************************************* -->
<!-- ********************************************************************* -->

#### Get Run Status {#get-run-status}

```
GET /run/{id}/status
```

Retrieves the status of this run, both as a numeric code and a string identifier.

##### Parameters:
```python
id: string
```

The `id` path parameter must be the id of a run folder.

##### Errors:
`403 Access Denied`

##### Example:
```
curl -X GET\
    --header 'Girder-Token: Z8Kaa0rIY98FMxlipOOCnsdBYEG290BhkPQk7JuxA9oen86DkEw5fIhp6hxtWL2A'\
     --header 'Accept: application/json'\
     'http://localhost:8080/api/v1/run/5ea6603a50d4f540f61f78b0/status'
```

##### Example Response:
```json
{
    "status": 0,
    "statusString": "UNKNOWN"
}
```

<!-- ********************************************************************* -->
<!-- ********************************************************************* -->

#### Set Run Status

```
PATCH /run/{id}/status
```

Sets the status of the run. This operation is meant to be used by the backend that implements an actual run execution and not by the frontend. The numeric status is accessible both by invoking the [Get Run](#get-run) operation and through the `.status` file inside the run folder.

##### Parameters:
```python
id: string
status: int
```

The `id` path parameter must be the id of a run folder. The `status` parameter is the numeric status code that will be returned by the [Get Run Status](#get-run-status) operation.

##### Errors:
`403 Access Denied`

##### Example:
```
curl -X PATCH\
    --header 'Girder-Token: Z8Kaa0rIY98FMxlipOOCnsdBYEG290BhkPQk7JuxA9oen86DkEw5fIhp6hxtWL2A'\
     --header 'Accept: application/json'\
     --header 'Content-Length: 0'\
     'http://localhost:8080/api/v1/run/5ea6603a50d4f540f61f78b0/status?status=2'
```

##### Example Response:

There is no response body if the call succeeds.

<!-- ********************************************************************* -->
<!-- ********************************************************************* -->

#### Stream Run Output

```
PATCH /run/{id}/stream
```

Allows run implementations to stream STDOUT and/or STDERR data to this run. The data is appended to the `.stdout` and/or `.stderr` files inside the run folder, respectively.

##### Parameters:
```python
id: string
[stdoutData: string]
[stderrData: string]
```

The `id` is the run id and `stdoutData` and `stderrData` are strings that are to be appended to the `.stdout` and `.stderr` run files, respectively. One or both of `stdoutData` and `stderrData` must be specified.

##### Errors:
`403 Access Denied`


##### Example:
```
curl -X PATCH\
    --header 'Girder-Token: Z8Kaa0rIY98FMxlipOOCnsdBYEG290BhkPQk7JuxA9oen86DkEw5fIhp6hxtWL2A'\
     --header 'Accept: application/json'\
     --header 'Content-Length: 0'\
     'http://localhost:8080/api/v1/run/5ea6603a50d4f540f61f78b0/stream?stdoutData=data'
```

##### Example response:
There is no response body for a successful invocation of this operation.


<!-- ********************************************************************* -->
<!-- ********************************************************************* -->

#### Delete Run

```
DELETE /run/{id}
```

Deletes a run.

##### Parameters:
```python
id: string
```

The `id` parameter points to the id of the run folder to be deleted.

##### Errors:
`403 Access Denied`

##### Example:
```
curl -X DELETE\
    --header 'Girder-Token: Z8Kaa0rIY98FMxlipOOCnsdBYEG290BhkPQk7JuxA9oen86DkEw5fIhp6hxtWL2A'\
    --header 'Accept: application/json'\
    'http://localhost:8080/api/v1/run/5ea6603a50d4f540f61f78b0'
```

##### Example Response:

There is an empty response body if the operation was successful.

<!-- ********************************************************************* -->
<!-- ********************************************************************* -->

#### Get Runs Root {#get-runs-root}

```
GET /run/getRoot
```

Returns the runs root folder for an instance. The runs root folder is the parent folder to all the runs.


##### Parameters:
```python
instanceId: string
```

The `instanceId` parameter points to the instance of the tale whose runs root folder will be returned.

##### Example:
```
curl -X GET\
    --header 'Girder-Token: Z8Kaa0rIY98FMxlipOOCnsdBYEG290BhkPQk7JuxA9oen86DkEw5fIhp6hxtWL2A'\
    --header 'Accept: application/json'\
    'http://localhost:8080/api/v1/run/getRoot?instanceId=5e5d855ec6efca74a8cacf26'
```

##### Example Response:
```json
{
    "_accessLevel": 2,
    "_id": "5e5d8541c6efca74a8cacf21",
    "_modelType": "folder",
    "baseParentId": "5e4b8ad832b7c36c2ec8f782",
    "baseParentType": "collection",
    "created": "2020-03-02T22:14:25.749000+00:00",
    "creatorId": null,
    "description": "",
    "meta": {"taleId": "5e5d8541c6efca74a8cacf1f"},
    "name": "5e5d8541c6efca74a8cacf1f",
    "parentCollection": "folder",
    "parentId": "5e4b8ad832b7c36c2ec8f783",
    "public": true,
    "size": 0,
    "updated": "2020-04-27T04:31:54.191000+00:00"
}
```

<!-- ********************************************************************* -->
<!-- ********************************************************************* -->

#### List Runs

```
GET /run/list
```

Returns all the runs for a tale.

##### Parameters:
```python
rootId: string
[limit: int = 50]
[offset: int]
[sort: string = 'created']
[sortdir: int = 1]
```

The `rootId` parameter points to the runs root folder for a Tale (see [Get Runs Root](#get-runs-root)).

The optional parameters are standard paging and sorting parameters.

##### Errors:
`403 Access Denied`

##### Example:
```
curl -X GET\
    --header 'Girder-Token: Z8Kaa0rIY98FMxlipOOCnsdBYEG290BhkPQk7JuxA9oen86DkEw5fIhp6hxtWL2A'\
    --header 'Accept: application/json'\
    'http://localhost:8080/api/v1/run/list?rootId=5e5d8541c6efca74a8cacf21&limit=50&sort=created&sortdir=1'
```

##### Example Response:
```json
[
    {
        "_accessLevel": 2,
        "_id": "5e5eb44ee2c48f2e00a465f7",
        "_modelType": "folder",
        "baseParentId": "5e4b8ad832b7c36c2ec8f782",
        "baseParentType": "collection",
        "created": "2020-03-03T19:47:26.923000+00:00",
        "creatorId": "582f621ccbb11e75430a89ae",
        "description": "",
        "fsPath": "/home/mike/work/wt/wt_dirs/run/5e/5e5d8541c6efca74a8cacf1f/5e5eb44ee2c48f2e00a465f7",
        "isMapping": true,
        "name": "Tue Mar  3 11:47:26 2020",
        "parentCollection": "folder",
        "parentId": "5e5d8541c6efca74a8cacf21",
        "public": true,
        "size": 0,
        "updated": "2020-03-03T19:47:26.923000+00:00"
    },
    {
        "_accessLevel": 2,
        "_id": "5e5ec93ce2c48f2e00a465f8",
        "_modelType": "folder",
        "baseParentId": "5e4b8ad832b7c36c2ec8f782",
        "baseParentType": "collection",
        "created": "2020-03-03T21:16:44.400000+00:00",
        ...
    },
    ...
    ]
```

<!-- ********************************************************************* -->
<!-- ********************************************************************* -->

#### Run Exists

```
GET /run/exists
```

Checks if a run with the specified *name* exists and return it if it does. The returned object is an object with a mandatory field named `exists`, which is a boolean value indicating whether the specified run exists, and an optional field named `obj` which contains the relevant run if found.

##### Parameters:
```python
rootId: string
name: string
```

The `rootId` parameter points to the runs root folder for a Tale (see [Get Runs Root](#get-runs-root)). The `name` parameter is the name to check for.

##### Errors:
`403 Access Denied`

##### Example:
```
curl -X GET\
    --header 'Girder-Token: Z8Kaa0rIY98FMxlipOOCnsdBYEG290BhkPQk7JuxA9oen86DkEw5fIhp6hxtWL2A'\
    --header 'Accept: application/json'\
    'http://localhost:8080/api/v1/run/exists?rootId=5e5d8541c6efca74a8cacf21&name=Tue%20Mar%20%203%2011%3A47%3A26%202020'
```

##### Example Response:
```json
{
    "exists": true,
    "obj": {
        "_accessLevel": 2,
        "_id": "5e5eb44ee2c48f2e00a465f7",
        "_modelType": "folder",
        "baseParentId": "5e4b8ad832b7c36c2ec8f782",
        "baseParentType": "collection",
        "created": "2020-03-03T19:47:26.923000+00:00",
        "creatorId": "582f621ccbb11e75430a89ae",
        "description": "",
        "fsPath": "/home/mike/work/wt/wt_dirs/run/5e/5e5d8541c6efca74a8cacf1f/5e5eb44ee2c48f2e00a465f7",
        "isMapping": true,
        "name": "Tue Mar  3 11:47:26 2020",
        "parentCollection": "folder",
        "parentId": "5e5d8541c6efca74a8cacf21",
        "public": true,
        "size": 0,
        "updated": "2020-03-03T19:47:26.923000+00:00"
    }
}
```

<!-- ********************************************************************* -->
<!-- ********************************************************************* -->

#### Clear Runs

```
GET /run/clear
```

Clears all runs from a tale by removing all Girder folders that have a certain run root, but does not delete the corresponding directories on disk. This operation requires administrative access and is mostly indetnded for testing environments.

##### Parameters:
```python
rootId: string
```

The `rootId` parameter points to the runs root folder for a Tale (see [Get Runs Root](#get-runs-root)).

##### Errors:
`403 Access Denied`

##### Example:
```
curl -X GET\
    --header 'Girder-Token: Z8Kaa0rIY98FMxlipOOCnsdBYEG290BhkPQk7JuxA9oen86DkEw5fIhp6hxtWL2A'\
    'http://localhost:8080/api/v1/run/clear?rootId=5e5d8541c6efca74a8cacf21'
```

##### Example Response:

There is no response body when the operation is successful.

## FUSE Filesystems {#fuse-fss}

The FUSE filesystems are implementations of filesystems that allow a tale instance to access its own versions and runs as POSIX filesystem hierarchies. These are implemented in the [GirderFS WholeTale Plugin](https://github.com/whole-tale/girderfs). 
