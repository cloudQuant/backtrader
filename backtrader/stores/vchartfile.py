#!/usr/bin/env python
"""VChartFile Store Module - VisualChart file store.

This module provides the VChartFile store for accessing VisualChart
binary files by market code.

Classes:
    VChartFile: Store for VisualChart binary files.

Example:
    >>> store = bt.stores.VChartFile(path='C:\\VisualChart\\Data')
    >>> data = bt.feeds.VChartFile(dataname='015ES', store=store)
    >>> cerebro.adddata(data)
"""

import os.path
import traceback

from ..store import Store


class VChartFile(Store):
    """Store provider for Visual Chart binary files

    Params:

      - ``path`` (default:``None``):

        If the path is ``None`` and running under *Windows*, the registry will
        be examined to find the root directory of the *Visual Chart* files.
    """

    params = (("path", None),)

    def __init__(self):
        self._path = self.p.path
        if self._path is None:
            self._path = self._find_vchart()

    @staticmethod
    def _find_vchart():
        # Find VisualChart registry key to get data directory
        # If not found returns ''
        VC_KEYNAME = r"SOFTWARE\VCG\Visual Chart 6\Config"
        VC_KEYVAL = "DocsDirectory"
        VC_DATADIR = ["Realserver", "Data", "01"]

        VC_NONE = ""

        from backtrader.utils.py3 import winreg

        if winreg is None:
            return VC_NONE

        vcdir = None
        # Search for Directory in the usual root keys
        for rkey in (
            winreg.HKEY_CURRENT_USER,
            winreg.HKEY_LOCAL_MACHINE,
        ):
            try:
                vckey = winreg.OpenKey(rkey, VC_KEYNAME)
            except OSError as e:
                traceback.format_exception(e)
                continue

            # Try to get the key value
            try:
                vcdir, _ = winreg.QueryValueEx(vckey, VC_KEYVAL)
            except OSError as e:
                traceback.format_exception(e)
                continue
            else:
                break  # found vcdir

        if vcdir is not None:  # something was found
            vcdir = os.path.join(vcdir, *VC_DATADIR)
        else:
            vcdir = VC_NONE

        return vcdir

    def get_datapath(self):
        return self._path
