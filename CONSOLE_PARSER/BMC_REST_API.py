# -*- coding: utf-8 -*-

from __future__ import print_function

import os
import sys
import time
import json
import logging
import requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

logging.getLogger("requests").setLevel(logging.WARNING)

import base64

import argparse
from smbios import SMBios

step_release_date = '06/20/2019'
r05_rbu_file_path = '/home/lacitis/WORK/ROMS/GB/MY81-EX0-Y3N/BIOS/R05/RBU/image.RBU'
step_rbu_file_path = '/home/lacitis/WORK/ROMS/GB/MY81-EX0-Y3N/BIOS/R05/STEP/2.10/R05_STEP_2_10_NoPPR.RBU'
step_w_ppr_rbu_file_path = '/home/lacitis/WORK/ROMS/GB/MY81-EX0-Y3N/BIOS/R05/STEP/2.10/R05_STEP_2_10_PPR.RBU'

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

    def __init__(self, host, user, password, logger=None):
        self.host = host
        self.user = user
        self.password = password
        self.logged = False
        if not logger:
            import logging
            logging.basicConfig(level=logging.INFO)

        self.header = {}
        #self.header.update({'Content-Type': 'application/json'})
        self.api_url = 'https://[' + self.host + ']/'

    def MicrocodeUpdateError(Exception):
        """Raise if any step of preparing to microcode update fails"""
        print("Exception: " + str(Exception))

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

    def get_BIOS_setup(self):
        import gzip
        if not self.logged:
            print("Getting BIOS settings...")
            try:
                self.create_session()
                r = self.session.get(url=self.api_url + 'api/system_inventory_gbt/bios-setup-file',
                                    headers=self.header, verify=False)
                if not r.ok:
                    raise self.MicrocodeUpdateError(r.content)
                #bios_settings_gz = r.content.decode('base64')
                bios_settings_gz = base64.b64decode(r.content)
                bios_settings_json_bytes = gzip.decompress(bios_settings_gz)
                with open('/tmp/bios_settings.json', 'wb') as f:
                    f.write(bios_settings_json_bytes)
                #bios_settings_json = json.loads(bios_settings_json_bytes.decode('utf8').replace("'", '"'))
                bios_settings_json = json.loads(bios_settings_json_bytes.decode('utf8'))
                print(type(bios_settings_json))
                print(json.dumps(bios_settings_json, indent=2))
            except Exception as e:
                print(str(e))
                self.destroy_session()

    def get_SMBIOS_information(self):
        try:
            self.create_session()
            r = self.session.get(url=self.api_url + 'api/system_inventory_gbt/smbios-file',
                                headers=self.header, verify=False)
            if not r.ok:
                raise self.MicrocodeUpdateError(r.content)
            #smbios_bin = r.content.decode('base64')
            smbios_bin = base64.b64decode(r.content)
            #print(smbios_bin)
            #open('/tmp/smbios.decoded', 'wb').write(smbios_bin)
            smbios_class = SMBios(smbios_bin)
            self.smbios = smbios_class.decode_all()
            if self.smbios:
                return True
        except Exception as e:
            print(str(e))
            self.destroy_session()

    def get_STEP_possibility(self):
        if bmc_api.get_SMBIOS_information():
            cur_bios_release_date = bmc_api.smbios['type0']['bios_release_date']
            system_model = bmc_api.smbios['type1']['system_model']
            memory_manufacturer = bmc_api.smbios['type17'][0]['manufacturer']
            memory_pn = bmc_api.smbios['type17'][0]['part_number']
            print('Detected {0} {1} memory in node type: {2}'.format(memory_manufacturer, memory_pn, system_model))
            # STEP is applicable only on Samsung's DRAM and in T175-N41-Y3N platform
            #if memory_manufacturer == 'Samsung' and system_model == 'T175-N41-Y3N':
            if system_model == 'T175-N41-Y3N':
                return True
            else:
                return False

    def update_microcode(self, rbu_file):
        if self.logged == False:
            print("Creating new session...")
            try:
                self.create_session()
                print(self.header)
                print("Successfully open new session with " + self.host)
            except Exception as e:
                print(self.host + " Fail: " + str(e))
                # Don't forget to log our of self.session
                self.destroy_session()

        print("Preparing SPI flash for update...")
        data = { 'flash_type' : 'BIOS' }
        r = self.session.put(url=self.api_url + 'api/maintenance/flash', json=data,
                            headers=self.header, verify=False)
        if not r.ok:
            raise self.MicrocodeUpdateError(r.content)

        print("Uploading firmware image..." + str(rbu_file))
        multipart_form_data = {
            'fwimage': (os.path.basename(rbu_file), open(rbu_file, 'rb')),
        }
        r = self.session.post(url=self.api_url + 'api/maintenance/firmware', files=multipart_form_data,
                            headers=self.header, verify=False)
        for r_str in r.content.split(b'\n'):
            try:
                r_json = json.loads(r_str.decode('utf-8'))
            except Exception:
                pass
        if not r.ok:
            raise self.MicrocodeUpdateError(r.content)
        if not r_json or r_json['cc'] != 0:
            print(str(r.raw))
            print('Invalid status code!')
            raise self.MicrocodeUpdateError(r.content)
        print("Do verification...")
        params = {'flash_type': 'BIOS'}
        r = self.session.get(url=self.api_url + 'api/maintenance/firmware/verification', params=params,
                            headers=self.header, verify=False)
        if not r.ok:
            raise self.MicrocodeUpdateError(r.content)
        print("Starting to update...")
        data = { "flash_status":1, "preserve_config":0, "flash_type":"BIOS" }
        r = self.session.put(url=self.api_url + 'api/maintenance/firmware/upgrade', json=data,
                            headers=self.header, verify=False)
        if not r.ok:
            raise self.MicrocodeUpdateError(r.content)

        print("Monitoring flash progress...")
        percent = '0'
        while percent != 'Complete':
            r = self.session.get(url=self.api_url + 'api/maintenance/firmware/flash-progress',
                            headers=self.header, verify=False)
            if not r.ok:
                raise self.MicrocodeUpdateError(r.content)
                break
            try:
                status = json.loads(r.content.decode('utf-8'))
                percent = status['progress'].split(' ')[0]
                sys.stdout.write("\r%s" % percent)
                sys.stdout.flush()
            except Exception as e:
                print("Progress bar don't work =(; Reason: " + str(e))
                pass
            time.sleep(10)
        print("\n")

        self.destroy_session()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('host')
    parser.add_argument('-f', '--force', action='store_true')
    parser.add_argument('-i', '--image')
    args = parser.parse_args()

    bmc_api = BMCHttpApi(args.host, 'ADMIN', 'ADMIN')
    # Get BIOS settings
#    bmc_api.get_BIOS_setup()
#    bmc_api.get_SMBIOS_information()
    bmc_api.get_STEP_possibility()
    sys.exit(0)

    # Check from BMC API that installed memory is Samsung 
    if bmc_api.get_STEP_possibility() or args.force:
        if args.image:
            print("Updating BIOS by using the following RBU image: " + str(args.image))
            bmc_api.update_microcode(args.image)
        else:
            #print("STEP is possible!")
            # Restore BIOS R05
            #bmc_api.update_microcode(r05_rbu_file_path)
            # Update BIOS to DEBUG version
            # STEP
            #bmc_api.update_microcode(step_rbu_file_path)
            # PPR
            print("PPR action by applying RBU image: " + str(step_w_ppr_rbu_file_path))
            bmc_api.update_microcode(step_w_ppr_rbu_file_path)
            # Power off the node

        # Activate SOL parser
