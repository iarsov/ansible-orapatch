
"""

    @author: Ivica Arsov
    @contact: https://blog.iarsov.com/contact

    @last_update: 23.12.2019

    File name:          orapatch.py
    Version:            2.0
    Purpose:            Automation for Oracle software binaries patching
    Author:             Ivica Arsov (ivica@iarsov.com)
    Copyright:          (c) Ivica Arsov - https://blog.iarsov.com - All rights reserved.
    Disclaimer:         This script is provided "as is", so no warranties or guarantees are made
                        about its correctness, reliability and safety. Use it at your own risk!
    License:            1) You may use this module for your (or your businesses) purposes for free.
                        2) You may modify this script as you like for your own (or your businesses) purpose,
                        but you must always leave this script header (the entire comment section), including the
                        author, copyright and license sections as the first thing in the beginning of this file
                        3) You may NOT publish or distribute this script, or packaged jar files,
                        or any other variation of it PUBLICLY (including, but not limited to uploading it to your public website or ftp server),
                        instead just link to its location in https://github.com/iarsov/ansible-orapatch
                        4) You may distribute this script INTERNALLY in your company, for internal use only,
                        for example when building a standard DBA toolset to be deployed to all
                        servers or DBA workstations
    Python version:     3.x

"""

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

from ansible.plugins.action import ActionBase

class ActionModule(ActionBase):

    def run(self, tmp=None, task_vars=None):

        # define empty dict if task_vars is not defined
        if task_vars is None:
            task_vars = dict()

        result = super(ActionModule, self).run(tmp, task_vars)

        # get module arguments
        args = self._task.args.copy()

        args["ansible_hostname"] = task_vars["ansible_hostname"]

        if args["function"] == "START_LOGGER_SESSION" or args["function"] == "END_LOGGER_SESSION":

            # set dummy values
            args["oracle_home"] = None
            args["only_prereq"] = None
            args["patch_id"] = None
            args["swlib_path"] = None
            args["patch_only_oh"] = None
            args["patch_ojvm"] = None
            args["patch_db_all"] = None
            args["patch_db_list"] = None
            args["orapatch_logfile"] = task_vars["orapatch_logfile"]
            args["patch_item"] = None
            args["root_password"] = None
            args["oratab_file"] = None

            if "debug" not in task_vars:
                args["debug"] = False
            else:
                args["debug"] = task_vars["debug"]

        else:

            db_item = args["item"]

            if "debug" not in task_vars or not task_vars["debug"]:
                if "debug" not in db_item:
                    args["debug"] = False
                else:
                    args["debug"] = db_item["debug"]
            else:
                args["debug"] = task_vars["debug"]

            args["oracle_home"] = db_item["oracle_home_path"]
            args["only_prereq"] = db_item["run_only_checks"]
            args["patch_id"] = db_item["patch_id"]
            args["swlib_path"] = task_vars["swlib_path"]
            args["patch_only_oh"] = db_item["patch_only_oh"]
            args["patch_ojvm"] = db_item["patch_ojvm"]
            args["patch_db_all"] = db_item["patch_db_all"]
            args["patch_db_list"] = db_item["patch_db_list"]
            args["orapatch_logfile"] = task_vars["orapatch_logfile"]

            if "oratab_file" in db_item and db_item["oratab_file"] is not None:
                args["oratab_file"] = db_item["oratab_file"]
            else:
                args["oratab_file"] = task_vars["oratab_file"]

            patch_id = db_item["patch_id"]
            patch_dict = task_vars["patch_dict"]

            try:

                patch_item = patch_dict[patch_id]
                patch_item["patch_id"] = patch_id
                args["patch_item"] = patch_item

            except Exception as e:

                result['failed'] = True
                result['msg'] = "Patch '" + str (patch_id) + "'not found!"
                result['msg'] += str (e)
                return result

            #v_root_password = task_vars["root_password"]
            #v_root_password_confirm = task_vars["root_password_confirm"]

            #if v_root_password == v_root_password_confirm:
            args["root_password"] = task_vars["root_password"]
            #else:
            #    result['failed'] = True
            #    result['msg'] = "Root password missmatch."
            #    return result

            # Clear item argument
            del args["item"]


        # run module
        result.update(self._execute_module(module_args=args, task_vars=task_vars))

        return result
