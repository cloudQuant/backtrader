#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

from collections import OrderedDict
import sys
from .date import *
from .ordereddefaultdict import *
from .autodict import *
from .cython_config import (
    set_extra_link_args,
    set_compile_args,
    set_cpp_version,
    set_optimize_option,
)
