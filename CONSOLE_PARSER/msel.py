# -*- coding: utf-8 -*-

from __future__ import print_function

import time
import yaml
import rethinkdb

class MemorySubsytemEventsLogger():
    def __init__(self, baseboard):
        self.baseboard = baseboard
	with open('spec_{0}.yaml'.format(self.baseboard), 'r') as stream:
	    try:
		self.node_configuration = yaml.safe_load(stream)
	    except yaml.YAMLError as e:
		print(e)
        #node_configuration = yaml.load(open('spec_{0}.yaml'.format(self.baseboard), 'r'), Loader=yaml.BaseLoader)
        #print(node_configuration)
        self.sys_conf = {
            'chassis_inv': '',
            'baseboard_sn': '',
            'sys_vendor': '',
            'product_name' : '',
            'baseboard_vendor' : '',
            'baseboard_model' : '',

            'bios_conf_id': 'current', # TODO also calc sha256 for BIOS conf
            'poppulation': self.node_configuration['dimm_conf'],
            'current_speed': '', # TODO get from dmidecode struct or MRC output 
            'slot_id': '', # TODO from dmidecode or MRC ouput
            'frb_degraded': False, # if one of the dimm in a neighbour slot is already blocked
            'blocked_ranks': [],
            'margin_results': {} # TODO from BDAT
        }
    
        self.dimms_spec = []
        """ Collectors used in case if serial is not detected
        and not to much sense logging events to rethinkdb directrly """
        self.dimm_failures_collector = []
        self.ppr_events_collector = []
        self.memory_subsytem_events = {
            'serial': {
                'dimm_spec': [],
                'sys_conf': self.sys_conf,
                'dimm_failures_info': [],
                'dimm_hppr_events': []
            }
        }

    def format_dimm_spec(self):
        dimm_spec_struct = {
            'functional', # JEDEC label
            'vendor',
            'model',
            'pn',
            'prod_week', #wwyy
            'dram_vendor',
            'factory_loc', # two-letter code in UPPER case
            'rcd',
            'si_die'
        }
        for field in dimm_ee_data_fields:
            if field in data.keys():
                dimm_error_event_struct[field] = data.pop(field)

        self.dimms_spec.append({timestamp: dimm_error_event_struct})


    def get_last_sys_conf_id(self):
        """Get hash (unique ID) of last system envirenment (if exists)
        to be sure that nothing changed since last error"""
        import hashlib

        values = tuple(sorted(self.sys_conf.items()))
        def hash_item(m, k, v):
            m.update(k.encode('utf-8'))
            m.update(str(k).encode('utf-8'))

        m = hashlib.sha256()
        for k, v in values:
            hash_item(m, k, v)
        # Last 6 chars is enought
        hash_id = m.digest()[-6:]
        # TODO make request to DB and compare hashes

    def log_dimm_failure(self, sn):
        timestamp = time.time()
        dimm_failure_event_struct = {
            'fru': (str, 'dimm'),
            'component': '',
            'ue_risk': '', 
            'pp_repairable': False,
            'exact': False,
            'inspector': 'MRC_parser',
            'inspector_version': '0.10',
            'absolute_counters': {
                'nodes': [], 
                'channels': [], 
                'modules': [], 
                'ranks': [], 
                'subranks': [], 
                'banks': [], 
                'bank_groups': [], 
                'bank_addresss': [], 
                'devices': [], 
                'rows': [], 
                'columns': [], 
                'dqs': []
                }
            }

    def log_dimm_error_event(self, data):
        # STEP event: [FailedPatternBitMask 0x4] N0.C1.D0. FAIL: R0.CID0.BG3.BA3.ROW:0x0119f.COL:0x1a8.DQ46.Temp45'CPPR:Done(PASS)
        # SAT miscompare: 
        # AMD syndrome:
        timestamp = time.time()
        dimm_error_event_struct = {}
#        dimm_error_event_struct = {
#            'data_provider': (str, 'MBIST')
#            'logger': (str, 'STEP'),
#            'logger_version': (str, '0.10'),
#            'transaction': (str),
#            'transaction_data': (str),
#            'temperature': (int),
#            'node': (int),
#            'channel': (int),
#            'module': (int),
#            'rank': (int),
#            'subrank': (int),
#            'bank': (int),
#            'bank_group': (int),
#            'bank_address': (int),
#            'device': (int),
#            'row': (float),
#            'dram_mask': (float),
#            'dq': (int)
#        }

        dimm_ee_data_fields = [
            'data_provider',
            'logger',
            'logger_version',
            'transaction',
            'transaction_data',
            'temperature',
            'socket',
            'channel',
            'dimm',
            'rank',
            'subrank',
            'bank',
            'bank_group',
            'bank_address',
            'device',
            'row',
            'dram_mask'
        ]
        for field in dimm_ee_data_fields:
            if field in data.keys():
                dimm_error_event_struct[field] = data.pop(field)

        self.dimm_failures_collector.append({timestamp: dimm_error_event_struct})
        print(self.dimm_failures_collector)
        return data

    def log_dimm_hppr_event(self, sn, timestamp):
        """
        Execute PPR : N0.C1.D0.R0 Sub-R0.Row 0x0119f.BG3.BA3.DQ46^M
        Fail Information : ch = 1, dimm = 0, rank = 0, cid = 0, bank = 0xf, addr = 0x119f, DRAM mask = 0x800^M
        numRowbit = 17, MaxRow = 0x1ffff.^M
        Execute address inversion for SIDE_B.^M
        Current Bank = 15, Address = 0x119f.^M
        Inversioned Bank = 0, Address = 0x23a67.^M
        """
        dimm_hppr_event_struct = {
            'actuator': (str, 'STEP'),
            'inspector_version': (str, '0.10'),
            'node': (int),
            'channel': (int),
            'module': (int),
            'rank': (int),
            'subrank': (int),
            'bank': (int),
            'bank_group': (int),
            'bank_address': (int),
            'device': (int),
            'row': (float),
            'dram_mask': (float),
            'dq': (int)
        }


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('host')
    args = parser.parse_args()

    r = RethinkDB()

# vim: tabstop=8 softtabstop=0 expandtab shiftwidth=4 smarttab
