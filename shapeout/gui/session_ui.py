#!/usr/bin/python
# -*- coding: utf-8 -*-
"""ShapeOut - session handling"""
from __future__ import division, print_function, unicode_literals

from distutils.version import LooseVersion
import os
import shutil
import tempfile
import zipfile
import warnings

import wx


from ..session.conversion import compatibilitize_session, \
                                 search_hashed_measurement, \
                                 update_session_hashes

from ..session import index, rw


def open_session(parent, session_file=None):
    """Open a session file into shapeout
    
    This is a dialog wrapper for `open_session_worker`. 
    """
    # Determine which session file to open
    if session_file is None:
        # User dialog
        dlg = wx.FileDialog(parent,
                            "Open session file",
                            parent.config.get_dir(name="Session"),
                            "",
                            "ShapeOut session (*.zmso)|*.zmso", wx.FD_OPEN)
        
        if dlg.ShowModal() == wx.ID_OK:
            parent.config.set_dir(dlg.GetDirectory(), name="Session")
            fname = dlg.GetPath()
            dlg.Destroy()
        else:
            parent.config.set_dir(dlg.GetDirectory(), name="Session")
            dlg.Destroy()
            return # nothing more to do here
    else:
        fname = session_file 

    open_session_worker(fname, parent)


def open_session_worker(path, parent):
    """Open a session file into shapeout
    
    This method performs a lot of logic on `parent`, the
    graphical user interface itself, such as cleanup and
    post-processing steps before and after data import.
    """
    # Cleanup
    delist = [parent, parent.PanelTop, parent.PlotArea]
    for item in delist:
        if hasattr(item, "analysis"):
            del item.analysis
    
    Arc = zipfile.ZipFile(path, mode='r')
    tempdir = tempfile.mkdtemp(prefix="ShapeOut-session_")
    Arc.extractall(tempdir)
    Arc.close()
    
    # The ShapeOut version used to create the session is returned:
    # Do not perform hash update, because we do not know if all
    # measurement files are where they're supposed to be. 
    version = compatibilitize_session(tempdir, hash_update=False)
    
    index_file = os.path.join(tempdir, "index.txt")
    index_dict = index.index_load(index_file)

    # check session integrity
    dirname = os.path.dirname(path)
    messages = index.index_check(index_file, search_path=dirname)
    while messages["missing files"]:
        # There are missing files. We need to modify the extracted
        # index file with a folder.
        missing = messages["missing files"]
        directories = [] # search directories
        updict = {}      # new dicts for individual measurements
        # Ask user for directory
        miss = os.path.basename(missing[0][1])
        
        message = "ShapeOut could not find the following measurements:"+\
                  "\n\n".join([""]+[m[1] for m in missing]) +"\n\n"+\
                  "Please select a directory that contains these."
        
        dlg = wx.MessageDialog(parent,
                               caption="Missing files for session",
                               message=message,
                               style=wx.CANCEL|wx.OK,
                               )
        mod = dlg.ShowModal()
        dlg.Destroy()
        if mod != wx.ID_OK:
            break
        
        sd = "SessionMissingDirSearch"
        msg = "Please select directory containing {}".format(miss)
        dlg = wx.DirDialog(parent,
                           message=msg,
                           defaultPath=parent.config.get_dir(name=sd)
                           )
        mod = dlg.ShowModal()
        path = dlg.GetPath()
        parent.config.set_dir(wd=path, name=sd)
        dlg.Destroy()
        if mod != wx.ID_OK:
            break

        # Add search directory            
        directories.insert(0, path)
        
        # Try to find all measurements with that directory (also relative)
        wx.BeginBusyCursor()
        remlist = []
        for m in missing:
            key, mfile, index_item = m
            newfile = search_hashed_measurement(mfile,
                                                index_item,
                                                directories,
                                                version=version)
            if newfile is not None:
                newdir = os.path.dirname(newfile)
                # Store the original directory name. This is important
                # for sessions stored with ShapeOut version <0.7.6 to
                # correctly compute tdms file hashes.
                updict[key] = {"fdir": newdir,
                               "fdir_orig":index_dict[key]["fdir"],
                               }
                directories.insert(0, os.path.dirname(newdir))
                directories.insert(0, os.path.dirname(os.path.dirname(newdir)))
                remlist.append(m)
        for m in remlist:
            missing.remove(m)
        wx.EndBusyCursor()

        # Update the extracted index file.
        index.index_update(index_file, updict)
    
    # Update hash values of tdms and hierarchy children
    if version < LooseVersion("0.7.6"):
        update_session_hashes(tempdir, search_path=dirname)
    
    # Catch hash comparison warnings and display warning to the user
    with warnings.catch_warnings(record=True) as ww:
        warnings.simplefilter("always", category=rw.HashComparisonWarning)
        rtdc_list = rw.load(tempdir, search_path=dirname)
        if len(ww):
            msg = "One or more files referred to in the chosen session "+\
                  "did not pass the hash check. Nevertheless, ShapeOut "+\
                  "loaded the data. The following warnings were issued:\n"
            msg += "".join([ "\n - "+w.message.message for w in ww ])
            dlg = wx.MessageDialog(None,
                                   msg,
                                   'Hash mismatch warning',
                                   wx.OK | wx.ICON_WARNING)
            dlg.ShowModal()

    parent.NewAnalysis(rtdc_list)

    directories = []
    for mm in parent.analysis.measurements:
        fdir = os.path.dirname(mm.path)
        if os.path.exists(fdir):
            directories.append(fdir)
    
    bolddirs = parent.analysis.GetFilenames()

    parent.OnMenuSearchPathAdd(add=False, path=directories,
                               marked=bolddirs)
    
    # Remove all temporary files
    shutil.rmtree(tempdir, ignore_errors=True)


def save_session(parent):
    dlg = wx.FileDialog(parent, "Save ShapeOut session", 
                parent.config.get_dir(name="Session"), "",
                "ShapeOut session (*.zmso)|*.zmso",
                wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT)
    if dlg.ShowModal() == wx.ID_OK:
        # Save everything
        path = dlg.GetPath()
        if not path.endswith(".zmso"):
            path += ".zmso"
        dirname = os.path.dirname(path)
        parent.config.set_dir(dirname, name="Session")
        rw.save(path, parent.analysis.measurements)
        return path
    else:
        dirname = dlg.GetDirectory()
        parent.config.set_dir(dirname, name="Session")
        dlg.Destroy()
