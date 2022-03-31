#!/usr/bin/env python
# -*- coding: utf-8 -*-

FIELD_STATUS_CODE = "runStatus"


class Constants:
    VERSIONS_ROOT_DIR_NAME = "WholeTale Tale Versions"
    RUNS_ROOT_DIR_NAME = "WholeTale Tale Runs"


class PluginSettings:
    VERSIONS_DIRS_ROOT = 'wtversioning.versions_root'
    RUNS_DIRS_ROOT = 'wtversioning.runs_root'


class RunState:
    ALL = {}  # type: dict

    def __init__(self, code: int, name: str):
        self.code = code
        self.name = name
        RunState.ALL[code] = self


class RunStatus:
    UNKNOWN = RunState(0, 'UNKNOWN')
    STARTING = RunState(1, 'STARTING')
    RUNNING = RunState(2, 'RUNNING')
    COMPLETED = RunState(3, 'COMPLETED')
    FAILED = RunState(4, 'FAILED')
    CANCELLED = RunState(5, 'CANCELLED')

    @classmethod
    def get(cls, code: int) -> RunState:
        return RunState.ALL[code]
