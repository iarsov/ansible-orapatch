#!/usr/bin/python

"""

    @author: Ivica Arsov
    @contact: https://blog.iarsov.com/contact

    @last_update: 03.08.2020

    File name:          orapatch.py
    Version:            2.0.3
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

# Import libraries
import datetime
import subprocess
import re
import time
import json
from distutils.util import strtobool
try:
    import pexpect
    pexpect_found = True
except ImportError:
    pexpect_found = False
import os
import xml.etree.ElementTree as ET
import traceback
from ansible.module_utils.basic import AnsibleModule

# Define global variables
g_supported_version_old = [10,11]
g_supported_version_new = [12,18,19]
g_function = "CHECK_OPATCH_MIN_VERSION"
g_file_oratab = "/etc/oratab"
g_sw_opatch_check_conflict_pattern = "Prereq \"checkConflictAgainstOHWithDetail\" passed"
g_sw_opatch_spacecheck_pattern = "Prereq \"checkSystemSpace\" passed"
g_sw_opatch_min_version = "Prereq \"checkMinimumOPatchVersion\" passed"
g_sw_opatch_check_pattern1 = "OPatch succeeded"
g_sw_opatch_check_pattern2 = "OPatch(.*)completed with warnings"
g_sw_opatch_no_need = "No need to apply this patch"
g_sw_opatchauto_check_pattern12 = "OPatchAuto successful"
g_sw_opatchauto_check_pattern11 = "opatch auto succeeded"
g_sw_opatch_check_patch_nonexist = "Inventory check failed: Patch ID (\d+) is NOT registered in Oracle Home"
g_sw_opatch_check_patch_exist = "Files check OK: Files from Patch ID (\d+) are present in Oracle Home."
g_inst_status = "is running on node"
g_check_cluster_state = "The cluster upgrade state is \[NORMAL\]"
g_root_password = None
g_changed = False
g_output = {}
g_instance_list = {}
g_listener_list = {}
g_patch_applied = False
g_debug = False
g_hostname = None
g_expected_list = { 'Do you want to proceed\? \[y\|n\]': 'y\r',
                'Email address/User Name:': '\r',
                'Do you wish to remain uninformed of security issues \(\[Y\]es, \[N\]o\) \[N\]': 'y\r',
                'Is the local system ready for patching\? \[y\|n\]': 'y\r' }
g_logger_file = ""
g_ocmrf_file = "/tmp/orapatch_ocm_" + time.strftime("%Y-%m-%d_%I-%M-%S%p")+".rsp"
g_inventory_file = ""

# @Description:
#   Function to convert value to boolean
# @Return:
#   Boolean
# @Exception:
#   Invalid value is specified
#
def gf_to_bool(p_value):
    """
       Converts 'something' to boolean. Raises exception for invalid formats
           Possible True  values: 1, True, "1", "TRue", "yes", "y", "t"
           Possible False values: 0, False, None, [], {}, "", "0", "faLse", "no", "n", "f", 0.0, ...
    """
    if str(p_value).lower() in ("yes", "y", "true",  "t", "1"): return True
    if str(p_value).lower() in ("no",  "n", "false", "f", "0", "0.0", "", "none", "[]", "{}"): return False

    raise Exception('Invalid value for boolean conversion: ' + str(p_value))

# @Description:
#   Function to trigger module failure
# @Return:
#   None
# @Exception:
#   Module failure
#
def fail_module(p_message, p_code = 245):
    logger("Module fail: " + str (p_message))
    module.fail_json(rc = p_code, msg = "[orapatch] module fail: " + str (p_message))

# @Description:
#   Function to return current time in specific format
#   Format: %Y-%m-%d_%H-%M-%S
# @Parameters:
#   None
# @Return:
#   String
# @Exception:
#   None
#
def gf_gettime():

    return time.strftime("%Y-%m-%d_%H-%M-%S")

# @Description:
#   Function to log given message to OS log file
#   This function is used through out the code to log specific events
# @Parameters:
#   p_message: Message to be logged
#   p_notime: Indicator whether to include timestamp with the message
# @Return:
#   None
# @Exception:
#   None
#
def logger(p_message, p_notime = False):

    if not p_notime:
        v_message = time.strftime("%c") + "\t" + p_message + "\n"
    else:
        v_message = p_message + "\n"

    f = open(g_logger_file,'a')
    f.write(v_message)
    f.close

# @Description:
#   Function to put informational message in logfile for session start
# @Parameters:
#   None
# @Return:
#   None
# @Exception:
#   None
#
def gf_start_logger_session():

    logger("--------------------------------", True)
    logger("orapatch session start")
    logger("--------------------------------", True)

# @Description:
#   Function to put informational message in logfile for session end
# @Parameters:
#   None
# @Return:
#   None
# @Exception:
#   None
#
def gf_end_logger_session():

    logger("--------------------------------", True)
    logger("orapatch session end")
    logger("--------------------------------", True)

# @Description:
#   Function to check if given oracle home is part of a cluster
#   The check is based on "NODE_LIST" argument in invetory file
#   Cluster oracle homes have the "NODE_LIST" argument which specifies each node
#
# @Parameters:
#   p_oracle_home = ORACLE_HOME path
# @Return:
#   None
# @Exception:
#   Fail if specified oracle home is not found in inventory
#
def gf_is_cluster(p_oracle_home):
    global g_inventory_file
    v_tree = ET.parse(g_inventory_file)
    v_root = v_tree.getroot()

    for inventory in v_root.findall('HOME_LIST'):
       for home in inventory.findall('HOME'):
          #print(home.get('LOC'))
          if home.get('LOC') == p_oracle_home:
              if home.find('NODE_LIST'):
                  logger("Oracle home ["+p_oracle_home+"] is part of a cluster.")
                  return True
              else:
                  logger("Oracle home ["+p_oracle_home+"] is not part of a cluster.")
                  return False

    logger("Oracle home ["+p_oracle_home+"] not found in inventory.")
    fail_module("Oracle home ["+p_oracle_home+"] not found in inventory.")

# @Description:
#   Class: DatabaseFactory
#   It creates a database object
# @Parameters:
#   None
# @Constructor parameters:
#   p_sid: Instance SID name
#   p_version: Database version (10,11,12)
#   p_db_name: Database name
#   p_is_asm: Indicator whether the instance is ASM
#   p_is_rac: Indicator whether the database is RAC database
#   p_is_standby: Indicator whether the database is standby database
#   p_instance_list: List of all (RAC) instances, if it is RAC
#   p_is_active: False #not used
#   p_initial_state: Initial state of the database (OPEN, MOUNT)
#   p_oracle_home: Database oracle home path
#   p_hostname: Hostname where the database is located
#   p_crs_registered: Indicator whether database is part of CRS:
#                     Oracle Restart or Clusterware.
#   p_patch: indicator Whether to patch database data dictionary
#   p_db_unique_name: Database unique name
# @Return:
#   None
# @Exception:
#   None
#
class DatabaseFactory(object):

    def __init__(self, p_sid, p_version, p_db_name, p_is_asm = False, p_is_rac = False
                     , p_is_standby = False, p_instance_list = None, p_is_active = False
                     , p_initial_state = None, p_oracle_home = None, p_hostname = None
                     , p_crs_registered = False, p_patch = False, p_db_unique_name = None):

        self.sid            = p_sid
        self.version        = p_version
        self.name           = p_db_name
        self.is_asm         = p_is_asm
        self.is_rac         = p_is_rac
        self.is_standby     = p_is_standby
        self.instance_list  = p_instance_list
        self.is_active      = p_is_active
        self.initial_state  = p_initial_state
        self.version_short  = p_version
        self.oracle_home    = p_oracle_home
        self.hostname       = p_hostname
        self.crs_registered = p_crs_registered
        self.patch          = p_patch
        self.db_unique_name = p_db_unique_name

# @Description:
#   Class: ListenerFactory
#   It creates a listener object
# @Parameters:
#   None
# @Constructor parameters:
#   p_listener_name: Listener name
#   p_oracle_home: Listener's home
# @Return:
#   None
# @Exception:
#   None
#
class ListenerFactory(object):

    def __init__(self, p_listener_name, p_oracle_home):

        self.listener_name = p_listener_name
        self.oracle_home = p_oracle_home

# @Description:
#   Class: PatchFactory
#   It creates a patch object
#   For each patch that needs to be applied an object is created
#   Patch attributes are defined in separate file named patch_dict.yml
# @Parameters:
#   None
# @Constructor parameters:
#   p_patch_id: Patch ID
#   p_patch_proactive_bp_id: Proactive bundle patch ID
#   p_patch_gi_id: Grid infrastructure patch ID
#   p_patch_db_id: Database patch ID
#   p_patch_ocw_id: OCW patch ID
#   p_patch_ojvm_id: OJVM patch ID
#   p_patch_acfs_id: ACFS patch ID
#   p_patch_dbwlm_id: DBWLM patch ID
#   p_patch_dir: Patch directory
#   p_file: Patch (zip) file name
#   p_only_oh: Indicator whether the patch is only for OH without SQL changes
#   p_desc: Patch description
# @Return:
#   None
# @Exception:
#   None
#
class PatchFactory(object):

    def __init__(self,  p_patch_id,
                        p_patch_proactive_bp_id,
                        p_patch_gi_id,
                        p_patch_db_id,
                        p_patch_ocw_id,
                        p_patch_ojvm_id,
                        p_patch_acfs_id,
                        p_patch_dbwlm_id,
                        p_patch_dir,
                        p_file,
                        p_only_oh,
                        p_desc):

        self.patch_id               = p_patch_id
        self.patch_proactive_bp_id  = p_patch_proactive_bp_id
        self.patch_gi_id            = p_patch_gi_id
        self.patch_db_id            = p_patch_db_id
        self.patch_ocw_id           = p_patch_ocw_id
        self.patch_ojvm_id          = p_patch_ojvm_id
        self.patch_dir              = str (p_patch_dir)
        self.file                   = p_file
        self.desc                   = p_desc
        self.only_oh                = p_only_oh
        self.patch_acfs_id          = p_patch_acfs_id
        self.patch_dbwlm_id         = p_patch_dbwlm_id

        if p_patch_proactive_bp_id:
            self.is_dbbp = True
        else:
            self.is_dbbp = False

        if p_patch_ojvm_id and (p_patch_proactive_bp_id or p_patch_db_id or p_patch_gi_id):
            self.is_combo = True
        else:
            self.is_combo = False

        if p_patch_gi_id:
            self.is_grid = True
        else:
            self.is_grid = False

# @Description:
#   Class: PatchProcess
#   Class where all magic happens
# @Parameters:
#   None
# @Constructor parameters:
#   p_oracle_home: Oracle home path
#   p_only_prereq: Indicator whether to run only prerequisites
#   p_patch_id: Patch ID of the patch to be appled
#   p_sw_stage: OS location of the patch binaries
#   p_patch_only_oh: Indicator whether to patch only oracle home without applying SQL changes
#   p_patch_ojvm: Indicator whether to apply OJVM patch
#   p_patch_db_all: Indicator whether to patch all databases for given oracle home
#   p_patch_db_list: If not all databases need to be patched
#                    This list contains which databases to patch
#   p_patch_item: Patch definition. It contains argument definitions from patch_dict.yml file
# @Return:
#   None
# @Exception:
#   None
#
class PatchProcess(object):

    def __init__(self, p_oracle_home, p_only_prereq,
                       p_patch_id, p_sw_stage,
                       p_patch_only_oh = None,
                       p_patch_ojvm = None, p_patch_db_all = None,
                       p_patch_db_list = None, p_patch_item = None):


        self.oracle_home = p_oracle_home
        self.only_prereq = p_only_prereq
        self.patch_id    = p_patch_id
        self.sw_stage    = p_sw_stage
        self.patch_list  = {}
        self.patch_item  = p_patch_item
        self.is_crs     = False
        self.is_cluster = False

        # Run this block if "prerequisites" flag is false
        # The user has chosen to apply patch
        if not p_only_prereq:

            # Check if required parameters are set to True/False
            # If not been specified, terminate module execution
            # One of the following parameters needs to be defined:
            #   p_patch_only_oh: Indicator whether to patch *only* oracle home
            #   p_patch_ojvm: Indicator whether to apply OJVM patch
            #   p_patch_db_all: Indicator whether to patch all databases
            if p_patch_only_oh == None or p_patch_ojvm == None or p_patch_db_all == None:
                # Terminate module execution
                fail_module("Specify all required arguments.")

            self.patch_only_oh  = p_patch_only_oh
            self.patch_ojvm     = p_patch_ojvm
            self.patch_db_all   = p_patch_db_all
            self.patch_db_list  = None

            # Check if the user has specified a list of databases to be patched
            # The list is comma (,) separated list of databases
            # The list can be empty (None)
            # Strip the defined list of databases
            if p_patch_db_list and p_patch_db_list.strip():
                # Populate "patch_db_list" array from user defined list
                # The list is split by comma (,)
                self.patch_db_list  = p_patch_db_list.split(',')

        self.set_inventory()

        # Prepare a command to check if the given oracle home is GI (CRS) home
        command = "grep \"LOC=\\\"" + self.oracle_home + "\\\"\" " + g_inventory_file + " | grep -i \"CRS=\\\"true\\\"\" | wc -l"
        output = self.run_os_command(command)
        # If the given oracle home is GI (CRS) home, set "is_crs" to True
        if output and int(output) == 1:
            self.is_crs = True
        else:
            # Note: 11g homes does not have CRS attribute in inventory.xml
            # Workaround: Check for ohasd.bin existence in $ORACLE_HOME/bin dir
            command = "ls " + self.oracle_home + "/bin | grep -iw [o]hasd.bin | wc -l"
            output = self.run_os_command(command)
            if output and int(output) == 1:
                self.is_crs = True
            else:
                self.is_crs = False


        #start: check if is cluster

        #todo: gf_is_cluster needs to be checked/validated
        command = "ls " + self.oracle_home + "/bin | grep -iw [c]emutlo.bin | wc -l"
        output = self.run_os_command(command)
        if output and int(output) == 1:
            command = self.oracle_home + "/bin/cemutlo -n"
            output = self.run_os_command(command)
            if (output):
                self.is_cluster = True
                self.cluster_name = str (output)

        # # Check if the given oracle home is part of a clusterware
        # if gf_is_cluster(self.oracle_home):
        #     # Set indicator "is_cluster" to True
        #     self.is_cluster = True
        #     # Get cluster name
        #     command = self.oracle_home + "/bin/cemutlo -n"
        #     output = self.run_os_command(command)
        #     self.cluster_name = str (output)

        #end: check if is cluster


        # Define oracle home installed version
        # 10/11/12
        self.oh_version = self.get_oh_version(p_oracle_home)

        # If oracle home version is 10 or 11 define OCM file
        # OCM file is needed when patching 10g and 11g oracle homes
        if self.oh_version in g_supported_version_old and (g_function == "PATCH_OH" or g_function == "PATCH_OH_OJVM"):
            self.gen_ocm_file(p_oracle_home)

    # @Description:
    #   Identifies and sets OH inventory file
    # @Parameters:
    #   None
    # @Return:
    #   None
    # @Exception:
    #   None
    #
    def set_inventory(self):
        global g_inventory_file

        v_orainst_file = self.oracle_home + "/oraInst.loc"
        v_command = "[ -f " + v_orainst_file + " ] && echo 1 || echo 0"
        output = self.run_os_command(v_command)

        if int(output) == 1:
            v_command = "grep inventory_loc " + v_orainst_file + " | awk -F= '{ print $2 }'"
            output = self.run_os_command(v_command)
        else:
            v_command = "grep inventory_loc /etc/oraInst.loc | awk -F= '{ print $2 }'"
            output = self.run_os_command(v_command)

        logger("Inventory location [inventory_loc]: " + output)
        g_inventory_file = output + "/ContentsXML/inventory.xml"

    # @Description:
    #   Generates OCM file required for OPatch
    # @Parameters:
    #   p_oracle_home: oracle home for which to generate OCM file
    # @Return:
    #   None
    # @Exception:
    #   None
    #
    def gen_ocm_file(self, p_oracle_home):
        global g_ocmrf_file
        global g_expected_list

        # Set environment variables
        self.set_env(p_oracle_home)

        # Prepare the command to generate OCM file
        v_command = p_oracle_home + "/OPatch/ocm/bin/emocmrsp -no_banner -output " + g_ocmrf_file
        self.run_os_command(v_command, p_expect = True)

    # @Description:
    #   Generates OCM file required for OPatch
    # @Parameters:
    #   p_oracle_home: oracle home for which to generate OCM file
    # @Return:
    #   int
    # @Exception:
    #   None
    #
    #todo: check for version > 12
    def get_oh_version(self, p_oracle_home):

        # Prepare the command to get oracle installed version
        # Current check is based on libcell library
        # The library name contains version number
        # Examples:
        #   10g: libcell10.so
        #   11g: libcell11.so
        #   12c: libcell12.so
        #command = "ls " + p_oracle_home + "/lib | grep libcell.*.so | awk '{ if ($0 == \"libcell10.so\"){ print 10 } if ($0 == \"libcell11.so\"){ print 11 } if ($0 == \"libcell12.so\") { print 12 } }'"
        command = "ls " + p_oracle_home + "/lib | gawk 'match($0, /libcell([[:digit:]][[:digit:]])\.so/, res) { print res[1] }'"
        v_result = self.run_os_command(command)

        if (v_result):
            return int(v_result)

        else:
            logger("Could not determine Oracle version.")
            fail_module("Could not determine Oracle version.")

    # @Description:
    #   Sets oracle environment
    # @Parameters:
    #   p_ora_home: oracle home for which to ORACLE_HOME environment
    # @Return:
    #   None
    # @Exception:
    #   None
    #
    def set_env(self, p_ora_home):

        logger("ORACLE_HOME set to to '" + p_ora_home + "'")
        os.environ["ORACLE_HOME"] = p_ora_home

    # @Description:
    #   This function creates an object from PatchFactory
    #   The object contains details for the patch to be installed
    # @Parameters:
    #   None
    # @Return:
    #   None
    # @Exception:
    #   Module failure
    #
    def build_patch_dict(self):

        #global patch_list
        v_patch_temp = None

        p_patch_id              = self.patch_item["patch_id"]
        p_patch_proactive_bp_id = self.patch_item["patch_proactive_bp_id"]
        p_patch_gi_id           = self.patch_item["patch_gi_id"]
        p_patch_db_id           = self.patch_item["patch_db_id"]
        p_patch_ocw_id          = self.patch_item["patch_ocw_id"]
        p_patch_ojvm_id         = self.patch_item["patch_ojvm_id"]
        p_patch_dir             = self.patch_item["patch_dir"]
        p_file                  = self.patch_item["file"]
        p_only_oh               = gf_to_bool(self.patch_item["only_oh"])
        p_desc                  = self.patch_item["desc"]
        p_patch_acfs_id         = self.patch_item["patch_acfs_id"]
        p_patch_dbwlm_id        = self.patch_item["patch_dbwlm_id"]

        v_patch_temp = PatchFactory(p_patch_id, p_patch_proactive_bp_id,
                                  p_patch_gi_id, p_patch_db_id, p_patch_ocw_id,
                                  p_patch_ojvm_id, p_patch_acfs_id,
                                  p_patch_dbwlm_id, p_patch_dir,
                                  p_file, p_only_oh, p_desc)

        self.patch_list[p_patch_id] = v_patch_temp

        # If patch is not found throw fail message
        if not v_patch_temp:

            fail_module("Patch " + str (self.patch_id) + " not found!")

    # @Description:
    #   Function to execute OS command
    # @Parameters:
    #   p_command: command to be executed
    #   p_expect: indicator whether the command requires user input
    #             In case of an user input, the questions are matched 
    #             against g_expect_list provided answers
    # @Return:
    #   Command output/result
    # @Exception:
    #   Module failure
    #
    def run_os_command(self, p_command, p_expect = False):

        v_error = None
        v_output = ""
        global g_expected_list

        logger("command: " + p_command)

        if p_expect:

            timeout = 3600 # 60 minutes
            #s = pexpect.pxssh()

            #try:

            # Prefer pexpect.run
            v_output, v_error = pexpect.run(p_command, timeout = timeout, withexitstatus = True, events = g_expected_list)

            #except TypeError:

            #    try:
            #
            #        v_output, v_error = pexpect.runu(p_command, timeout = timeout, withexitstatus = True, events = g_expected_list)
            #
            #    except:
            #        raise
        else:

            process = subprocess.Popen(p_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
            v_output, v_error = process.communicate()
        
        v_output = v_output.decode('ascii').strip()
        
        try:
            v_error = v_error.decode('ascii').strip()
        except AttributeError:
            # if "v_error" returns 0
            pass

        if g_debug:            
            logger("---------------------------", True)
            logger("output:", False)
            logger(str (v_output), True)
            logger("---------------------------", True)

        # 1. If there is an error terminate the module execution.
        # (and) 2. If the error is reported for "OPatch Session completed with warnings" don't terminate the module execution.
        if v_error and re.search(g_sw_opatch_check_pattern2,str (v_error)) is None:

            if g_debug:
                logger("subprocess error: " + str (v_error))

            fail_module(v_error)

        else:

            return str (v_output)

    # @Description:
    #   Function to check OPatch required version
    #   It checks OPatch required version for all patches
    # @Parameters:
    #   None
    # @Return:
    #   None
    # @Exception:
    #   Module failure if OPatch version check fails
    #
    def check_opatch_min_version(self):

        global g_sw_opatch_min_version

        v_oracle_home   = str (self.oracle_home)
        v_sw_stage      = str (self.sw_stage)

        for patch in self.patch_list:

            v_patch_obj = self.patch_list[patch]

            logger("Check minumum OPatch version for OH: " + self.oracle_home)

            v_patch_dir = v_patch_obj.patch_dir
            v_patch_proactive_bp_id = v_patch_obj.patch_proactive_bp_id
            v_patch_gi_id = v_patch_obj.patch_gi_id
            v_patch_db_id = v_patch_obj.patch_db_id
            v_patch_id = v_patch_obj.patch_id
            v_is_combo = v_patch_obj.is_combo

            v_command = v_oracle_home + "/OPatch/opatch prereq CheckMinimumOPatchVersion -phBaseDir " + v_sw_stage + "/" + v_patch_dir

            if v_is_combo:
                if v_patch_proactive_bp_id:
                    v_command += "/" + str (v_patch_proactive_bp_id) + "/" + str (v_patch_db_id)
                elif v_patch_gi_id:
                    v_command += "/" + str (v_patch_gi_id) + "/" + str (v_patch_db_id)

            output = self.run_os_command(v_command)

            if re.search(g_sw_opatch_min_version,output) is None:

                p_message = "CheckMinimumOPatchVersion failed for " + self.oracle_home
                fail_module(p_message)

    # @Description:
    #   Function to check patch conflicts against oracle home
    # @Parameters:
    #   None
    # @Return:
    #   Command output/result
    # @Exception:
    #   Module failure if OPatch version check fails
    #
    def check_conflict_against_oh(self):

        global g_sw_opatch_check_conflict_pattern
        global g_sw_opatch_spacecheck_pattern

        v_oracle_home   = str (self.oracle_home)
        v_sw_stage      = str (self.sw_stage)

        for patch in self.patch_list:

            v_patch_obj = self.patch_list[patch]

            logger("Check conflict for patch: " + v_patch_obj.desc)

            v_patch_dir = v_patch_obj.patch_dir
            v_patch_proactive_bp_id = v_patch_obj.patch_proactive_bp_id
            v_patch_gi_id = v_patch_obj.patch_gi_id
            v_patch_db_id = v_patch_obj.patch_db_id
            v_patch_ocw_id = v_patch_obj.patch_ocw_id
            v_patch_dbwlm_id = v_patch_obj.patch_dbwlm_id
            v_patch_acfs_id = v_patch_obj.patch_acfs_id
            v_patch_id = v_patch_obj.patch_id
            v_is_combo = v_patch_obj.is_combo

            v_command_list = {}

            v_base_path_conflict = v_oracle_home + "/OPatch/opatch prereq CheckConflictAgainstOHWithDetail -phBaseDir " + v_sw_stage + "/" + v_patch_dir
            v_base_path_space = v_oracle_home + "/OPatch/opatch prereq CheckSystemSpace -phBaseDir " + v_sw_stage + "/" + v_patch_dir

            if v_is_combo:
                if v_patch_proactive_bp_id:
                    v_base_path_conflict += "/" + str (v_patch_proactive_bp_id)
                    v_base_path_space += "/" + str (v_patch_proactive_bp_id)
                elif v_patch_gi_id:
                    v_base_path_conflict += "/" + str (v_patch_gi_id)
                    v_base_path_space += "/" + str (v_patch_gi_id)

                if v_patch_db_id:
                    v_command_list["conflict_db"] = v_base_path_conflict + "/" + str (v_patch_db_id)
                    v_command_list["space_db"] = v_base_path_space + "/" + str (v_patch_db_id)

                if v_patch_ocw_id:
                    v_command_list["conflict_ocw"] = v_base_path_conflict + "/" + str (v_patch_ocw_id)
                    v_command_list["space_ocw"] = v_base_path_space + "/" + str (v_patch_ocw_id)

                if v_patch_dbwlm_id:
                    v_command_list["conflict_dbwlm"] = v_base_path_conflict + "/" + str (v_patch_dbwlm_id)
                    v_command_list["space_dbwlm"] = v_base_path_space + "/" + str (v_patch_dbwlm_id)

                if v_patch_acfs_id:
                    v_command_list["conflict_acfs"] = v_base_path_conflict + "/" + str (v_patch_acfs_id)
                    v_command_list["space_acfs"] = v_base_path_space + "/" + str (v_patch_acfs_id)


            for command in v_command_list:

                output = self.run_os_command(v_command_list[command])

                if command[:8] == "conflict" and re.search(g_sw_opatch_check_conflict_pattern,output) is None:

                    p_message = "CheckConflictAgainstOHWithDetail failed for " + self.oracle_home
                    fail_module(p_message)

                elif command[:5] == "space" and re.search(g_sw_opatch_spacecheck_pattern,output) is None:

                    p_message = "CheckSystemSpace failed for " + self.oracle_home
                    fail_module(p_message)

    # @Description:
    #   Function to initiate actual patching process
    # @Parameters:
    #   None
    # @Return:
    #   None
    # @Exception:
    #   None
    #
    def patch_oh(self):

        self.set_env(self.oracle_home)
        
        # start: "if self.is_crs"
        if self.is_crs:

            self.patch_grid_oh()

            v_sleep_time = 10; # seconds
            v_sleep_timeout = 600; # minutes
            v_sleep_time_cnt = 0

            v_command = "$ORACLE_HOME/bin/crsctl check has | grep -v \"is online$\" | wc -l"
            v_stack_label = "CRS"

            if (self.is_cluster):
                v_stack_label = "HAS"
                v_command = "$ORACLE_HOME/bin/crsctl check crs | grep -v \"is online$\" | wc -l"

            while(True):
                
                v_result = self.run_os_command(v_command)
                v_not_online_items = int(v_result)

                if (v_not_online_items == 0):
                    logger(v_stack_label + " is online, continue...")
                    break

                if (v_sleep_time_cnt >= v_sleep_timeout):
                    logger("Timeout: " + v_stack_label + " did not start within given 10 minutes period")
                    fail_module("Error: " + v_stack_label + " start timeout. " + v_stack_label + " did not start within 10 minutes period")

                logger(v_stack_label + " is not online, check again in 10 seconds...")
                time.sleep(v_sleep_time)
                
                v_sleep_time_cnt += v_sleep_time

        else:

            self.patch_db_oh()

    # end: patch_oh

    # @Description:
    #   Function to initiate patching process to DB dictionary
    # @Parameters:
    #   p_ojvm: indicator whether to patch JVM
    # @Return:
    #   None
    # @Exception:
    #   None
    #
    def patch_db(self, p_ojvm = False):

        if self.patch_db_all:

            logger("Patch all databases for ORACLE_HOME: " + self.oracle_home)

        else:

            logger("Patch specific databases for ORACLE_HOME: " + self.oracle_home)

            if not g_instance_list:
                logger("No database found for patching.",True)
            else:

                for item in g_instance_list:
                    logger("database: " + g_instance_list[item].name,True)

        #db_list_to_patch = active_instance_list

        for dbname in g_instance_list:

            v_db_obj = g_instance_list[dbname]

            if not v_db_obj.patch:
                logger("Skip database [" + v_db_obj.name + "/" + v_db_obj.db_unique_name + "].")
                if v_db_obj.is_standby:
                    logger("Database " + v_db_obj.name + " will not be patched because it's a standby database.",True)
                continue

            if v_db_obj.initial_state == "OPEN":

                if v_db_obj.version_short in g_supported_version_new:
                    self.patch_db_12c(v_db_obj, p_ojvm)

                elif v_db_obj.version_short in g_supported_version_old:
                    self.patch_db_pre_12c(v_db_obj, p_ojvm)

            else:

                logger("Database " + v_db_obj.name + " will not be patched because its initial state is " + v_db_obj.initial_state + ".",True)

    # @Description:
    #   Function to perform actual patching of DB dictionary for databases prior 12c version
    # @Parameters:
    #   p_db_obj: database object
    #   p_ojvm: indicator whether to patch JVM
    # @Return:
    #   None
    # @Exception:
    #   None
    #
    def patch_db_pre_12c(self, p_db_obj, p_ojvm):

        #if self.patch_db_id:
        #logger("starting instance: " + p_db_obj.sid)

        if not p_ojvm:

            self.start_instance(p_db_obj)

            command = "export ORACLE_SID=" + p_db_obj.sid + "; " + self.oracle_home + "/bin/sqlplus / as sysdba <<< \"@" + self.oracle_home + "/rdbms/admin/catbundle.sql psu apply\""
            logger("Now applying PSU for database dictionary: \"" + p_db_obj.sid + "\"", True)
            output = self.run_os_command(command)
            logger("Database dictionary \"" + p_db_obj.sid + "\" was patched. Check logfiles for errors.")

        elif p_ojvm and self.patch_list[self.patch_id].patch_ojvm_id:

            self.start_instance(p_db_obj, "upgrade")

            command = "export ORACLE_SID=" + p_db_obj.sid + "; " + self.oracle_home + "/bin/sqlplus / as sysdba <<< \"@" + self.oracle_home + "/sqlpatch/" + str (self.patch_list[self.patch_id].patch_ojvm_id) + "/postinstall.sql\""
            logger("Now applying OJVM for database dictionary: """ + p_db_obj.sid + "", True)
            output = self.run_os_command(command)
            logger("Database dictionary \"" + p_db_obj.sid + "\" was patched. Check logfiles for errors.")

        self.stop_instance(p_db_obj)

    # @Description:
    #   Function to perform actual patching of DB dictionary for 12c version and higher
    # @Parameters:
    #   p_db_obj: database object
    #   p_ojvm: indicator whether to patch JVM
    # @Return:
    #   None
    # @Exception:
    #   None
    #
    def patch_db_12c(self, p_db_obj, p_ojvm):

        if p_ojvm:
            self.start_instance(p_db_obj, "upgrade")
        else:
            self.start_instance(p_db_obj)

        v_command = "export ORACLE_SID=" + p_db_obj.sid + "; $ORACLE_HOME/OPatch/datapatch -verbose"

        logger("Now patching database: \"" + p_db_obj.sid + "\"", p_notime = True)

        v_output = self.run_os_command(v_command)

        logger("Database dictionary \"" + p_db_obj.sid + "\" was patched. Check logfiles for errors.")

        self.stop_instance(p_db_obj)

    # @Description:
    #   Function to perform actual patching of GI home
    # @Parameters:
    #   None
    # @Return:
    #   None
    # @Exception:
    #   Module failure if patching process throws an error
    #
    def patch_grid_oh(self):

        v_sw_stage = str (self.sw_stage)
        global g_ocmrf_file

        for item in self.patch_list:

            v_patch_obj = self.patch_list[item]

            v_patch_proactive_bp_id = str (v_patch_obj.patch_proactive_bp_id)
            v_patch_gi_id = str (v_patch_obj.patch_gi_id)
            v_patch_db_id = str (v_patch_obj.patch_db_id)
            v_patch_dir = v_patch_obj.patch_dir

            if self.oh_version in g_supported_version_new:

                # Initially assume (initialize path to) GI only. Can change below.
                # If it is DBBP only, v_patch_dir == v_patch_proactive_bp_id, therefore does not need to append v_patch_proactive_bp_id
                v_path = self.oracle_home + "/OPatch/opatchauto apply " + v_sw_stage + "/" + v_patch_dir + " -oh " + self.oracle_home

                # COMBO of OJVM + DBBP
                if v_patch_obj.is_dbbp and v_patch_obj.is_combo:
                    v_path = self.oracle_home + "/OPatch/opatchauto apply " + v_sw_stage + "/" + v_patch_dir + "/" + v_patch_proactive_bp_id  + "/" + v_patch_db_id + " -oh " + self.oracle_home

                # COMBO of OJVM + GI
                if not v_patch_obj.is_dbbp and v_patch_obj.is_combo:
                    v_path = self.oracle_home + "/OPatch/opatchauto apply " + v_sw_stage + "/" + v_patch_dir + "/" + v_patch_gi_id + " -oh " + self.oracle_home

            if self.oh_version in g_supported_version_old:

                # COMBO of OJVM + GI
                if v_patch_obj.is_combo:
                    v_path = self.oracle_home + "/OPatch/opatch auto " + v_sw_stage + "/" + v_patch_dir + "/" + v_patch_gi_id + " -oh " + self.oracle_home + " -ocmrf " + g_ocmrf_file

                # GI only, in such case v_patch_dir == v_patch_gi_id
                if not v_patch_obj.is_combo:
                    v_path = self.oracle_home + "/OPatch/opatch auto " + v_sw_stage + "/" + v_patch_dir + " -oh " + self.oracle_home + " -ocmrf " + g_ocmrf_file


            if g_root_password:
                v_command = "su -c \"" + v_path + "\""
                g_expected_list["Password: "] = g_root_password + "\r"
                v_output= self.run_os_command(v_command, p_expect = True)
            else:
                v_command = "sudo " + v_path
                v_output= self.run_os_command(v_command)

            if self.oh_version in g_supported_version_new:
                if re.search(g_sw_opatchauto_check_pattern12, v_output) is not None:
                    g_changed = True
                    return

            if self.oh_version in g_supported_version_old:
                if re.search(g_sw_opatchauto_check_pattern11, v_output) is not None:
                    g_changed = True
                    return

            if re.search(g_sw_opatch_no_need, v_output) is not None:
                return
            else:
                fail_module("Error during applying patch for: " + self.oracle_home)

    # @Description:
    #   Function to perform actual patching of OJVM to oracle home
    # @Parameters:
    #   None
    # @Return:
    #   None
    # @Exception:
    #   Module failure if patching process throws an error
    #
    def patch_oh_ojvm(self):

        global g_ocmrf_file
        v_sw_stage = str (self.sw_stage)
        v_patch_id = str (self.patch_id)

        for item in self.patch_list:

            v_patch_obj = self.patch_list[item]

            v_patch_dir             = v_patch_obj.patch_dir
            v_patch_ojvm_id         = str (v_patch_obj.patch_ojvm_id)

            if (v_patch_obj.patch_ojvm_id):

                v_command = self.oracle_home + "/OPatch/opatch apply -silent " + v_sw_stage + "/" + v_patch_dir + "/" + v_patch_ojvm_id

                if self.oh_version in g_supported_version_old:
                    v_command += " -ocmrf " + g_ocmrf_file
            
                output= self.run_os_command(v_command)

                if re.search(g_sw_opatch_check_pattern1,output) is not None or re.search(g_sw_opatch_check_pattern2,output) is not None:
                    g_changed = True

                elif re.search(g_sw_opatch_no_need,output) is not None:
                    pass

                else:
                    fail_module("Error during applying patch for: " + self.oracle_home)
            else:
                logger("Skip OJVM as the patch could not be identified.")

    # @Description:
    #   Function to perform actual patching of DB oracle home
    # @Parameters:
    #   None
    # @Return:
    #   None
    # @Exception:
    #   Module failure if patching process throws an error
    #
    def patch_db_oh(self):

        v_sw_stage = str (self.sw_stage)
        v_patch_id = str (self.patch_id)

        for item in self.patch_list:

            v_patch_obj = self.patch_list[item]

            v_patch_proactive_bp_id = str (v_patch_obj.patch_proactive_bp_id)
            v_patch_db_id           = str (v_patch_obj.patch_db_id)
            v_patch_gi_id           = str (v_patch_obj.patch_gi_id)
            v_patch_dir             = v_patch_obj.patch_dir

            # Define patch path
            v_command = self.oracle_home+"/OPatch/opatch apply -silent " + v_sw_stage + "/" + v_patch_dir

            #
            # Valid cases:
            #
            #   1. if patch is DBBP only - in this case v_patch_dir == v_patch_proactive_bp_id, therefore only append v_patch_db_id
            #      (v_patch_proactive_bp_id and not v_patch_obj.is_combo)
            #
            #   2. if patch is COMBO of OJVM + DB. Need to be sure it is not COMBO with DBBP or COMBO with GI
            #      (not v_patch_proactive_bp_id and v_patch_obj.is_combo and not v_patch_obj.is_grid)
            #
            #   3. if patch is GI only
            #      (v_patch_obj.is_grid and not v_patch_obj.is_combo)
            #
            if ((v_patch_obj.is_dbbp and not v_patch_obj.is_combo)
                or (not v_patch_obj.is_dbbp and v_patch_obj.is_combo and not v_patch_obj.is_grid)
                or (v_patch_obj.is_grid and not v_patch_obj.is_combo)):
                v_command += "/" + v_patch_db_id

            #
            # Valid cases:
            #
            #   1. If patch is COMBO of OJVM + DBBP
            #
            if v_patch_obj.is_combo and v_patch_obj.is_dbbp:
                v_command += "/" + v_patch_proactive_bp_id + "/" + v_patch_db_id

            # Valid cases:
            #
            #   1. if patch is COMBO of OJVM + GI
            # 
            if v_patch_obj.is_grid and v_patch_obj.is_grid:
                v_command += "/" + v_patch_gi_id + "/" + v_patch_db_id

            if self.oh_version in g_supported_version_old:
                v_command += " -ocmrf " + g_ocmrf_file

            output= self.run_os_command(v_command)

            if re.search(g_sw_opatch_check_pattern1,output) is not None or re.search(g_sw_opatch_check_pattern2,output) is not None:
                g_changed = True

            elif re.search(g_sw_opatch_no_need,output) is not None:
                pass

            else:
                fail_module("Error during applying patch for: " + self.oracle_home)

    # @Description:
    #   Function to stop active services
    #   Only necessary services are stopped from the home that is being patched
    # @Parameters:
    #   None
    # @Return:
    #   None
    # @Exception:
    #   None
    #
    def stop_services_from_oh(self):

        global g_instance_list
        global g_listener_list

        if not g_instance_list and not g_listener_list:
            logger("No instances or listeners found to stop.")
            return

        # Stop active listeners
        for item in g_listener_list:

            self.set_env(item.oracle_home)
            self.stop_listener(item.listener_name)

        # if self.is_crs:
        #     logger("This is CRS configuration, opatchauto takes care.")
        #     logger("Skipping STOP_SERVICES_FROM_OH.")
        #     return

        # Stop active instances from specified OH
        for item in g_instance_list:

            v_db_obj = g_instance_list[item]

            if not v_db_obj.is_asm:

                self.set_env(v_db_obj.oracle_home)
                self.stop_instance(v_db_obj)

        #Stop active ASM instances from specified OH
        for item in g_instance_list:

            v_db_obj = g_instance_list[item]

            if v_db_obj.is_asm:

                self.set_env(v_db_obj.oracle_home)
                self.stop_instance(v_db_obj, p_asm = True)

    # @Description:
    #   Function to start services
    #   Only services that were stopped by this module are started
    # @Parameters:
    #   None
    # @Return:
    #   None
    # @Exception:
    #   None
    #
    def start_services_from_oh(self):

        # if self.is_crs:
        #     logger("This is CRS configuration, opatchauto takes care.")
        #     logger("Skipping START_SERVICES_FROM_OH.")
        #     return

        global g_instance_list
        global g_listener_list

        if not g_instance_list and not g_listener_list:
            logger("No instances or listeners found to start.")
            return

        # Start previously stopped ASM instances
        for item in g_instance_list:

            v_db_obj = g_instance_list[item]

            if v_db_obj.is_asm:

                self.set_env(g_instance_list[item].oracle_home)
                self.start_instance(g_instance_list[item], p_asm = True)

        logger("Now starting: [instance_list]: " + str (g_instance_list))
        # Start previously stopped DB instances
        for item in g_instance_list:

            v_db_obj = g_instance_list[item]
            #logger("Now starting: [db_name]: " + str (v_db_obj.name))
            #logger("Now starting: [initial_state]: " + str (v_db_obj.initial_state))
            #logger("Now starting  [is_asm]: " + str (v_db_obj.is_asm))
            if not v_db_obj.is_asm:

                v_db_obj = g_instance_list[item]
                self.set_env(v_db_obj.oracle_home)

                if v_db_obj.initial_state == "OPEN" or self.is_crs:

                    self.start_instance(v_db_obj, "open")

                elif v_db_obj.initial_state == "MOUNTED":

                    self.start_instance(v_db_obj, "mount")

                else:
                    logger("Database instance " + v_db_obj.sid + " not started. Wrong initial state.")
                    logger("Database instance initial state: " + str (v_db_obj.initial_state))

        # Start previously stopped listeners
        for item in g_listener_list:

            self.set_env(item.oracle_home)
            self.start_listener(item.listener_name)

    # @Description:
    #   Function to identify databases and build database objects
    #   If oracle home is part of CRS database list is build from CRS
    #   otherwise, database list is build from oratab file
    # @Parameters:
    #   None
    # @Return:
    #   None
    # @Exception:
    #   None
    #
    def build_instance_list(self):

        # if self.is_crs:
        #     logger("This is CRS configuration, opatchauto takes care.")
        #     logger("Skip BUILD_INSTANCE_LIST.")
        #     return

        global g_file_oratab
        global g_hostname

        v_oratab_sid_match = {}
        v_oratab_asm_sid_match = {}
        v_oratab_sid_list = {}

        # Build list of DBs defined in oratab
        f = open(g_file_oratab,'r')
        lines_oratab = list(f)

        for line in lines_oratab:

            if not line.startswith('#') and not line.startswith('\n'):

                line_elements = line.split(':')
                v_oratab_sid_list[line_elements[0]] = line_elements[1]

        f.close

        # Build list of DBs from oratab which map to specified OH
        for item in v_oratab_sid_list:

            if v_oratab_sid_list[item] == self.oracle_home:

                if self.is_crs:

                    v_oratab_asm_sid_match[item] = v_oratab_sid_list[item]
                else:

                    v_oratab_sid_match[item] = v_oratab_sid_list[item]

        # If OH is GI
        if self.is_crs:

            # Get 1st key from "v_oratab_asm_sid_match"
            #   - since it's GI, we're assuming only one ASM per GI.
            v_asm_sid = list(v_oratab_asm_sid_match.keys())[0]

            # Check if ASM is running
            v_command = "ps -ef | grep -iw [a]sm_pmon_" + v_asm_sid + " | wc -l"
            output = self.run_os_command(v_command)
            v_is_sid_active = int(output)

            # If ASM instance is running
            if v_is_sid_active:

                # Create DB object for ASM instance
                self.create_db_object(v_asm_sid, self.oracle_home, p_asm = True)

                # Set OH to GI
                self.set_env(self.oracle_home)

                # Get ASM clients
                logger("Registered databases:")
                v_command = "$ORACLE_HOME/bin/crsctl stat res -f -w \"(TYPE = ora.database.type) and (STATE = ONLINE)\" | grep -i \"^NAME=\" | uniq || paste -s -d, -"
                v_result = self.run_os_command(v_command)                

                if v_result:
                    
                    v_crs_registered_dbs = v_result.split(',')

                    for client in v_crs_registered_dbs:
                        v_db_unique_name = client.split('=')[1].split('.')[1]

                        v_command = "$ORACLE_HOME/bin/crsctl stat res -f -w \"(TYPE = ora.database.type) and (NAME = ora." + v_db_unique_name + ".db) and (LAST_SERVER = " + g_hostname + ")\" | grep -i \"^USR_ORA_INST_NAME=\""
                        v_result = self.run_os_command(v_command)

                        if (v_result):
                            v_inst_name = v_result.split('=')[1]
                            logger("Database unique name/Instance name: " + v_db_unique_name + "/" + v_inst_name, p_notime = True)

                            self.create_db_object(p_sid = v_inst_name, p_ora_home = v_oratab_sid_list[v_inst_name], p_db_unique_name = v_db_unique_name)
                            # # If ASM client matches to oratab list
                            # if v_db_name not in v_oratab_sid_match:
                            #     #v_oratab_sid_match[v_inst_name] = v_oratab_sid_list[v_inst_name]
                            #     self.create_db_object(p_sid = v_inst_name, p_ora_home = v_oratab_sid_list[v_inst_name], p_db_name = v_db_name)

                else:
                    logger("No databases found registered in local/cluster registry.")

        else:
            #
            # 1. patch_only OH
            #   -shutdown/start up ONLY active instances

            # 2. patch all DBs
            #   -shutdown/start up all active and inactive instances

            # 3. patch specific DBs
            #   -shutdown/start up only specific instances

            for sid in v_oratab_sid_match:

                v_command = "ps -ef | grep -iw [o]ra_pmon_" + sid + " | wc -l"

                v_output = self.run_os_command(v_command)
                v_is_sid_active = int(v_output)

                if v_is_sid_active == 1:

                    self.create_db_object(sid,v_oratab_sid_match[sid])

    # @Description:
    #   Function to create database object
    # @Parameters:
    #   None
    # @Return:
    #   None
    # @Exception:
    #   None
    #
    def create_db_object(self, p_sid
                        , p_ora_home
                        , p_asm = False
                        , p_db_unique_name = None):

        global g_instance_list

        self.set_env(self.oracle_home)

        v_patch = False

        if not p_asm:

            # if patching GI home we only to stop running databases
            # no metadata is needed for databases
            if self.is_crs:

                v_db_initial_state = None
                v_db_name = None
                v_db_version = None
                v_db_is_standby = None
                v_db_is_rac = None
                v_db_inst_list = None
                v_db_hostname = None
                v_crs_registered = True
                v_db_unique_name = p_db_unique_name

            else:

                # get db name
                v_command = "export ORACLE_SID=""" + p_sid + "; $ORACLE_HOME/bin/sqlplus -s / as sysdba @/tmp/orapatch_scripts/get_db_metadata"
                v_db_metadata = self.run_os_command(v_command).split(';')
                logger("Database metadata: " + str (v_db_metadata))
                # remove index 0 - used to catch output from gloging.sql
                v_db_metadata.pop(0)
                v_db_name = v_db_metadata[0]

                v_db_version = self.oh_version
                v_db_hostname = g_hostname
                v_db_inst_list = None # not used
                v_db_unique_name = v_db_metadata[6]

                v_argument_append = "-db"
                if self.oh_version in g_supported_version_old:
                    v_argument_append = "-d"

                v_command = "$ORACLE_HOME/bin/srvctl status database " + v_argument_append + " " + v_db_unique_name + " | grep -Ei \"Database is (not ){0,1}running\" | wc -l"
                v_output = self.run_os_command(v_command)

                if int(v_output) == 0:
                    # Get database metadata from sql
                    v_db_is_standby = False
                    if v_db_metadata[2] == 'PHYSICAL STANDBY':
                        v_db_is_standby = True
                    v_db_is_rac = gf_to_bool(v_db_metadata[3])
                    #if v_db_is_rac:
                    #    v_db_inst_list = v_db_metadata[4].split(',')
                    #else:
                    #    v_db_inst_list = v_db_metadata[4]
                    v_db_initial_state = v_db_metadata[5]
                    v_crs_registered = False

                elif int(v_output) == 1:
                    v_crs_registered = True

                    # Get database metadata details from CRS
                    if self.oh_version in g_supported_version_old:

                        v_command = "$ORACLE_HOME/bin/srvctl config database -d " + v_db_unique_name + " -a | grep -i \"^Database role:\""
                        v_output = self.run_os_command(v_command).split(':')[1].strip()
                        v_db_is_standby = False
                        if v_output and v_output.upper() == "PHYSICAL STANDBY":
                            v_db_is_standby = True

                        v_command = "$ORACLE_HOME/bin/srvctl config database -d " + v_db_unique_name + " -a | grep -i \"^Type:\""
                        v_output = self.run_os_command(v_command)
                        v_db_is_rac = False

                        if v_output:
                            if v_output.split(':')[1].upper() == "RAC":
                                v_db_is_rac = True

                        v_command = "$ORACLE_HOME/bin/srvctl config database -d " + v_db_unique_name + " -a | grep -i \"^Start options:\""
                        v_output = self.run_os_command(v_command).split(':')[1].strip()
                        v_db_initial_state = "OPEN"
                        if v_output and v_output.upper() != "OPEN":
                            v_db_initial_state = v_output

                    elif self.oh_version in g_supported_version_new:

                        v_command = "$ORACLE_HOME/bin/srvctl config database -db " + v_db_unique_name + " -all | grep -i \"^Database role:\""
                        v_output = self.run_os_command(v_command).split(':')[1].strip()
                        v_db_is_standby = False
                        if v_output and v_output.upper() == "PHYSICAL STANDBY":
                            v_db_is_standby = True

                        v_command = "$ORACLE_HOME/bin/srvctl config database -db " + v_db_unique_name + " -all | grep -i \"^Type:\""
                        v_output = self.run_os_command(v_command)
                        v_db_is_rac = False

                        if v_output:
                            if v_output.split(':')[1].strip().upper() == "RAC":
                                v_db_is_rac = True

                        v_command = "$ORACLE_HOME/bin/srvctl config database -db " + v_db_unique_name + " -all | grep -i \"^Start options:\""
                        v_output = self.run_os_command(v_command).split(':')[1].strip()
                        v_db_initial_state = "OPEN"
                        if v_output and v_output.upper() != "OPEN":
                            v_db_initial_state = v_output
                else:
                    fail_module("Failed in determing whether database is registered in CRS.")


                # Report which databases will be patched only if flag to patch only OH is set to False
                if not self.patch_only_oh:
                    if self.patch_db_all:
                        v_patch = True
                    elif self.patch_db_list:
                        logger("db_unique_name list: " + str(self.patch_db_list))
                        logger("Checking whether database ["+v_db_unique_name+"] exists in the user-defined list of databases.")
                        if v_db_unique_name in self.patch_db_list:
                            if v_db_is_standby:
                                logger("Instance ["+v_db_unique_name+"] is found in the specified list, but it won't be patched because it's a standby.")
                            else:
                                v_patch = True
                                logger("Instance ["+v_db_unique_name+"] is found in the specified list, will be patched.")
                        else:
                            logger("Instance ["+v_db_unique_name+"] is not in the specified list.")
                else:
                    v_patch = False

            logger("==========================", p_notime = True)
            logger("Database details:", p_notime = True)
            logger("Database name: " + str(v_db_name), p_notime = True)
            logger("Database unique name: " + str(v_db_unique_name), p_notime = True)
            logger("Database version: " + str(v_db_version), p_notime = True)
            logger("Database hostname: " + str(v_db_hostname), p_notime = True)
            logger("Database standby role: " + str(v_db_is_standby), p_notime = True)
            logger("Database RAC: " + str(v_db_is_rac), p_notime = True)
            logger("Database initial state: " + str(v_db_initial_state), p_notime = True)
            logger("Database will be patched: " + str(v_patch), p_notime = True)

        else:

            v_db_name = None # not used in case of GI
            v_db_unique_name = None
            v_db_version = self.oh_version
            v_db_hostname = g_hostname
            v_db_inst_list = None # # not used in case of GI
            v_db_is_standby = None # not used in case of GI
            v_db_is_rac = None # not used in case of GI
            v_db_initial_state = None # not used in case of GI
            v_crs_registered = True

        #end: if not p_asm

        db_obj = DatabaseFactory(p_sid, v_db_version, v_db_name, p_asm, v_db_is_rac
                                ,v_db_is_standby, v_db_inst_list, False
                                ,v_db_initial_state, p_ora_home, v_db_hostname
                                ,v_crs_registered, v_patch, v_db_unique_name)

        if (g_function == "PATCH_DB" or g_function == "PATCH_DB_OJVM") and not db_obj.patch:
            logger("Database [" + db_obj.db_unique_name + "] won't be patched.")
            return

        g_instance_list[p_sid] = db_obj

        #if is_down:
        #    self.stop_instance(p_sid)

        #logger ("db_name: " + db_obj.name)
        #logger ("db_version: " + db_obj.version)
        #logger ("is_standby: " + str (db_obj.is_standby))
        #logger ("is_rac: " + str (db_obj.is_rac))
        #logger ("inst_list: " + db_obj.instance_list)
        #logger ("is_active: " + str (db_obj.is_active))

    # @Description:
    #   Function to build listener list depended on oracle home being patched
    # @Parameters:
    #   p_oracle_home: oracle home being patched
    # @Return:
    #   None
    # @Exception:
    #   None
    #
    def build_listener_list(self, p_oracle_home):

        # There might be unregistered listeners.
        if self.is_crs:
           logger("This is CRS configuration, opatchauto takes care.")
           logger("Skipping BUILD_LISTENER_LIST.")
           return

        global g_listener_list

        # the shell command
        v_command = "ps -eo args | grep tns | grep -iw " + p_oracle_home + " | grep -v grep | cut -d' ' -f2"

        #Launch the shell command:
        v_output = self.run_os_command(v_command)

        for listener in v_output.splitlines():
            v_listener_obj = ListenerFactory(listener.strip(), p_oracle_home)
            g_listener_list[v_listener_obj] = v_listener_obj

        #logger("manage: " + str (g_listener_list))

    # @Description:
    #   Function to stop an instance
    # @Parameters:
    #   p_db_obj: database object
    #   p_mode: what mode to use for shutdown operation
    #   p_asm: indicator whether it's an ASM instance
    # @Return:
    #   Output of shutdown operation
    # @Exception:
    #   None
    #
    def stop_instance(self, p_db_obj, p_mode = "immediate", p_asm = False):

        if p_asm:

            logger("Skip ASM stop as opatchauto takes care")

            # if self.oh_version in g_supported_version_new:

            #     v_argument_append = ""

            #     if self.is_cluster:
            #         v_argument_append = "-node " + p_db_obj.hostname

            #     v_command = "$ORACLE_HOME/bin/srvctl stop asm -force -stopoption " + p_mode + " " + v_argument_append

            # elif self.oh_version in g_supported_version_old:

            #     v_argument_append = ""

            #     if self.is_cluster:
            #         v_argument_append = "-n " + p_db_obj.hostname

            #     v_command = "$ORACLE_HOME/bin/srvctl stop asm -f -o " + p_mode + " " + v_argument_append

        else:

            if self.oh_version in g_supported_version_new:

                if p_db_obj.is_rac:
                    v_command = "$ORACLE_HOME/bin/srvctl stop instance -db " + p_db_obj.db_unique_name + " -stopoption " + p_mode + " -instance " + p_db_obj.sid
                elif p_db_obj.crs_registered:
                    v_command = "$ORACLE_HOME/bin/srvctl stop database -db " + p_db_obj.db_unique_name + " -stopoption " + p_mode
                else:
                    v_command = "export ORACLE_SID=" + p_db_obj.sid + "; $ORACLE_HOME/bin/sqlplus -s / as sysdba <<< \"shutdown " + p_mode + "\""

            elif self.oh_version in g_supported_version_old:

                if p_db_obj.is_rac:
                    v_command = "$ORACLE_HOME/bin/srvctl stop instance -d " + p_db_obj.db_unique_name + " -o " + p_mode + " -i " + p_db_obj.sid
                elif p_db_obj.crs_registered:
                    v_command = "$ORACLE_HOME/bin/srvctl stop database -d " + p_db_obj.db_unique_name + " -o " + p_mode
                else:
                    v_command = "export ORACLE_SID=" + p_db_obj.sid + "; $ORACLE_HOME/bin/sqlplus -s / as sysdba <<< \"shutdown " + p_mode + "\""

            logger("Stop instance: " + p_db_obj.sid)

            return self.run_os_command(v_command)

    # @Description:
    #   Function to stop a listener
    # @Parameters:
    #   p_listener: listener to be stopped
    # @Return:
    #   Output of listener stop operation
    # @Exception:
    #   None
    #
    def stop_listener(self, p_listener):

        v_command = "$ORACLE_HOME/bin/lsnrctl stop " + p_listener

        logger("Stopping listener: " + p_listener)

        return self.run_os_command(v_command)

    # @Description:
    #   Function to start an instance
    # @Parameters:
    #   p_db_obj: database object
    #   p_mode: mode used for startup operation
    #   p_asm: indicator whether the instance is an ASM instance
    # @Return:
    #   Output of startup operation
    # @Exception:
    #   None
    #
    def start_instance(self, p_db_obj, p_mode = "open", p_asm = False):

        if p_asm:

            logger("Skip ASM start as opatchauto takes care")
            # v_argument_append = ""

            # if self.is_cluster:

            #     if self.oh_version in g_supported_version_new:

            #         v_argument_append = "-node " + p_db_obj.hostname

            #     elif self.oh_version in g_supported_version_old:

            #         v_argument_append = "-n " + p_db_obj.hostname

            # v_command = "$ORACLE_HOME/bin/srvctl start asm " + v_argument_append

        else:

            if self.oh_version in g_supported_version_new:

                if p_db_obj.is_rac and p_mode != "upgrade":
                    v_command = "$ORACLE_HOME/bin/srvctl start instance -db " + p_db_obj.db_unique_name + " -instance " + p_db_obj.sid
                elif p_db_obj.crs_registered and p_mode != "upgrade":
                    v_command = "$ORACLE_HOME/bin/srvctl start database -db " + p_db_obj.db_unique_name
                else:
                    v_command = "export ORACLE_SID=" + p_db_obj.sid + "; $ORACLE_HOME/bin/sqlplus -s / as sysdba <<< \"startup " + p_mode + "\""

            elif self.oh_version in g_supported_version_old:

                if p_db_obj.is_rac and p_mode != "upgrade":
                    v_command = "$ORACLE_HOME/bin/srvctl start instance -d " + p_db_obj.db_unique_name + " -i " + p_db_obj.sid
                elif p_db_obj.crs_registered and p_mode != "upgrade":
                    v_command = "$ORACLE_HOME/bin/srvctl start database -d " + p_db_obj.db_unique_name
                else:
                    v_command = "export ORACLE_SID=" + p_db_obj.sid + "; $ORACLE_HOME/bin/sqlplus -s / as sysdba <<< \"startup " + p_mode + "\""

            logger("Starting instance: " + p_db_obj.sid)

            return self.run_os_command(v_command)

    # @Description:
    #   Function to start listener
    # @Parameters:
    #   p_listener: listener to be started
    # @Return:
    #   Output of startup operation
    # @Exception:
    #   None
    #
    def start_listener(self, p_listener):

        v_command = "$ORACLE_HOME/bin/lsnrctl start " + p_listener

        logger("Starting listener: " + p_listener)

        return self.run_os_command(v_command)

    # @Description:
    #   Function to start listener
    # @Parameters:
    #   p_listener: listener to be started
    # @Return:
    #   Output of startup operation
    # @Exception:
    #   None
    #
    def check_running_services_from_oh(self):

        if self.is_crs:
            logger("This is CRS configuration, opatchauto takes care.")
            logger("Skip CHECK_RUNNING_SERVICES_FROM_OH.")
            return

        global g_instance_list

        v_fail = False

        if not self.is_crs:
            # Check running processes from OH
            v_command = "ps -ef | grep -iw " + self.oracle_home + " | grep -v grep | wc -l"
            #Launch the shell command:
            v_output = self.run_os_command(v_command)

            v_output = int(v_output)

            if v_output > 0:

                v_fail = True

        for item in g_instance_list:

            v_db_obj = g_instance_list[item]

            if v_db_obj.initial_state != "DOWN":

                v_inst_argument = "ora_pmon"

                if v_db_obj.is_asm:
                    v_inst_argument = "asm_pmon"

                v_command = "ps -ef | grep -iw " + v_inst_argument + "_" + v_db_obj.sid + " | grep -v grep | wc -l"

                #Launch the shell command:
                v_output = self.run_os_command(v_command)

                v_output = int(v_output)

                if v_output > 0:

                    v_fail = True

        #if not found_home_oratab:
            #module.fail_json(rc=256, msg="Oracle home " + self.oracle_home+" was not found in " + g_file_oratab)
        #    p_message = "Oracle home " + self.oracle_home+" was not found in " + g_file_oratab
        #    fail_module(p_message)
        if v_fail:
            #module.fail_json(rc=256, msg="There are active services under " + self.oracle_home)
            p_message = "There are running processes under " + self.oracle_home

            fail_module(p_message)

    def check_patch_exist(self):

        global g_patch_applied
        logger("Checking if patch " + str (self.patch_id) + " is already applied.")
        v_command = self.oracle_home + "/OPatch/opatch lspatches -id " + str (self.patch_id)
        v_output = self.run_os_command(v_command)

        if re.search(g_sw_opatch_check_patch_nonexist,v_output) is not None:
            logger("Patch " + self.patch_id + " is not installed.")
            # Patch is not installed
        if re.search(g_sw_opatch_check_patch_exist,v_output) is not None:
            g_patch_applied = True
            logger("Patch " + self.patch_id + " is already installed.")
        else:
            fail_module("Unknown error for patch existence check.")


    def check_cluster_patch_db_dict(self):

        global g_patch_db_dict
        global g_check_cluster_state

        g_patch_db_dict = True

        logger("Checking if cluster is in NORMAL upgrade state.")
        v_command = "if [ -f /etc/oracle/olr.loc ]; then cat /etc/oracle/olr.loc | grep 'crs_home=' | awk '{split($0,list,\"=\"); print list[2]}'; fi"
        v_gi_home= self.run_os_command(v_command)

        logger("CRS_HOME: " + v_gi_home)

        if len (v_gi_home) > 0:

            g_patch_db_dict = False
            v_command = "su -c \"" + v_gi_home + "/bin/crsctl query crs activeversion -f\""
            g_expected_list["Password: "] = g_root_password + "\r"
            v_output= self.run_os_command(v_command, p_expect = True)

            if re.search(g_check_cluster_state,v_output):
                g_patch_db_dict = True
            else:
                logger("Cluster state is: " + v_output)
                logger("Database dictionary won't be patched.")

    def patchprocess_pre_patch(self):

        logger("==============================================",True)
        logger(g_function + " => BUILD_INSTANCE_LIST",True)
        logger("==============================================",True)
        self.build_instance_list()

        if g_function != "PATCH_DB" and g_function != "PATCH_DB_OJVM":
            logger("==============================================",True)
            logger(g_function + " => BUILD_LISTENER_LIST",True)
            logger("==============================================",True)
            self.build_listener_list(self.oracle_home)

        logger("==============================================",True)
        logger(g_function + " => STOP_SERVICES_FROM_OH",True)
        logger("==============================================",True)
        self.stop_services_from_oh()

        if g_function != "PATCH_DB" and g_function != "PATCH_DB_OJVM":
            logger("==============================================",True)
            logger(g_function + " => CHECK_RUNNING_SERVICES_FROM_OH",True)
            logger("==============================================",True)
            self.check_running_services_from_oh()


    def patchprocess_post_patch(self):

        logger("==============================================",True)
        logger(g_function + " => START_SERVICES_FROM_OH",True)
        logger("==============================================",True)
        self.start_services_from_oh()


    def patchprocess_main(self):

        # Build list of patches which will be applied
        self.build_patch_dict()

        v_patch_obj = self.patch_list[self.patch_id]

        if not pexpect_found:
            fail_module("Required \"pexpect\" (RPM) library not found")

        if g_function == "CHECK_OPATCH_MIN_VERSION":

            logger("==============================================",True)
            logger("FUNC => CHECK_OPATCH_MIN_VERSION",True)
            logger("==============================================",True)
            self.check_opatch_min_version()

        elif g_function == "CHECK_CONFLICT_AGAINST_OH":

            logger("==============================================",True)
            logger("FUNC => CHECK_CONFLICT_AGAINST_OH",True)
            logger("==============================================",True)
            self.check_conflict_against_oh()
            g_changed = False

        elif g_function == "PATCH_OH" and not self.only_prereq:

            #logger("==============================================",True)
            #logger(g_function + " => CHECK_PATCH_EXISTENCE",True)
            #logger("==============================================",True)
            #self.check_patch_exist()

            #if not g_patch_applied:

            self.patchprocess_pre_patch()

            logger("==============================================",True)
            logger("FUNC => PATCH_OH",True)
            logger("==============================================",True)
            self.patch_oh()

            self.patchprocess_post_patch()

        elif g_function == "PATCH_DB" and not self.patch_only_oh and not v_patch_obj.only_oh and not self.is_crs:

            if self.is_cluster:
                self.check_cluster_patch_db_dict()
                if not g_patch_db_dict:
                    return

            self.patchprocess_pre_patch()

            logger("==============================================",True)
            logger("FUNC => PATCH_DB",True)
            logger("==============================================",True)
            self.patch_db()

            self.patchprocess_post_patch()

        elif g_function == "PATCH_OH_OJVM" and not self.patch_only_oh and not v_patch_obj.only_oh and not self.is_crs:

            if (v_patch_obj.patch_ojvm_id):

                self.patchprocess_pre_patch()

                logger("==============================================",True)
                logger("FUNC => PATCH_OH_OJVM",True)
                logger("==============================================",True)
                self.patch_oh_ojvm()

                self.patchprocess_post_patch()

            else:
                logger("Skip OJVM.")
                logger("OJVM patch number not defined in patch metadata file.")

        elif g_function == "PATCH_DB_OJVM" and not self.patch_only_oh and not v_patch_obj.only_oh and not self.is_crs:

            if (v_patch_obj.patch_ojvm_id):
            
                if self.is_cluster:
                    self.check_cluster_patch_db_dict()
                    if not g_patch_db_dict:
                        return

                self.patchprocess_pre_patch()

                logger("==============================================",True)
                logger("FUNC => PATCH_DB_OJVM",True)
                logger("==============================================",True)
                self.patch_db(p_ojvm = True)

                self.patchprocess_post_patch()

            else:
                logger("Skip OJVM.")
                logger("OJVM patch number not defined in patch metadata file.")

def main():

    try:

        global module
        global g_function
        global g_logger_file
        global g_root_password
        global g_file_oratab
        global g_debug
        global g_hostname

        module = AnsibleModule(
            argument_spec = dict(
                oracle_home         = dict(required = True,  type = 'path'),
                swlib_path          = dict(required = True,  type = 'path'),
                patch_id            = dict(required = True,  type = 'int'),
                only_prereq         = dict(required = True,  type = 'bool'),
                patch_only_oh       = dict(required = False, type = 'bool'),
                patch_ojvm          = dict(required = False, type = 'bool'),
                patch_db_all        = dict(required = False, type = 'bool'),
                patch_db_list       = dict(required = False, type = 'str'),
                patch_item          = dict(required = True,  type = 'dict'),
                function            = dict(required = True,  type = 'str'),
                orapatch_logfile    = dict(required = True,  type = 'str'),
                root_password       = dict(required = True,  type = 'str'),
                oratab_file         = dict(required = False,  type = 'str'),
                debug               = dict(required = False, type = 'bool'),
                ansible_hostname    = dict(required = False, type = 'str'),
            )
        )

        # Define arguments passed from ansible playbook.
        p_oracle_home   = module.params['oracle_home']
        p_sw_stage      = module.params['swlib_path']
        p_patch_id      = module.params['patch_id']
        p_only_prereq   = module.params['only_prereq']
        p_patch_only_oh = module.params['patch_only_oh']
        p_patch_ojvm    = module.params['patch_ojvm']
        p_patch_db_all  = module.params['patch_db_all']
        p_patch_db_list = module.params['patch_db_list']
        p_patch_item    = module.params['patch_item']
        g_logger_file   = module.params['orapatch_logfile']
        g_function      = module.params['function'].upper()
        g_root_password = module.params['root_password']
        g_file_oratab   = module.params['oratab_file']
        g_hostname      = module.params['ansible_hostname']

        if "debug" in module.params:
            g_debug = module.params['debug']

        if g_function != "START_LOGGER_SESSION" and g_function != "END_LOGGER_SESSION":

            if g_debug:
                logger("Debug is enabled for: [" + str (p_oracle_home) + "].")
            else:
                logger("Debug is not enabled for: [" + str (p_oracle_home) + "].")

        if g_function == "START_LOGGER_SESSION":

            gf_start_logger_session()

            if g_debug:
                logger("Global debug is enabled.")
            else:
                logger("Global debug is not enabled.")

        elif g_function == "END_LOGGER_SESSION":

            gf_end_logger_session()

        else:

            patchprocess = PatchProcess(p_oracle_home, p_only_prereq
                                        ,p_patch_id, p_sw_stage
                                        ,p_patch_only_oh, p_patch_ojvm
                                        ,p_patch_db_all, p_patch_db_list
                                        ,p_patch_item)

            patchprocess.patchprocess_main()

        module.exit_json(changed = g_changed, msg = "Finished.")

    except Exception as e:
        logger(str(e))
        logger(e.__class__.__name__)
        fail_module(traceback.format_exc())

if __name__ == '__main__':

    main()
