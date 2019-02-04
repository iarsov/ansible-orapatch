# ansible-orapatch
Automation for Oracle software binaries patching

# Synopsis

Author: Ivica Arsov<br/>
Contact: https://blog.iarsov.com/contact

Last module version: 1.4.0<br/>
Last update: 01.02.2019

The main purpose of the module is to automate the patching process of Oracle database and grid infrastructure binaries with PSUs, BPs, RUs patches released by Oracle.<br/>
<br/>
One-off patches: It won't work with one-off patches as it's not designed for that. Though, it that can be extended to support one-off patches.<br/>
<br/>
The module will use opatchauto if the Oracle home being patched is grid infrastructure, otherwise it will use standard opatch steps.<br/>
<br/>
The patching is customizable via role's variables definition. For example, you can run just prerequisites without applying patch or patch binaries without database dictionary changes or skip the OJVM patch etc.<br/>
<br/>
The module supports 11g, 12c and 18c database versions. It should work properly on 10g as well, but I haven't tested it.<br/>
<br/>
Expected actions performed by the module:<br/>
<br/>
    The module will identify what database instances, listeners and ASM instances are running.<br/>
    The module will shutdown all listeners and database instances, only if the home from which services are running is being patched.<br/>
    The module will start up all previously stopped services after it completes with patching*<br/>
    The module will skip databases which are not in READ WRITE state**<br/>
    The module will identify if a given database is in STANDBY or PRIMARY role***<br/>
    The module always patches GI homes with opatchauto<br/>
    The module always patches DB homes with opatch<br/>
    The module will make multiple restarts of the databases and listeners during the process<br/>
<br/>
* Assuming no error occurred and module did not fail during the patching process.<br/>
** Even if the databases are specified for patching<br/>
*** Databases in STANDBY role are not patched<br/>
<br/>
<br/>
Note: If an error is encountered and you restart the process, the module will not automatically start previously stopped services. The module will note stopped services at the beginning of the process and it will leave the services stopped at the end of execution. Due to the nature of how Oracle patching is performed, in some cases if something breaks a manual intervention might be needed. In other words if you restart the Ansible process do not expect to continue from where it stopped.<br/>
<br/>
Opatch has support for "resume" functionality. That's something I can take a look to implement into the module. As of now there is no such option.<br/>
<br/>

# Step-by-step guide

1. Define the individual hosts or group of hosts in "inventory/hosts" under group [database]

2. Define the location where patch binaries are extracted with "swlib_path" variable in "roles/common/defaults/main.yml"<br/>
   The "swlib_path" location needs to be accessible from the target machine.

3. Define the list of oracle homes to be patched in "roles/orapatch/vars/main.yml"<br/>
   For list's variable specification see (below) the "*Oracle home list definition format*" section.
   <br/><br/>
   3a. Executing the playbook against group of hosts with different oracle home structures<br/><br/>
   The list of oracle homes defined in "roles/orapatch/vars/main.yml" is always executed against all hosts defined in the host group. If different targets have different oracle home structure, you can use the "host" variable which can be set for each oracle entry in the list to map the entry to a specific target. With such configuration when the "host" variable is set to a specific target, the entry will be "skipped" for all targets except the matching target.

4. Check if the patch you want to install is defined in "roles/orapatch/vars/patch_dictionary/patch_dict.yml" file.<br/>
   If the patch is not defined, see "*Patch metadata format*: on how to define patch metadata.

5. Specify the user which is used to authenticate against target machine in "orapatch.yml" playbook file.

6. Run the playbook: <br/>
   ansible-playbook orapatch.yml -k

   Note: The "-k" option will prompt you to enter the SSH password.<br/>
         If you're using SSH keys then "-k" option can be omitted.

# Logging

During the whole process, all steps and output are logged in a log file on the target machines.<br/>
Currently, there are two logging modes, standard (default) and debug. You switch between the modes with True/False value for the debug variable. In debug mode, more descriptive output is written in the log file.<br/>
As an example, if you run OJVM patching with debug mode for 11g you would see whole output of the post install SQL script that's executed.<br/>
<br/>
At the end of the patching the log file is copied over to the control machine from where the patching started. So, if you patch multiple nodes you will get all log files.<br/>
<br/>
The module by default will prompt for the user to provide root password. It is necessary for opatchauto and it is only applicable when grid infrastructure software is being patched.<br/>

# Real Application Clusters

The module supports Real Application Clusters (RAC). All you need to do is specify group of hosts.<br/>
There is one tricky moment with clusters. When a node patching is complete, when the CRS is started, the operation is asynchronous, meaning the module will get OK state when it executes crsctl start crs command. At that point from module perspective CRS is up and running. That's why I have implemented a check on every 10 seconds with a timeout of 10 minutes where the CRS is checked if all services are online prior to continue to patch other nodes.

# Patch metadata format:

Prior usage, the patches metadata needs to be specified in "vars/patch_dictionary/patch_dict.yml"

```
25437795: -> patch_id (it's in the name of the file you download from Oracle)
  patch_proactive_bp_id -> patch proactive bundle patch id (if it's bundle patch)
  patch_gi_id: -> Applicable for COMBO (GI) only. GI patch ID. If it's GI only or COMBO DBBP, it is ignored
  patch_db_id -> DB patch ID
  patch_ocw_id -> OCW patch ID (applicable if the patch is COMBO patch)
  patch_ojvm_id -> OJVM patch ID
  patch_acfs_id: -> ACFS patch ID
  patch_dbwlm_id: -> DBWLM path ID
  patch_dir -> patch directory (directory where patch file is extracted)
  file -> patch file name (not used currently)
  only_oh -> whether the patch is for OH binaries only
  desc -> patch description (usually should contain the patch name)
```

# Oracle home list definition format:

Oracle homes and databases which need to be patched can be specified as a list in "vars/main.yml" file.

```
#
# List of oracle homes and databases to patch.
#
ora_home_list:
  - oracle_owner: -> OS owner of the oracle binaries
    oracle_home_path: -> OH OS path
    oratab_file: -> Absolute path for oratab file. This can be ignored if the global value is set.
    run_only_checks: -> Indicator whether to run onl prereq checks against OH
    patch_id: -> Patch ID of the patch which is to be applied. This module needs to find a match in "vars/patch_dictionary/patch_dict.yml"
    patch_only_oh: -> Indicator whether to patch only OH without the databases (True/False)
    patch_ojvm: -> Indicator whether to apply OJVM patch (applicable if the patch is COMBO) (True/False)
    patch_db_all: -> Indicator whether to apply the patch on all databases after patching the OH ("patch_only_oh" has precedence over "patch_db_all") (True/False)
    patch_db_list: "" -> Comma separated list (in quotes!) of specific databases to patch ("patch_db_all" has precedence over "patch_db_list")
    host: -> It allows the user to specify a mapping to specific host for which this list entry is valid. It's applicable only if the playbook is executed against group of hosts
    backup_oh: -> Indicator whether to backup oracle home binaries (True/False)
    skip: -> Main indicator whether to skip this item or not
    debug: -> Enables debug mode (True/False)
```

# Example run:

```
ansible-playbook orapatch.yml -k
```

# License

See LICENSE.md file.