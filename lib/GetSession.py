#!/usr/bin/env python
# Corey Brune - Oct 2016
#This class handles the config file and authentication to a VE
#requirements
#pip install docopt delphixpy

"""This module takes the conf file for VE(s) and returns an authentication
   object
"""

import json

from delphixpy.v1_6_0.delphix_engine import DelphixEngine
from delphixpy.v1_6_0.exceptions import RequestError
from delphixpy.v1_6_0.exceptions import JobError
from delphixpy.v1_6_0.exceptions import HttpError
from delphixpy.v1_6_0 import job_context
from delphixpy.v1_6_0.web import job

from lib.DlpxException import DlpxException
from lib.DxLogging import print_debug


VERSION = 'v.0.2.000'


class GetSession(object):
    """
    Class to get the configuration and returns an Delphix authentication
    object
    """

    def __init__(self):
        self.server_session = None
        self.dlpx_engines = {}
        self.jobs = {}


    def get_config(self, config_file_path='./dxtools.conf'):
        """
        This method reads in the dxtools.conf file

        config_file_path: path to the configuration file.
                          Default: ./dxtools.conf
        """

        config_file_path = config_file_path

        #First test to see that the file is there and we can open it
        try:
            config_file = open(config_file_path).read()

            #Now parse the file contents as json and turn them into a
            #python dictionary, throw an error if it isn't proper json
            config = json.loads(config_file)

        except IOError:
            raise DlpxException('\nERROR: Was unable to open %s  Please '
                                'check the path and permissions, and try '
                                'again.\n' %
                                (config_file_path))

        except (ValueError, TypeError) as e:
            raise DlpxException('\nERROR: Was unable to read %s as json. '
                                'Please check if the file is in a json format'
                                ' and try again.\n %s' %
                                (config_file, e))

        #Create a dictionary of engines (removing the data node from the
        # dxtools.json, for easier parsing)
        for each in config['data']:
            self.dlpx_engines[each['hostname']] = each


    def serversess(self, f_engine_address, f_engine_username,
                   f_engine_password, f_engine_namespace='DOMAIN'):
        """
        Method to setup the session with the Virtualization Engine

        f_engine_address: The Virtualization Engine's address (IP/DNS Name)
        f_engine_username: Username to authenticate
        f_engine_password: User's password
        f_engine_namespace: Namespace to use for this session. Default: DOMAIN
        """

        try:
            if f_engine_password:
                self.server_session = DelphixEngine(f_engine_address,
                                                    f_engine_username,
                                                    f_engine_password,
                                                    f_engine_namespace)
            elif f_engine_password is None:
                self.server_session = DelphixEngine(f_engine_address,
                                                    f_engine_username,
                                                    None, f_engine_namespace)

        except (HttpError, RequestError, JobError) as e:
            raise DlpxException('ERROR: An error occurred while authenticating'
                                ' to %s:\n %s\n' % (f_engine_address, e))


    def job_mode(self, single_thread=True):
        """
        This method tells Delphix how to execute jobs, based on the
        single_thread variable

        single_thread: Execute application synchronously (True) or
                       async (False)
                       Default: True
        """

        #Synchronously (one at a time)
        if single_thread is True:
            print_debug("These jobs will be executed synchronously")
            return job_context.sync(self.server_session)

        #Or asynchronously
        elif single_thread is False:
            print_debug("These jobs will be executed asynchronously")
            return job_context.async(self.server_session)


    def job_wait(self):
        """
        This job stops all work in the thread/process until jobs are completed.

        No arguments
        """
        #Grab all the jos on the server (the last 25, be default)
        all_jobs = job.get_all(self.server_session)

        #For each job in the list, check to see if it is running (not ended)
        for jobobj in all_jobs:
            if not (jobobj.job_state in ["CANCELED", "COMPLETED", "FAILED"]):
                print_debug('\nDEBUG: Waiting for %s (currently: %s) to '
                            'finish running against the container.\n' %
                            (jobobj.reference, jobobj.job_state))

                #If so, wait
                job_context.wait(self.server_session, jobobj.reference)
