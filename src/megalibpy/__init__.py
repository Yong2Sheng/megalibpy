#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sat Nov 30 20:47:47 2024

@author: shengyong
"""

from importlib.metadata import version

from .cosima import Cosima
from .execution import ExecutionError, ExecutionResult, MEGAlibRuntime, SimulationWorkspace
from .revan import Revan
from .megalib_source import BaseParams, MEGAlibSource, Run, RunConfig, Source
from .test_data import test_data_path as test_data

__version__ = version("megalibpy")

__all__ = [
    "BaseParams", "MEGAlibSource", "RunConfig", "Run", "Source", "test_data",
    "Cosima", "MEGAlibRuntime", "ExecutionResult", "ExecutionError",
    "Revan", "SimulationWorkspace",
]
