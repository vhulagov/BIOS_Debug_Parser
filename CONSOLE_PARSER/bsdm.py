# -*- coding: utf-8 -*-

from __future__ import print_function

import os
import sys
import signal
import fcntl

import argparse
import logging

import time
import stat
import re
import select
from collections import defaultdict
from collections import Counter

#from operator import itemgetter
import yaml
import json

# TODO move to separate class
import serial
import tty
import termios

from rmt import RMT
from step import STEP
from sol import SOL
from msel import MemorySubsytemEventsLogger

from benchmark.test_result import BasicTestResult
from benchmark.common import yank_api
from benchmark.conf import Conf, parse_list, parse_bool

sys.stdout = os.fdopen(sys.stdout.fileno(), 'w', 0)

logging.basicConfig(
    level=logging.DEBUG,
    format='[%(asctime)s] {%(filename)s:%(lineno)d} %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger()

rmt_instance = None
environment = {}

CONF_FILE = 'MRC_parser.ini'
parser_version = '0.23'

# Intel MRC base blocks
MRC_BBLOCK_START_RE = re.compile(r'START_([0-9A-Z_]+)')
MRC_BBLOCK_END_RE = re.compile(r'STOP_([0-9A-Z_]+)')

# Intel MRC iMC blocks functions
MRC_iMC_BLOCK_START_RE = re.compile(r'(^[A-Z@].*) -- Started')
MRC_iMC_BLOCK_END_RE = re.compile(r'(^[A-Z@].*) [-]?[=]? ([0-9]+)[ ]?ms')

# Intel SMM handlers sample code
MRC_SMM_BLOCK_START_RE = re.compile(r'(.*) Hander start!')
MRC_SMM_BLOCK_END_RE = re.compile(r'(.*) Hander end!')

# UEFI ACPI functions
#MRC_ACPI_START_RE = re.compile(r'^(.*): Class ID:  [0-9][0-9]')
MRC_ACPI_START_RE = re.compile(r'^(.*): Class ID:.*')
MRC_ACPI_END_RE = re.compile(r'^(.*) Exiting...')

# MRC Fatal Error
MRC_FATAL_ERROR_RE = re.compile(r'Major Code = [0-9]+, Minor Code = [0-9]+')

# Checkpoint regexp (POST codes):
#Checkpoint Code: Socket 0, 0xBF, 0x00, 0x0000
POST_CHECKPOINT_RE = re.compile(r'Checkpoint Code: Socket [01], (0x[0-9A-F]+), (0x[0-9A-F]+), (0x[0-9A-F]+)')

SERVER_POWER_ON_RE = re.compile(r'Status Code Available')
SERVER_POWER_OFF_RE = re.compile(r'SecSMI. S5 Trap')

# OS booted
RUNTIME_BLOCK_START_MARK = 'OSBootEvent = Success'
# SMM handler
SMM_BLOCK_MARK = 'SMM Error Handler Entry'
# SMBIOS data
SMMRC_BBLOCK_MARK = 'GenerateFruSmbiosData'

CLIENT_DESCRIPTION = """Yandex R&D Debug Log parser for Intel FFM DRAM Hard Error handlers"""
HELPS = {
    'source': 'source of test information',
    'tags': 'append tags to test result',
    'config': 'config file path (default machinegun.ini)',
    'mission': 'a list of activities to reach the goal',
    'verbose': 'enable verbose output',
    'disable_sending': 'disable API calls and e-mail sending',
}

NO_COMPONENT = """Component {model} not found in the benchmark database.
Please, create component with alias {model} in benchmark manually."""


OPTIONS = { 
    'base' : {
        'timeout' : (int, 600)
    },
    'report': {
        # notification options
        'api_url': (str, 'https://benchmark-test.haas.yandex-team.ru/api'),
        'smtp_relay': (str, 'outbound-relay.yandex.net'),
        'mail_to': (parse_list, [])
    },  
    'checks': {
        'check_poppulation' : (parse_bool, True),
        'check_frequency' : (parse_bool, True),
        'check_homogenity' : (parse_bool, True)
    },
    'node_configuration': {
        'por_ram_freq' : (int, 2666),
        'dimms_count' : (int, 24),
        'sockets_count' : (int, 2),
        'channels_count' : (int, 12),
        'dimm_per_channel' : (int, 2),
        'dimm_labels' : (str, 'MY81-EX0-Y3N_dimm_labels.yaml')
    },
    'mission': {
        'RMT': (bool, True),
        'STEP': (bool, True)
    },
    'RMT': {
        'repeats' : (int, 5),
        'guidelines' : (str, 'CascadeLake_DDR4_Margin_guidelines.yaml')
    },
    'STEP': {
    }
}


def tree():
    return defaultdict(tree)

def argument_parsing():
    """
    Parse and return command line arguments
    """
    parser = argparse.ArgumentParser(description=CLIENT_DESCRIPTION)
    parser.add_argument('source', help=HELPS['source'])
    parser.add_argument('-T', '--tags', help=HELPS['tags'])
    parser.add_argument('-c', '--config', help=HELPS['config'],
                        default=CONF_FILE)
    parser.add_argument('-v', '--verbose', help=HELPS['verbose'],
                        action='store_true')
    parser.add_argument('--disable-sending', help=HELPS['disable_sending'],
                        action='store_true', default=False)
    return parser.parse_args()

class BDSM():
    """
    BIOS Debug Serial Monitor
    """
    def __init__(self, data_source, conf, ram_info):
        self.mission = conf['mission']
        self.source = data_source
        self.ram_info = ram_info
        #print(json.dumps(self.environment['poppulation'], indent=2))

        self.data_source = None
        self.dbg_log_data = []
        self.processed_funcs = []
        self.mrc_fatal_error_catched = False
        self.first_run_flag = True

        if self.dbg_log_src_is_logfile():
            self.dbg_log_data = open(self.source)
        elif self.dbg_log_src_is_console():
            self.data_source = 'das'
            logger.debug('Waiting for data from direct attached serial console' + self.source + '...')
            # TODO: Make do not fumble the console
            self.dbg_log_data = dasc_data(self.source, 115200)
        elif self.dbg_log_src_is_sol():
            # TODO: Rewrite with context manager concept im mind
            self.data_source = 'sol'
    #        sol_output = list()
            try:
                logger.info('Trying initialize IPMI SOL session with ' + self.source + '...')
                sol_session = SOL(self.source)
                logger.info("SOL initiated!")
                try:
                    def sigterm_handler(sig, frame):
                        print('Ctrl+C is pressed! Session is terminating...')
                        sol_session.close()
                        sys.exit(0)
                    if signal.signal(signal.SIGINT, sigterm_handler):
                        logger.info("Signal SIGINT registered to carefully close SOL session")
                    logger.info('Waiting for data from SOL console ' + self.source + '...')
                    dbg_log_data = sol_session.get_data()
                except Exception as e:
                    print(e)
                    logger.error("Something goes wrong...")
                    sol_session.close()
            except Exception as e:
                print(e)
                logger.error("Can't get SOL data from " + self.source + " source.")

        self.dbg_block_processing_rules = {
                'InitFruStrings' : 'process_chassis_info',
                'DIMMINFO_TABLE' : 'process_dimm_info',
                'SOCKET_0_TABLE' : 'process_socket_info',
                'SOCKET_1_TABLE' : 'process_socket_info',
                'Rx Dq/Dqs Basic' : 'process_training_info',
                'MemTest' : 'process_mbist',
                'Corrected Memory Error' : 'process_smm_ce_handler'
        }


        # Goal testplan and processors dependencies rules
        # Base part:
        self.testplan = {
            'ram_conf_validator' : [ 'process_socket_info', 'process_dimm_info' ],
            'process_chassis_info' : [ 'console_data_dummy' ],
            'process_socket_info' : [ 'console_data_dummy' ],
            'process_dimm_info' : [ 'console_data_dummy' ]
        }
        for submission in self.mission.keys():
            if self.mission[submission]:
                submission = submission.lower()
                if submission == 'rmt':
                    self.rmt_guidelines = yaml.load(open(conf['RMT']['guidelines']), Loader=yaml.SafeLoader)
                    self.rmt = RMT(ram_info, self.rmt_guidelines)
                    submission_instance = self.rmt
                    self.dbg_block_processing_rules.update(self.rmt.dbg_block_processing_rules)
                elif submission == 'step':
                    self.step = STEP(ram_info)
                    submission_instance = self.step
                    self.dbg_block_processing_rules.update(self.step.dbg_block_processing_rules)
                self.testplan.update({'{0}.result_completeness'.format(submission): ['process_dimm_info']})
                self.testplan.update(submission_instance.testplan)
        self.testplan_set = dict((k, set(self.testplan[k])) for k in self.testplan)
#        print(self.testplan)
#        sys.exit(0)

        #self.dbg_block_processing_rules.update(test_instance.processing_rules)


    def dbg_log_src_is_console(self):
        try:
            if stat.S_ISCHR(os.stat(self.source).st_mode):
                logger.debug("Source of debug data is direct attached serial console")
                return True
        except Exception:
            return False

    def dbg_log_src_is_sol(self):
        logger.debug("Trying get date from IPMI host...")
        try:
            if os.system("ping6 -c 1 " + self.source + ">/dev/null") is 0:
                # TODO: Add check for sol info
                logger.debug("Source of debug data is IPMI SOL")
                return True
            else:
                return False
        except Exception:
            return False

    def dbg_log_src_is_logfile(self):
        if os.path.isfile(self.source) and os.path.getsize(self.source) > 0:
            logger.debug("Source of debug data is plain text file")
            return True

    def dasc_data(self, port, baudrate):
        """ Direct attached serial console """
        debug_console = serial.Serial(
            port=port,\
            baudrate=baudrate,\
            parity=serial.PARITY_NONE,\
            stopbits=serial.STOPBITS_ONE,\
            bytesize=serial.EIGHTBITS,\
            timeout=0)
        while True:
            yield debug_console.readline()
        debug_console.close()

    def console_data_dummy(self, dbg_log_block, dbg_block_name, socket_id):
        return False

    def process_chassis_info(self, dbg_log_block, dbg_block_name, socket_id):
        logger.info("Processing chassis info...")
        sys_vendor_re = re.compile(r'SystemManufacturer: UpdateStr: (.*)')
        product_name_re = re.compile(r' SystemProductName: UpdateStr: (.*)')
        inventory_re = re.compile(r'SystemSerialNumber: UpdateStr: ([0-9]*)')
        baseboard_vendor_re = re.compile(r'BaseBoardManufacturer: UpdateStr: (.*)')
        baseboard_model_re = re.compile(r'BaseBoardProductName: UpdateStr: (.*)')
        environment_regs = {
            'sys_vendor' : sys_vendor_re,
            'product_name' : product_name_re,
            'inventory' : inventory_re,
            'baseboard_vendor' : baseboard_vendor_re,
            'baseboard_model' : baseboard_model_re
            }

        for line in dbg_log_block:
            for k in environment_regs.keys():
                match = re.search(environment_regs[k], line)
                if match is not None:
                    environment[k] = match.group(1)
                    break

        if environment['inventory'] and environment['baseboard_model']:
            logger.debug(environment)
            logger.info("...success")
            if test_instance:
                test_instance.result.environment = environment
            return True

    def process_socket_info(self, dbg_log_block, dbg_block_name, socket_id):
        logger.info("Processing Socket info table...")
	dimms_info = tree()
        dimm_params = ['vendor', 'dram_vendor', 'rcd', 'organisation', 'form_factor', 'freq', 'prod_week', 'pn', 'sn']
        header = ''
        param_id = 0
        socket_id = str(socket_id)
        for line in dbg_log_block:
            if line.startswith('=' * 10) or line.startswith('-' * 10)\
                or line.startswith('BDX') or line.startswith('CLX'):
                continue
            line_stripped = ([v.strip() for v in line.split('|')])
            if line_stripped[0] == 'S':
                header = line_stripped
                continue
            if line_stripped[0] and line_stripped[0].isdigit():
                dimm_id = str(line_stripped[0])
                param_id = 0
            socket_dict = {}
            channel_dict = {}
            for index, channel_id_raw in enumerate(header[1:-1]):
		channel_id = [s for s in channel_id_raw.split() if s.isdigit()].pop()
                if len(line_stripped[1:-1]) >= index + 1:
                    if len(dimm_params) > param_id:
                        if len(line.split(':')) > 2:
                            value = line_stripped[index+1].split(':')[-1].strip()
                        else:
                            value = line_stripped[index+1].strip()
                        if dimm_params[param_id] == 'freq':
                            speed_value_composed = line_stripped[index+1].split()
                            if len(speed_value_composed) == 2:
                                dimms_info[socket_id][channel_id][dimm_id]['timings'] = speed_value_composed[-1]
                                value = speed_value_composed[0]

			#print(json.dumps(self.ram_info.memory_subsytem_events, indent=2))
			#print(self.ram_info.memory_subsytem_events)
                        dimms_info[socket_id][channel_id][dimm_id][dimm_params[param_id]] = value
                    else:
                        continue
            param_id += 1
        print(json.dumps(dimms_info, indent=2))

    def process_dimm_info(self, dbg_log_block, dbg_block_name, socket_id):
        logger.info("Processing DIMM info table...")
        ram_info_buffer = []
        for line in dbg_log_block:
            if line.startswith('=' * 10):
                continue
            line_splitted = ([v.strip() for v in line.split('|')])

            if line.startswith(' ' * 10):
                header = line_splitted
                logger.debug("DIMM info header:" + str(header))
                continue

            ram_info_buffer.append(line_splitted)
            for index, socket_id in enumerate(header[1:]):
                socket_dict = {}
                #logger.info("Socket:" + str(index) + ' ' + str(socket_id))
                for line in ram_info_buffer[:-1]:
                     if len(line) >= index + 2:
                          value = line[index+1].strip()
                          if not value or value == 'N/A':
                               continue
                          if line[0].startswith('Ch'):
                              channel_dict = {}
                              channel_raw, param = line[0].split()
                              channel_id = re.sub(r'Ch([0-5])', r"Channel \1", channel_raw)
                              ram_info[socket_id][channel_id][param] = value
                          else:
                              key = line[0]
                              ram_info[socket_id][key] = value
        return ram_info['System']['DDR Freq'].isdigit()

    def ram_conf_validator(self):
        logger.debug('Checking RAM info completeness...')
        node_configuration = conf['node_configuration']
        ram_config_status = {}
        ec = None

    #    logger.debug("RAM_INFO")
    #    logger.debug(json.dumps(ram_info, indent=2))
        # TODO: rewrite to list comprehension?
        for s, sconf in ram_info.items():
            if s.startswith('Socket'):
                components_counter['sockets_count'] += 1
                for c, chconf in sconf.items():
                    if c.startswith('Channel'):
                        components_counter['channels_count'] += 1
                        for d, rdimm in chconf.items():
                            if isinstance(rdimm, dict) and rdimm['DIMM vendor'] != 'Not installed':
                                components_counter['dimms_count'] += 1
                                size, organisation = re.sub(r'([0-9]+)GB\((.*)\)', r"\1,\2", rdimm['Organisation']).split(",")
                                prod_week_norm = re.sub(r'ww([0-9][0-8]) 20([0-3][0-9])', r"\2\1", rdimm['Prod. week'])
                                model = '{}_{}'.format(rdimm['PN'], rdimm['RCD vendor'].upper())
                                slot = dimm_labels[str('{}.{}.{}'.format(s.split()[-1],c.split()[-1],d.split()[-1]))]
                                ram_info[s][c][d] = {
                                    'type': 'RAM',
                                    'pn': rdimm['PN'],
                                    'model': model,
                                    'prod date': prod_week_norm,
                                    'serial': rdimm['SN'],
                                    'vendor': rdimm['DIMM vendor'],
                                    'dram vendor': rdimm['DRAM vendor'],
                                    'size': size,
                                    'organisation': organisation.replace(" ", ""),
                                    'form factor': rdimm['Form factor'],
                                    'speed': rdimm['Freq'],
                                    'timings': rdimm['Timings'],
                                    'slot': slot
                                }

        #logger.debug(json.dumps(components_counter, indent=2))

        if conf['checks']['check_homogenity']:
            # Check that all RDIMMs are same
            ram_config_status['homogeneity'] = all(components[0]['model'] == dimm['model'] for dimm in components[1:])
            if not ram_config_status['homogeneity']:
                ram_rdimm_pns_set = set(dimm['model'] for dimm in components)
                logger.error("Wrong RAM config: RDIMMs are not the same! Founded: " + ' '.join(ram_rdimm_pns_set))

        if conf['checks']['check_poppulation']:
            # Check DIMM poppulation
            # TODO: add function to validate poppulation if DIMM less than 24 pcs
            ram_config_status['poppulation'] = all(components_counter[x] == node_configuration[x] for x in components_counter.keys())
            if not ram_config_status['poppulation']:
                logger.error("DIMM poppulation is wrong:\n" + json.dumps(components_counter, indent=2) + "\n, instead POR:\n" + json.dumps(node_configuration, indent=2))

        if conf['checks']['check_frequency']:
            # Check frequency
            ddr_freq = int(ram_info['System']['DDR Freq'].lstrip('DDR4-'))
            if ddr_freq == node_configuration['por_ram_freq']:
                ram_config_status['ddr_frequency'] = True
            else:
                ram_config_status['ddr_frequency'] = False
                logger.error('Wrong RAM config: RAM initializated at ' + str(ddr_freq) + ' MT/s instead of ' + str(node_configuration['por_ram_freq']) + ' MT/s')

        if all(ram_config_status[s] for s in ram_config_status.keys()):
            #logger.info('Founded ' + components.values['vendor'] + ' ' + components.values['model'])
            pass
        else:
            sys.exit(ec)

        if test_instance:
            test_instance.result.component = components

        return ram_config_status

    def parse_memtest_failed(self, data_buffer):
        LOCATION_KEYS = {
            'socket': '(?P<socket>[01])',
            'channel': '(?P<channel>\d|FF)',
            'dimm': '(?P<dimm>\d|FF)',
        }

        ERR_MSG = (r'N{socket}\.C{channel}\.D{dimm}(\.R\d)?(\.S\d\d)?:\s*'
                   '(ERROR:|FAULTY_PARTS_TRACKING:)?\s+(?P<message>[^:!]+?)\s*!*$')
        ERR_MSG_RE = re.compile(ERR_MSG.format(**LOCATION_KEYS))
        for line in data_buffer:
            #rank, line.split(':')
            #match = ERR_MSG_RE.search(line)
            failed_rank_match = re.match(r'^N([0-9]).C([0-6]).D([0-3]).R[0-9]: MemTest Failure!', line)
            #if match:
            if failed_rank_match:
                fields = match.groupdict()
                location = LOC_TMPL.format(**fields)
                msg = fields['message'].strip()
                self.err_message[location] = (msg, self.stage)

    #    def process_checkpoint(self, line):
    #        checkpoint_match = CHECKPOINT_RE.search(line)
    #        if checkpoint_match:
    #            self.checkpoint = Checkpoint(**checkpoint_match.groupdict())
    #        if self.checkpoint in self.parsed_checkpoints:
    #            handler = self.parsed_checkpoints[self.checkpoint]
    #            handler(line)


    def parse_enhanced_warning(self, data_buffer, timestamp):
        warn_dict = {}
        def fill_warn_dict(line):
            key, value = re.split('= |: |\s(?=\S*$)', line, maxsplit=1)
            warn_dict[key.lower().strip(' ,').replace(' ','_').lower()] = value

        #enhanced_warning = re.match(r'Enhanced warning of type \([0-9]\) logged:.*', data_buffer)
        enhanced_warning = re.match(r'Enhanced warning of type ([0-9]) logged:', data_buffer)
        if enhanced_warning:
            logger.warning('Founded Enhanced warning block!')
            warn_type = int(enhanced_warning.group(1))
            data_buffer_splitted = data_buffer.splitlines()
            data_buffer_splitted.remove(enhanced_warning.group(0))
            logger.debug("Parsing the common part...")
            for line in data_buffer_splitted:
                #logger.debug("Line(" + str(data_buffer_splitted.index(line)) + "): " + line) 
                if 'Warning Code' in line:
                    # Flush processed lines
                    data_buffer_splitted[data_buffer_splitted.index(line)] = ''
                    for l in line.split(', '):
                        fill_warn_dict(l.strip(' ,'))
                    continue
                #key, value = re.split('= |: |\s(?=\S*$)', data_buffer_splitted, maxsplit=1)
                fill_warn_dict(line)
                data_buffer_splitted[data_buffer_splitted.index(line)] = ''
                if 'Socket' in line:
                    break
            logger.debug("Parsing specific part...")
            for line in data_buffer_splitted:
                if not line.strip():
                    continue
                if warn_type == 5:
                    #logger.info('Warning type: ' + str(warn_type) + ' (RAM issue)')
                    if 'Dq bytes' in line:
                        print(line.split('x'))
                        # TODO: determine DQ line from node/channel/dimm/!device!/bit inputs
                        # Need to parse START_DATA_TX_DQ_PER_BIT to analyze type of failure
                        # or get from STEP output see: ITDC-202731, ITDC-202681
                        continue
                    fill_warn_dict(line)

            #slot = self.dimm_labels[warn_dict['socket'], warn_dict['channel'], warn_dict['dimm']]
            error_event_data = {}
            warn_dict['data_provider'] = 'MBIST'
            warn_dict['logger'] = 'BSDM'
            warn_dict['logger_version'] = parser_version
            print(json.dumps(warn_dict, indent=2))
            warn_dict = self.ram_info.log_dimm_error_event(warn_dict)
            logger.debug("Unused data:")
            print(json.dumps(warn_dict, indent=2))

    def process_mbist(self, dbg_log_block, dbg_block_name, socket_id):
        logger.info('Processing MemTest...')

        self.dimm_labels = ram_info.sys_conf['poppulation']
        #print(dbg_log_block)
        dbg_log_block_text = "\n".join(dbg_log_block)
        mbist_block = re.compile("(?<!^)\s+(?=.*: MemTest Failure!)(?!.\s)").split(dbg_log_block_text)
        enchanced_warning = re.compile("(?<!^)\s+(?=Enhanced warning of type [0-9] logged:.*)(?!.\s)").split(dbg_log_block_text)
        timestamp = time.time()
        if mbist_block:
            for memfail in mbist_block:
                mbist_part, warn_part = memfail.split('\n\n')
                self.parse_enhanced_warning(warn_part, timestamp)
        elif enchanced_warning:
            parse_enhanced_warning(warn_part)
        else:
            logger.info("Memory test passed without any issues")

    def process_training_info(self, dbg_log_block, dbg_block_name, socket_id):
        for line in dbg_log_block:
            failed_rank_match = re.match(r'.*(N[0-9].C[0-6].D[0-3].R[0-9]).S[01][0-9]: Failed RdDqDqs', line)
            if failed_rank_match:
                failed_device = failed_rank_match.group(1)
                print('Founded training error ' + failed_device)
                ident_dimm(failed_device,'critical')

    def process_smm_ce_handler(self, dbg_log_block, dbg_block_name, socket_id):
        logger.info("Processing Runtime SMM handlers output...")
    #    print(dbg_log_block)
        for line in dbg_log_block:
            failed_rank_match = re.match(r'Last Err Info Node=([0-9]) ddrch=([0-9]] dimm=([0]) rank=([1])', line)
            if failed_rank_match:
                failed_device = failed_rank_match.group(1)
                print('Founded training error ' + failed_device)
                ident_dimm(failed_device,'critical')

    def resolve_dependecies(self):
        #import pdb; pdb.set_trace()
        print("TESTPLAN_GEN_DICT: " + str(self.testplan_set))
        logger.debug("Current processed func: " + str(set(self.processed_funcs)))
        # values not in keys (items without dep)
        funcs_wo_deps=set(i for v in self.testplan_set.values() for i in v)-set(self.testplan_set.keys())

        for p in self.processed_funcs:
            for k in self.testplan_set.keys():
                if k == p:
                    logger.debug("Processed func set:" + str(self.testplan_set[k]))
                    self.testplan_set.pop(k, None)


#        print("ITEMS_WO_DEPS_VALUES: " + str(funcs_wo_deps) + " TYPE: " + str(type(funcs_wo_deps)))
        # and keys without value (items without dep)
        funcs_wo_deps.update(k for k, v in self.testplan_set.items() if not v)
#        print("ITEMS_WO_DEPS_KEYS: " + str(funcs_wo_deps))
#        print("ITEMS_TO_DO: " + str(funcs_wo_deps))
#        print("PROCESSED_FUNCS: " + str(self.processed_funcs))
#        print("ITEMS_TO_DO(STILL): " + str(funcs_wo_deps) + "; LENGHT: " + str(len(funcs_wo_deps)))
        self.testplan_set=dict(((k, set(v)-set(self.processed_funcs)) for k, v in self.testplan_set.items() if v))
#        print("TESTPLAN_GEN_DICT_CLEANED: " + str(testplan_set))
        if len(funcs_wo_deps) != 0 and next(iter(funcs_wo_deps)) is not None:
            for supplementary_func in funcs_wo_deps:
                print("SUPPLEMENTARY_FUNC:" + supplementary_func)
                if self.exec_func_by_name(supplementary_func, None, None, None ):
                    logger.debug(str(supplementary_func) + " just passed")
                    self.processed_funcs.append(supplementary_func)

    def exec_func_by_name(self, func_name, block_buffer, block_name, socket_id):
        print("FUNC NAME:")
        print(func_name)
        print(type(func_name))
        if len(func_name.split('.')) == 2:
            class_name, func_name = func_name.split('.')
            klass = eval('self.' + class_name)
        else:
            klass = self
        func = getattr(klass, func_name, None)
        if func:
            return func(self.block_buffer[block_name], block_name, socket_id)
        else:
            return False
        

    def parse_debug_log(self):
        """
        Parse Serial Debug Log for RDIMM/DRAM errors and call specific handlers 
        """
        func_counter = defaultdict(int)
        self.block_buffer = defaultdict(list)
        block_processing_queue = []
        mrc_block_name = ''
        current_processing_block_name = ''
        current_processing_block_ended = False

        def wait_data(timeout):
            if self.data_source in ('sol', 'das'):
                #logger.info('.', end='')
                print('.')
                time.sleep(1)

        logger.info('Parsing data from source ' + self.source + '...')

        for line in self.dbg_log_data:
    #        if not dbg_log_data:
    #            if wait_data(conf['base']['timeout']):
    #                continue
    #            else:
    #                break

    #        try:
    #            if sol_session.wait_for_rsp(timeout=600):
    #                print('There is must be some data here...')
    #                line = sol_output.getvalue()
    #                if not line:
    #                    print('PASS')
    #                    continue
    #                else:
    #                    print("GET called VALUE: " + str(line) + str(len(line)))
    #    #            line = dbg_log_data.pop()
    #    #            print("POPPED valie: " + line)
    #        except Exception:
    #            print('EXCEPTION!')
    #            print(dbg_log_data)
    #            time.sleep(3)
    #            continue
            ansi_escape = re.compile(r'\x1B[@-_][0-?]*[ -/]*[@-~]')
            line = ansi_escape.sub('', line).rstrip('\r\n')

            dbg_block_name = ''
            if SERVER_POWER_ON_RE.match(line):
                if self.first_run_flag:
                    first_run_flag = False
                    logger.info("Server just powered on. Initialized new job session.")
                else:
                    logger.info("Server just restarted. #TODO: Check reason:")
                    # TODO 1. Check reason of restart

            if SERVER_POWER_OFF_RE.match(line):
                logger.info("Server just powered off. Job session finished.")
                # TODO flush buffers and may be send the job result

            if MRC_ACPI_START_RE.match(line):
                dbg_block_name = MRC_ACPI_START_RE.match(line).group(1)
                logger.debug("Founded ACPI BIOS block: " + dbg_block_name)
                dbg_block_end_re = MRC_ACPI_END_RE

            if MRC_BBLOCK_START_RE.match(line):
                dbg_block_name = MRC_BBLOCK_START_RE.match(line).group(1)
                logger.debug("Founded AMI BIOS base block: " + dbg_block_name)
                dbg_block_end_re = MRC_BBLOCK_END_RE

            if MRC_iMC_BLOCK_START_RE.match(line):
                dbg_block_name = MRC_iMC_BLOCK_START_RE.match(line).group(1)
                logger.debug("Founded MRC block: " + dbg_block_name)
                dbg_block_end_re = MRC_iMC_BLOCK_END_RE

            if MRC_SMM_BLOCK_START_RE.match(line):
                dbg_block_name = MRC_SMM_BLOCK_START_RE.match(line).group(1)
                logger.debug("Founded AMI BIOS SMM block: " + dbg_block_name)
                dbg_block_end_re = MRC_SMM_BLOCK_END_RE

            if dbg_block_name:
                try:
                    block_processor_name = self.dbg_block_processing_rules[dbg_block_name]
                    block_processing_queue.append({dbg_block_name:dbg_block_end_re})
    #                print("ADDED BLOCK: " + str(block_processing_queue))
                except KeyError as e:
                    pass

            else:
                if block_processing_queue:
                    current_processing_block_ended = False
                    if MRC_FATAL_ERROR_RE.match(line):
                        mrc_fatal_error_catched = True
                    current_processing_block_name = ''.join(block_processing_queue[-1].keys())
                    print("CURRENT_PROC_BLOCK_NAME: " + str(current_processing_block_name))
                    current_processing_block_end_re = block_processing_queue[-1][current_processing_block_name]
    #                print(current_processing_block_end_re.pattern)
                    founded_stop_block_mark = current_processing_block_end_re.match(line)
                    if founded_stop_block_mark:
                        if founded_stop_block_mark.group(1) == current_processing_block_name:
                            current_processing_block_ended = True
                    if self.mrc_fatal_error_catched or current_processing_block_ended:
                        if self.dbg_block_processing_rules[current_processing_block_name]:
                            func_name = self.dbg_block_processing_rules[current_processing_block_name]
                            print("CURRENT_FUNC_NAME: " + str(func_name))
                            socket_id = re.sub(r'\D', "", current_processing_block_name)
                            if not socket_id:
                                socket_id = None
                            #try:
                            print("BUFFER:")
                            print(self.block_buffer[current_processing_block_name])
                            self.exec_func_by_name(func_name, self.block_buffer[current_processing_block_name], current_processing_block_name, socket_id)
                            self.processed_funcs.append(func_name)
#                           print("BEFORE: " + str(block_processing_queue[-1].keys()))
                            block_processing_queue.pop()
                            mrc_fatal_error_catched = False
#                            except Exception, e:
#                                #logger.info("Failed to process " + str(current_processing_block_name) + " with func.: " + str(func) + ":" )
#                                logger.info("Failed to process {} with func {}, raised: {}".format(current_processing_block_name, func_name, e))
#                                pass
                            # Check for possibility to run supplimentary functions and execute them if possible
                            if self.testplan.keys():
                                self.resolve_dependecies()
                            else:
                                break
                    else:
                        self.block_buffer[current_processing_block_name].append(line)

        n = 0
        if self.testplan_set:
            logger.debug("Last chance to reach the goal: " + str(self.testplan_set))
            self.testplan_set.pop('console_data_dummy', None)
            while self.testplan_set:
                self.resolve_dependecies()
                n += 1
                if n > 10:
                    logger.error("Failed! Not enough data for accomplish the goals!")
                    logger.error(self.testplan_set.keys())
                    break

if __name__ == '__main__':
    args = argument_parsing()
    conf = Conf(OPTIONS, args.config, log=False)

    ram_info = MemorySubsytemEventsLogger('MY81-EX0-Y3N')
    data_source = args.source

    MRC_parser = BDSM(data_source, conf, ram_info)
    MRC_parser.parse_debug_log()

# vim: tabstop=8 softtabstop=0 expandtab shiftwidth=4 smarttab
