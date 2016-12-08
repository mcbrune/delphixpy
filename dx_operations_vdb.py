#!/usr/bin/env python
# Corey Brune - Oct 2016
#This script starts or stops a VDB
#requirements
#pip install docopt delphixpy

#The below doc follows the POSIX compliant standards and allows us to use
#this doc to also define our arguments for the script.
"""List all VDBs or Start, stop, enable, disable a VDB
Usage:
  dx_operations_vdb.py (--vdb <name [--stop | --start | --enable | --disable] | --list)
                  [-d <identifier> | --engine <identifier> | --all]
                  [--debug] [--parallel <n>] [--poll <n>]
                  [--config <path_to_file>] [--logdir <path_to_file>]
  dx_operations_vdb.py -h | --help | -v | --version
List all VDBs, start, stop, enable, disable a VDB

Examples:
  dx_operations_vdb.py -d landsharkengine --vdb testvdb --stop

  dx_operations_vdb.py --vdb --start

Options:
  --vdb <name>              Name of the VDB to stop or start
  --start                   Stop the VDB
  --stop                    Stop the VDB
  --list                    List all databases from an engine
  --enable                  Enable the VDB
  --disable                 Disable the VDB
  -d <identifier>           Identifier of Delphix engine in dxtools.conf.
  --engine <type>           Alt Identifier of Delphix engine in dxtools.conf.
  --all                     Run against all engines.
  --debug                   Enable debug logging
  --parallel <n>            Limit number of jobs to maxjob
  --poll <n>                The number of seconds to wait between job polls
                            [default: 10]
  --config <path_to_file>   The path to the dxtools.conf file
                            [default: ./dxtools.conf]
  --logdir <path_to_file>    The path to the logfile you want to use.
                            [default: ./dx_operations_vdb.log]
  -h --help                 Show this screen.
  -v --version              Show version.
"""

VERSION="v.0.0.002"

from docopt import docopt
import logging
from os.path import basename
import signal
import sys
import time
import traceback
import json

from multiprocessing import Process
from time import sleep, time

from delphixpy.v1_6_0.delphix_engine import DelphixEngine
from delphixpy.v1_6_0.exceptions import HttpError, JobError
from delphixpy.v1_6_0 import job_context
from delphixpy.v1_6_0.web import database, host, job, source
from delphixpy.v1_6_0.exceptions import RequestError, JobError, HttpError


class dlpxException(Exception):
    def __init__(self, message):
        self.message = message


def vdb_operation(engine, server, jobs, vdb_name, operation):
    """
    Function to start, stop, enable or disable a VDB
    """
    print_debug(engine['hostname'] + ': Searching for ' + vdb_name +
                ' reference.\n')

    vdb_obj = find_obj_by_name(engine, server, source, vdb_name)

    try:
        if vdb_obj:
            if operation == 'start':
                source.start(server, vdb_obj.reference)
            elif operation == 'stop':
                source.stop(server, vdb_obj.reference)
            elif operation == 'enable':
                source.enable(server, vdb_obj.reference)
            elif operation == 'disable':
                source.disable(server, vdb_obj.reference)

            jobs[engine['hostname']] = server.last_job

    except (RequestError, HttpError, JobError, AttributeError), e:
        raise dlpxException('An error occurred while performing ' +
                            operation + ' on ' + vdb_name + '.:%s\n' % (e))


def list_databases(engine, server, jobs):
    """
    Function to list all databases for a given engine
    """

    try:
        databases = database.get_all(server)

        for db in databases:
            if db.provision_container == None:
                db.provision_container = 'dSource'

            print 'name = ', str(db.name), '\n', 'current timeflow = ', \
                  str(db.current_timeflow), '\n', 'provision container = ', \
                  str(db.provision_container), '\n', 'processor = ', \
                  str(db.processor), '\n'

    except (RequestError, HttpError, JobError, AttributeError), e:
        print 'An error occurred while listing databases on ' + \
              engine['ip_address'] + '.:%s\n' % (e)


def find_obj_by_name(engine, server, f_class, obj_name):
    """
    Function to find objects by name and object class, and return object's
    reference as a string
    You might use this function to find objects like groups.
    """
    print_debug(engine["hostname"] + ": Searching objects in the " +
                f_class.__name__ + " class\n   for one named \"" +
                obj_name + "\"")
    obj_ref = ''

    all_objs = f_class.get_all(server)
    try:
        for obj in all_objs:
            if obj.name == obj_name:
                print_debug(engine["hostname"] + ": Found a match " +
                            str(obj.reference))
                return obj

        #If the code reaches here, the object was not found.
        raise dlpxException('Object %s not found in %s\n' % (obj_name,
                            engine['ip_address']))

    except (RequestError, HttpError, JobError, AttributeError), e:
        raise dlpxException('Object %s not found in %s' % (obj_name, 
                            engine['ip_address']))


def get_config(config_file_path):
    """
    This function reads in the dxtools.conf file
    """
    #First test to see that the file is there and we can open it
    try:
        config_file = open(config_file_path).read()
    except:
        print_error("Was unable to open " + config_file_path +
                    ". Please check the path and permissions, then try again.")
        sys.exit(1)

    #Now parse the file contents as json and turn them into a python
    # dictionary, throw an error if it isn't proper json
    try:
        config = json.loads(config_file)
    except:
        print_error("Was unable to read " + config_file_path +
                    " as json. Please check file in a json formatter and " +
                    "try again.")
        sys.exit(1)

    #Create a dictionary of engines (removing the data node from the
    # dxtools.json, for easier parsing)
    delphix_engines = {}
    for each in config['data']:
        delphix_engines[each['hostname']] = each
    print_debug(delphix_engines)
    return delphix_engines


def logging_est(logfile_path):
    """
    Establish Logging
    """
    global debug
    logging.basicConfig(filename=logfile_path,format='%(levelname)s:%(asctime)s:%(message)s', level=logging.INFO, datefmt='%Y-%m-%d %H:%M:%S')
    print_info("Welcome to " + basename(__file__) + ", version " + VERSION)
    global logger
    debug = arguments['--debug']
    logger = logging.getLogger()
    if debug == True:
        logger.setLevel(10)
        print_info("Debug Logging is enabled.")


def job_mode(server):
    """
    This function tells Delphix how to execute jobs, based on the
    single_thread variable at the beginning of the file
    """
    #Synchronously (one at a time)
    if single_thread == True:
        job_m = job_context.sync(server)
        print_debug("These jobs will be executed synchronously")
    #Or asynchronously
    else:
        job_m = job_context.async(server)
        print_debug("These jobs will be executed asynchronously")
    return job_m


def job_wait():
    """
    This job stops all work in the thread/process until jobs are completed.
    """
    #Grab all the jos on the server (the last 25, be default)
    all_jobs = job.get_all(server)
    #For each job in the list, check to see if it is running (not ended)
    for jobobj in all_jobs:
        if not (jobobj.job_state in ["CANCELED", "COMPLETED", "FAILED"]):
            print_debug("Waiting for " + jobobj.reference + " (currently: " +
                        jobobj.job_state +
                        ") to finish running against the container")
            #If so, wait
            job_context.wait(server,jobobj.reference)



def on_exit(sig, func=None):
    """
    This function helps us end cleanly and with exit codes
    """
    print_info("Shutdown Command Received")
    print_info("Shutting down " + basename(__file__))
    sys.exit(0)


def print_debug(print_obj):
    """
    Call this function with a log message to prefix the message with DEBUG
    """
    try:
        if debug == True:
            print "DEBUG: " + str(print_obj)
            logging.debug(str(print_obj))
    except:
        pass


def print_error(print_obj):
    """
    Call this function with a log message to prefix the message with ERROR
    """
    print "ERROR: " + str(print_obj)
    logging.error(str(print_obj))


def print_info(print_obj):
    """
    Call this function with a log message to prefix the message with INFO
    """
    print "INFO: " + str(print_obj)
    logging.info(str(print_obj))


def print_warning(print_obj):
    """
    Call this function with a log message to prefix the message with WARNING
    """
    print "WARNING: " + str(print_obj)
    logging.warning(str(print_obj))


def run_async(func):
    """
        http://code.activestate.com/recipes/576684-simple-threading-decorator/
        run_async(func)
            function decorator, intended to make "func" run in a separate
            thread (asynchronously).
            Returns the created Thread object
            E.g.:
            @run_async
            def task1():
                do_something
            @run_async
            def task2():
                do_something_too
            t1 = task1()
            t2 = task2()
            ...
            t1.join()
            t2.join()
    """
    from threading import Thread
    from functools import wraps

    @wraps(func)
    def async_func(*args, **kwargs):
        func_hl = Thread(target = func, args = args, kwargs = kwargs)
        func_hl.start()
        return func_hl

    return async_func


@run_async
def main_workflow(engine):
    """
    This function actually runs the jobs.
    Use the @run_async decorator to run this function asynchronously.
    This allows us to run against multiple Delphix Engine simultaneously
    """

    #Pull out the values from the dictionary for this engine
    engine_address = engine["ip_address"]
    engine_username = engine["username"]
    engine_password = engine["password"]
    #Establish these variables as empty for use later
    jobs = {}

    #Setup the connection to the Delphix Engine
    server = serversess(engine_address, engine_username, engine_password)

    try:
        if arguments['--vdb']:
            #Get the database reference we are copying from the database name
            database_obj = find_obj_by_name(engine, server, database,
                                            arguments['--vdb'])

    except dlpxException, e:
        print '\nERROR: %s\n' % (e.message)
        sys.exit(1)

    thingstodo = ["thingtodo"]
    #reset the running job count before we begin
    i = 0
    with job_mode(server):
        while (len(jobs) > 0 or len(thingstodo)> 0):
            if len(thingstodo)> 0:

                if arguments['--start']:
                    vdb_operation(engine, server, jobs, database_name, 'start')

                elif arguments['--stop']:
                    vdb_operation(engine, server, jobs, database_name, 'stop')

                elif arguments['--enable']:
                    vdb_operation(engine, server, jobs, database_name,
                                  'enable')

                elif arguments['--disable']:
                    vdb_operation(engine, server, jobs, database_name,
                                  'disable')

                elif arguments['--list']:
                    list_databases(engine, server, jobs)

                thingstodo.pop()

            #get all the jobs, then inspect them
            i = 0
            for j in jobs.keys():
                job_obj = job.get(server, jobs[j])
                print_debug(job_obj)
                print_info(engine["hostname"] + ": VDB Operations: " +
                           job_obj.job_state)

                if job_obj.job_state in ["CANCELED", "COMPLETED", "FAILED"]:
                    #If the job is in a non-running state, remove it from the
                    # running jobs list.
                    del jobs[j]
                else:
                    #If the job is in a running state, increment the running
                    # job count.
                    i += 1

            print_info(engine["hostname"] + ": " + str(i) + " jobs running. ")
            #If we have running jobs, pause before repeating the checks.
            if len(jobs) > 0:
                sleep(float(arguments['--poll']))


def run_job(engine):
    """
    This function runs the main_workflow aynchronously against all the servers
    specified
    """
    #Create an empty list to store threads we create.
    threads = []

    #If the --all argument was given, run against every engine in dxtools.conf
    if arguments['--all']:
        print_info("Executing against all Delphix Engines in the dxtools.conf")

        #For each server in the dxtools.conf...
        for delphix_engine in dxtools_objects:
            engine = dxtools_objects[delphix_engine]

            #Create a new thread and add it to the list.
            threads.append(main_workflow(engine))
    else:

        #Else if the --engine argument was given, test to see if the engine
        # exists in dxtools.conf
        if arguments['--engine']:
            try:
                engine = dxtools_objects[arguments['--engine']]
                print_info("Executing against Delphix Engine: " +
                           arguments['--engine'])
            except:
                print_error("Delphix Engine \"" + arguments['--engine'] +
                            "\" cannot be found in " + config_file_path)
                print_error("Please check your value and try again. Exiting")
                sys.exit(1)

        #Else if the -d argument was given, test to see if the engine exists
        # in dxtools.conf
        elif arguments['-d']:
            try:
                engine = dxtools_objects[arguments['-d']]
                print_info("Executing against Delphix Engine: " +
                           arguments['-d'])
            except:
                print_error("Delphix Engine \"" + arguments['-d'] +
                            "\" cannot be found in " + config_file_path)
                print_error("Please check your value and try again. Exiting")
                sys.exit(1)
        else:
            #Else search for a default engine in the dxtools.conf
            for delphix_engine in dxtools_objects:
                if dxtools_objects[delphix_engine]['default'] == 'true':
                    engine = dxtools_objects[delphix_engine]
                    print_info("Executing against the default Delphix Engine "
                               "in the dxtools.conf: " +
                               dxtools_objects[delphix_engine]['hostname'])
                    break

            if engine == None:
                print_error("No default engine found. Exiting")
                sys.exit(1)

        #run the job against the engine
        threads.append(main_workflow(engine))

    #For each thread in the list...
    for each in threads:
        #join them back together so that we wait for all threads to complete
        # before moving on
        each.join()


def serversess(f_engine_address, f_engine_username, f_engine_password):
    """
    Function to setup the session with the Delphix Engine
    """
    server_session= DelphixEngine(f_engine_address, f_engine_username,
                                  f_engine_password, "DOMAIN")
    return server_session


def set_exit_handler(func):
    """
    This function helps us set the correct exit code
    """
    signal.signal(signal.SIGTERM, func)


def time_elapsed():
    """
    This function calculates the time elapsed since the beginning of the script.
    Call this anywhere you want to note the progress in terms of time
    """
    elapsed_minutes = round((time() - time_start)/60, +1)
    return elapsed_minutes


def update_jobs_dictionary(engine, server, jobs):
    """
    This function checks each job in the dictionary and updates its status or
    removes it if the job is complete.
    Return the number of jobs still running.
    """
    #Establish the running jobs counter, as we are about to update the count
    # from the jobs report.
    i = 0
    #get all the jobs, then inspect them
    for j in jobs.keys():
        job_obj = job.get(server, jobs[j])
        print_debug(engine["hostname"] + ": " + str(job_obj))
        print_info(engine["hostname"] + ": " + j.name + ": " +
                   job_obj.job_state)

        if job_obj.job_state in ["CANCELED", "COMPLETED", "FAILED"]:
            #If the job is in a non-running state, remove it from the running
            # jobs list.
            del jobs[j]
        else:
            #If the job is in a running state, increment the running job count.
            i += 1
    return i

def main(argv):
    #We want to be able to call on these variables anywhere in the script.
    global single_thread
    global usebackup
    global time_start
    global config_file_path
    global database_name
    global host_name
    global dxtools_objects

    try:
        logging_est(arguments['--logdir'])
        print_debug(arguments)
        time_start = time()
        engine = None
        single_thread = False
        config_file_path = arguments['--config']
        #Parse the dxtools.conf and put it into a dictionary
        dxtools_objects = get_config(config_file_path)

        database_name = arguments['--vdb']

        #This is the function that will handle processing main_workflow for
        # all the servers.
        run_job(engine)

        elapsed_minutes = time_elapsed()
        print_info("script took " + str(elapsed_minutes) +
                   " minutes to get this far.")

    #Here we handle what we do when the unexpected happens
    except SystemExit as e:
        """
        This is what we use to handle our sys.exit(#)
        """
        sys.exit(e)
    except HttpError as e:
        """
        We use this exception handler when our connection to Delphix fails
        """
        print_error("Connection failed to the Delphix Engine")
        print_error( "Please check the ERROR message below")
        print_error(e.message)
        sys.exit(2)
    except JobError as e:
        """
        We use this exception handler when a job fails in Delphix so that we have actionable data
        """
        print_error("A job failed in the Delphix Engine")
        print_error(e.job)
        elapsed_minutes = time_elapsed()
        print_info(basename(__file__) + " took " + str(elapsed_minutes) + " minutes to get this far.")
        sys.exit(3)
    except KeyboardInterrupt:
        """
        We use this exception handler to gracefully handle ctrl+c exits
        """
        print_debug("You sent a CTRL+C to interrupt the process")
        elapsed_minutes = time_elapsed()
        print_info(basename(__file__) + " took " + str(elapsed_minutes) + " minutes to get this far.")
    except:
        """
        Everything else gets caught here
        """
        print_error(sys.exc_info()[0])
        print_error(traceback.format_exc())
        elapsed_minutes = time_elapsed()
        print_info(basename(__file__) + " took " + str(elapsed_minutes) + " minutes to get this far.")
        sys.exit(1)

if __name__ == "__main__":
    #Grab our arguments from the doc at the top of the script
    arguments = docopt(__doc__, version=basename(__file__) + " " + VERSION)
    #Feed our arguments to the main function, and off we go!
    main(arguments)
