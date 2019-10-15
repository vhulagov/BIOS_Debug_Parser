import os
import time
import json
from requests_toolbelt import MultipartEncoder
import requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

import argparse
import logging

logging.basicConfig(level=logging.DEBUG)

import logging
import contextlib
try:
    from http.client import HTTPConnection # py3
except ImportError:
    from httplib import HTTPConnection # py2

def debug_requests_on():
    '''Switches on logging of the requests module.'''
    HTTPConnection.debuglevel = 1

    logging.basicConfig()
    logging.getLogger().setLevel(logging.DEBUG)
    requests_log = logging.getLogger("requests.packages.urllib3")
    requests_log.setLevel(logging.DEBUG)
    requests_log.propagate = True

def debug_requests_off():
    '''Switches off logging of the requests module, might be some side-effects'''
    HTTPConnection.debuglevel = 0

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.WARNING)
    root_logger.handlers = []
    requests_log = logging.getLogger("requests.packages.urllib3")
    requests_log.setLevel(logging.WARNING)
    requests_log.propagate = False

@contextlib.contextmanager
def debug_requests():
    '''Use with 'with'!'''
    debug_requests_on()
    yield
    debug_requests_off()

class BMCHttpApi(object):

    def __init__(self, host, user, password, test_bios_rbu):
        self.host = host
        self.user = user
        self.password = password
        self.test_bios_rbu = test_bios_rbu
        self.header = {}
        self.api_url = 'https://[' + self.host + ']/'
        #self.api_url = 'https://[' + self.host.replace('%', '%25') + ']/'
        #self.header = {'Content-Type': 'application/x-www-form-urlencoded'}
        #self.header = {'Content-Type': 'application/x-www-form-urlencoded', 'User-Agent': 'curl/7.54.0', 'Host': '[' + self.host + ']'}
                          #'Host': '[' + self.host.split('%')[0] + ']'}

    def create_session(self):
        # Get QSESSIONID and X-CSRFTOKEN to log into AMI API
        payload = {'username': self.user, 'password': self.password}
        self.session = requests.Session()
        r = self.session.post(url=self.api_url + 'api/session', params=payload,
            headers=self.header, verify=False)
        #print(self.session)
        #print(dir(self.session))
        if r.ok:
            try:
                print(r)
                j = r.json()
            except Exception as e:
                print(self.host + " Failed to log into AMI Session" + str(e))
                return False
            print(j)
            CSRFToken = j["CSRFToken"]
            QSESSIONID = self.session.cookies["QSESSIONID"]
        else:
            print(self.host + " Failed to log into AMI Session")
            return False

        # Update Header with QSESSIONID, X-CSRFTOKEN Details and new Content Type
        self.header.update({'Cookie': 'QSESSIONID=' + QSESSIONID})
        self.header.update({"X-CSRFTOKEN": CSRFToken})
        self.logged = True
        return self.logged

    def destroy_session(self):
        #self.header.update({'Content-Type': 'application/json'})
        r = self.session.delete(url=self.api_url + 'api/session', headers=self.header, verify=False)
        print(r)
        if r.ok:
            self.logged = False
            return True
        else:
            print(self.host + " Failed to log out session")
            return False

    def update_microcode(self):
        class MicrocodeUpdateError(Exception):
            """Raise if any step of preparing to microcode update fails"""
            print("Exception: " + str(Exception))
    #        self.destroy_session()
    #            resp_bin_file_path = '/tmp/resp.bin'
    #            resp_bin_file = open(resp_bin_file_path, 'wb')
    #            resp_bin_file.write(r.content)

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


    def getVirtualMediaStatus(self):
        if self.logged:
            pass
        else:
            return {}
        self.api_url = 'https://[' + self.host.replace('%', '%25') + ']/'
        self.session = self.session.get(url=self.api_url + 'api/settings/media/instance', headers=self.header, verify=False)

        if self.session.ok:
            try:
                j = self.session.json()
            except:
                return {}

        return j

 # Each Redfish Update Requires just one PUT Call. Can't use multiple PUT Calls
    def setMiniOSDefaults(self):
        try:
            self.session = self.session.put(self.redfishapi + 'Systems/Self/Bios/SD', auth=(self.username, self.password),\
                                   verify=False, headers=self.redfishheader,\
                                   # data='{"Attributes":{"FBO001":"LEGACY","FBO101":"CD/DVD","FBO102":"USB","FBO103":"Hard Disk","FBO104":"Network"}}')\
        
                                   data='{"Attributes":{"FBO001":"UEFI","FBO201":"CD/DVD","FBO202":"USB","FBO203":"Hard Disk","FBO204":"Network","CRCS005":"Enable","IIOS1FE":"Enable", "IPMI100":"Disabled"}}')
            if self.session.status_code == 200:
                print(self.host + ' ' + 'Successfully set MiniOS BIOS Settings')
            else:
                print(self.host + ' ' + 'Hooray Failed to set MiniOS BIOS Settings')

        except:
            pass
        #if self.session.status_code == 204:
        #    print(self.host + ' ' + 'Successfully set MiniOS BIOS Settings')
        #else:
        #    print(self.host + ' ' + 'Failed to set MiniOS BIOS Settings')

    # Returns the file details about the device in either date form or version form
    # Note: Nodes can only be used with date form. Can't force update incorrect BMC/BIOs combo
    def returnfirmwarefileJSON(self, name, inputdata):
        print("The name for node is: ", name)
        print ("The inputdata for nodedate is: ", inputdata)
        print ("============================================")

        for device, data in self.firmwaredictionary.items():
            if name in device:
                for datesel, json in data.items():
                    if inputdata in datesel or inputdata in json.get("Version", ""):
                        return json
        raise ValueError("Can't find JSON profile")

    def returnfilepath(self, name):
        for root, dirs, files in os.walk(self.path):
            for file in files:
                if name in file:
                    return str(os.path.join(root, file))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('host')
    args = parser.parse_args()

    bmc_api = BMCHttpApi(args.host, 'ADMIN', 'ADMIN', '/home/lacitis/WORK/ROMS/GB/MY81-EX0-Y3N/BIOS/R05/STEP/2.10/R05_STEP_2_10_NoPPR.RBU')
    bmc_api.update_microcode()
