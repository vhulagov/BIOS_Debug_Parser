import os
import time
import json
import requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

import argparse
#
#
#import contextlib
#try:
#    from http.client import HTTPConnection # py3
#except ImportError:
#    from httplib import HTTPConnection # py2
#
#def debug_requests_on():
#    '''Switches on logging of the requests module.'''
#    HTTPConnection.debuglevel = 1
#
#    logging.basicConfig()
#    logging.getLogger().setLevel(logging.DEBUG)
#    requests_log = logging.getLogger("requests.packages.urllib3")
#    requests_log.setLevel(logging.DEBUG)
#    requests_log.propagate = True
#
#def debug_requests_off():
#    '''Switches off logging of the requests module, might be some side-effects'''
#    HTTPConnection.debuglevel = 0
#
#    root_logger = logging.getLogger()
#    root_logger.setLevel(logging.WARNING)
#    root_logger.handlers = []
#    requests_log = logging.getLogger("requests.packages.urllib3")
#    requests_log.setLevel(logging.WARNING)
#    requests_log.propagate = False

class BMCHttpApi(object):

    def __init__(self, host, user, password, test_bios_rbu, logger=None):
        self.host = host
        self.user = user
        self.password = password
        self.test_bios_rbu = test_bios_rbu
        if not logger:
            import logging
            logging.basicConfig(level=logging.INFO)

        self.header = {}
        #self.header.update({'Content-Type': 'application/json'})
        self.api_url = 'https://[' + self.host + ']/'

    def create_session(self):
        # Get QSESSIONID and X-CSRFTOKEN to log into AMI API
        payload = {'username': self.user, 'password': self.password}
        self.session = requests.Session()
        r = self.session.post(url=self.api_url + 'api/session', params=payload,
            headers=self.header, verify=False)
        if r.ok:
            try:
                j = r.json()
            except Exception as e:
                print(self.host + " Failed to log into AMI Session" + str(e))
                return False
            CSRFToken = j["CSRFToken"]
            QSESSIONID = self.session.cookies["QSESSIONID"]
        else:
            print(self.host + " Failed to log into AMI Session")
            return False

        # Update Header with QSESSIONID, X-CSRFTOKEN
        self.header.update({'Cookie': 'QSESSIONID=' + QSESSIONID})
        self.header.update({"X-CSRFTOKEN": CSRFToken})
        self.logged = True
        return self.logged

    def destroy_session(self):
        r = self.session.delete(url=self.api_url + 'api/session', headers=self.header, verify=False)
        if r.ok:
            self.logged = False
            return True
        else:
            print(self.host + " Failed to log out session")
            return False

    def api_error(Exception):
        """Raise if any step of preparing to microcode update fails"""
        print("Exception: " + str(Exception))
        self.destroy_session()

    def get_STEP_possibility(self):
        try:
            self.create_session()
            r = self.session.get(url=self.api_url + 'api/system_inventory_gbt/dimm_info',
                                headers=self.header, verify=False)
            dimm_info_json = json.loads(r.content)
            print(json.dumps(dimm_info_json, indent=2))
            print("Founded DRAM: " + str(dimm_info_json[0]['strPartNum']))
            if dimm_info_json[0]['strManufacturer'] == 'Samsung':
                return True
            else:
                return False
        except Exception as e:
            print(self.host + " Fail: " + str(e))
            # Don't forget to log our of self.session
            self.destroy_session()


    def update_microcode(self):
        print("Creating new session...")
        try:
            self.create_session()
            print(self.header)
        except Exception as e:
            print(self.host + " Fail: " + str(e))
            # Don't forget to log our of self.session
            self.destroy_session()
        print("Successfully open new session with " + self.host)

        data = { 'flash_type' : 'BIOS' }
        r = self.session.put(url=self.api_url + 'api/maintenance/flash', json=data,
                            headers=self.header, verify=False)
        print(r.content)
        if not r.ok:
            raise MicrocodeUpdateError(r.content)

        print("Uploading firmware image...")
        multipart_form_data = {
            'fwimage': ('R05_STEP_2_10_NoPPR.RBU', open(self.test_bios_rbu, 'rb')),
        }
        #files = { 'file': ('fwimage', open(self.test_bios_rbu, 'rb'))}
        #data = { 'name': 'fwimage', 'filename': 'R05_STEP_2_10_NoPPR.RBU' }
        #debug_requests_on()
        r = self.session.post(url=self.api_url + 'api/maintenance/firmware', files=multipart_form_data,
                            headers=self.header, verify=False)
        for r_str in r.content.split('\n'):
            try:
                r_json = json.loads(r_str)
            except Exception:
                pass
        if not r.ok:
            raise MicrocodeUpdateError(r.content)
        if not r_json or r_json['cc'] != 0:
            print(str(r.raw))
            print('Invalid status code!')
            raise MicrocodeUpdateError(r.content)
        print("Do verification...")
        params = {'flash_type': 'BIOS'}
        #params = []
        print(self.header)
        r = self.session.get(url=self.api_url + 'api/maintenance/firmware/verification', params=params,
                            headers=self.header, verify=False)
        if not r.ok:
            raise MicrocodeUpdateError(r.content)
        print("Starting to update...")
        data = { "flash_status":1, "preserve_config":0, "flash_type":"BIOS" }
        r = self.session.put(url=self.api_url + 'api/maintenance/firmware/upgrade', json=data,
                            headers=self.header, verify=False)
        if not r.ok:
            raise MicrocodeUpdateError(r.content)

        print("Monitor flash progress")
        for i in range(7):
            progress = self.session.get(url=self.api_url + 'api/maintenance/firmware/flash-progress',
                            headers=self.header, verify=False)
            print(progress)
            time.sleep(20)

        self.destroy_session()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('host')
    args = parser.parse_args()

    bmc_api = BMCHttpApi(args.host, 'ADMIN', 'ADMIN', '/home/lacitis/WORK/ROMS/GB/MY81-EX0-Y3N/BIOS/R05/STEP/2.10/R05_STEP_2_10_NoPPR.RBU')
    # Check from BMC API that installed memory is Samsung 
    if bmc_api.get_STEP_possibility():
        print("GOOD NEWS! STEP IS POSSIBLE!")
        # Update BIOS to DEBUG version
        #bmc_api.update_microcode()
        # Activate SOL parser
        #...
