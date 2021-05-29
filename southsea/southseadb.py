import sys
import os
import argos
from argos.main import main, printInspectors


def run_app():
    # argos.info.TESTING = False
    # argos.info.DEBUGGING = False

    this_dir = os.path.dirname(os.path.realpath(__file__))
    log_file = os.path.realpath(os.path.join(this_dir, 'log.json'))
    settings_file = os.path.realpath(os.path.join(this_dir, 'settings.json'))

    # for debug
    nc_file_name = 'ww3.199101_hs.nc'
    parent_dir = os.path.realpath(os.path.join(this_dir, '..'))
    nc_file = os.path.realpath(os.path.join(parent_dir, nc_file_name))
    #
    args = [
        # "-d",  # debugging mode
        "--config-file",
        settings_file,
        "--open",
        nc_file,
        "--select",
        "/" + nc_file_name + "/hs",
        "--inspector",
        "Image",
        "--log-config",
        log_file,
        "--log-level",
        "debug"
    ]
    old_sys_argv = sys.argv
    sys.argv = [old_sys_argv[0]] + args

    #
    main()
