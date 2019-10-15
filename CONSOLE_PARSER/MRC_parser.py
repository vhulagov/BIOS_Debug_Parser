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

import serial
import tty
import termios

from pyghmi.ipmi import console as ipmi_console

from rmt import RMT
from step import STEP

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

# Exit error codes
ERROR_CODES = {
    'homogeneity' : 102,
    'poppulation' : 103,
    'ddr_frequency' : 104,
    'data_missing' : 120
}

rmt_instance = None
components = {}
environment = {}

CONF_FILE = 'MRC_parser.ini'

# Led highlighting is turned off by default
LED_EXISTENCE = False

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
    'goal': 'the final goal of activity',
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
    'goal': {
        'name' : (str, 'RMT'),
    },
    'RMT': {
        'repeats' : (int, 5),
        'guidelines' : (str, 'CascadeLake_DDR4_Margin_guidelines.yaml')
    },
    'STEP': {
    }
}

dimm_params = ['DIMM vendor', 'DRAM vendor', 'RCD vendor', 'Organisation', 'Form factor', 'Freq', 'Prod. week', 'PN', 'SN']

def tree():
    return defaultdict(tree)

ram_info = tree()

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

def dbg_log_src_is_console(dbg_log_data_source):
    try:
        if stat.S_ISCHR(os.stat(dbg_log_data_source).st_mode):
            logger.debug("Source of debug data is direct attached serial console")
            return True
    except Exception:
        return False

def dbg_log_src_is_sol(dbg_log_data_source):
    logger.debug("Trying get date from IPMI host...")
    try:
        if os.system("ping6 -c 1 " + dbg_log_data_source + ">/dev/null") is 0:
            # TODO: Add check for sol info
            logger.debug("Source of debug data is IPMI SOL")
            return True
        else:
            return False
    except Exception:
        return False

def dbg_log_src_is_logfile(dbg_log_data_source):
    if os.path.isfile(dbg_log_data_source) and os.path.getsize(dbg_log_data_source) > 0:
        logger.debug("Source of debug data is plain text file")
        return True

class SOL():
    def __init__(self, bmc):
        self.bmc = bmc
        self.sol_data = list()
        print("BMC host is " + str(self.bmc))
        self.sol_session = ipmi_console.Console(bmc=self.bmc, userid='ADMIN', password='ADMIN',
                               iohandler=self.putdata, force=True)
        print(dir(self.sol_session))
  
    def putdata(self, data):
        print("Put the following data to SOL buffer: " + str(data))
        self.sol_data.append(data)
 
    def getdata(self):
        line = ''
        while True:
            if self.waitdata():
                print('There is must be some data here...')
                print(self.sol_data)
                if self.sol_data:
                    print('pop some existence data from SOL buffer')
                    line = self.sol_data.pop()
                else:
                    print('SOL data buffer is empty: return empty string')
                    break
            else:
                print('No payload from SOL')
                break
            yield line
 
    def waitdata(self):
        return not self.sol_session.wait_for_rsp(timeout=600)

    def close(self):
        return self.sol_session.close()


def das_data(port, baudrate):
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

def init_leds():
    # For LED highlighting using PCA9685
    import smbus
    import pca9685pw

    # Settings for PCA9685
    PCA9685_I2C_BUS = 8 # bus id
    PCA9685_I2C_ADDRESS = 0b1000000 # address pins [1][A5][A4][A3][A2][A1][A0]
    LED_PWM_FREQ = 600 # hertz 64 recomended for Servos

    # For single socket platform
    LED_DIMM_MATCH_TABLE = {
        '0.0.0' : 0,
        '0.0.0' : 0,
        '0.0.1' : 2,
        '0.0.1' : 2,
        '0.1.0' : 4,
        '0.1.0' : 4,
        '0.1.1' : 6,
        '0.1.1' : 6,
        '0.2.0' : 8,
        '0.2.0' : 8,
        '0.2.1' : 10,
        '0.2.1' : 10,
        '0.3.0' : 12,
        '0.3.0' : 12,
        '0.3.1' : 14,
        '0.3.1' : 1
    }

    pwm = pca9685pw.Pca9685pw(8,PCA9685_I2C_BUS,PCA9685_I2C_ADDRESS)
    pwm.defaultAddress = PCA9685_I2C_ADDRESS
    pwm.setFrequency(LED_PWM_FREQ)
    pwm.reset()
    LED_EXISTENCE = True
    for i in range(0,16):
      pwm.setFullOff(i)

def ident_dimm(device_rank, state):
    global LED_EXISTENCE
    if LED_EXISTENCE:
        severity_mapping = {
            'critical' : 100,
            'warning' : 20,
            }
        led_id = LED_DIMM_MATCH_TABLE[device_rank]
        if severity_mapping[state]:
            pwm = pca9685pw.Pca9685pw(8,PCA9685_I2C_BUS,PCA9685_I2C_ADDRESS)
            pwm.setPercent(led_id,severity_mapping[state])
        else:
            print("Can't find leds for highlighting failed DIMM")

def console_data_dummy():
    return False

def process_chassis_info(dbg_log_block, dbg_block_name, socket_id):
    global environment
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

def process_socket_info(dbg_log_block, dbg_block_name, socket_id):
    logger.info("Processing Socket info table...")
    global ram_info
    header = ''
    param_id = 0
    socket_id_phrase = "Socket " + str(socket_id)
    for line in dbg_log_block:
        if line.startswith('=' * 10) or line.startswith('-' * 10)\
            or line.startswith('BDX'):
            continue
        line_stripped = ([v.strip() for v in line.split('|')])
        if line_stripped[0] == 'S':
            header = line_stripped
            continue
        if line_stripped[0] and line_stripped[0].isdigit():
            cs_id = 'Dimm ' + str(line_stripped[0])
            param_id = 0
        socket_dict = {}
        channel_dict = {}
        for index, channel_id in enumerate(header[1:-1]):
            if len(line_stripped[1:-1]) >= index + 1:
                if len(dimm_params) > param_id:
                    if len(line.split(':')) > 2:
                        value = line_stripped[index+1].split(':')[-1].strip()
                    else:
                        value = line_stripped[index+1].strip()
                    if dimm_params[param_id] == 'Freq':
                        speed_value_composed = line_stripped[index+1].split()
                        if len(speed_value_composed) == 2:
                            ram_info[socket_id_phrase][channel_id][cs_id]['Timings'] = speed_value_composed[-1]
                            value = speed_value_composed[0]

                    ram_info[socket_id_phrase][channel_id][cs_id][dimm_params[param_id]] = value
                else:
                    continue
        param_id += 1

def process_dimm_info(dbg_log_block, dbg_block_name, socket_id):
    logger.info("Processing DIMM info table...")
    global ram_info
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

def ram_conf_validator():
    logger.debug('Checking RAM info completeness...')
    global ERROR_CODES
    global ram_info
    global conf
    global components
    node_configuration = conf['node_configuration']
    components_counter = {
        'sockets_count' : 0,
        'channels_count' : 0,
        'dimms_count' : 0
    }
    ram_config_status = {}
    ec = None

    dimm_labels = yaml.load(open(conf['node_configuration']['dimm_labels']), Loader=yaml.BaseLoader)
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
                            components[slot] = {
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
            ec = ERROR_CODES['homogeneity']

    if conf['checks']['check_poppulation']:
        # Check DIMM poppulation
        # TODO: add function to validate poppulation if DIMM less than 24 pcs
        ram_config_status['poppulation'] = all(components_counter[x] == node_configuration[x] for x in components_counter.keys())
        if not ram_config_status['poppulation']:
            logger.error("DIMM poppulation is wrong:\n" + json.dumps(components_counter, indent=2) + "\n, instead POR:\n" + json.dumps(node_configuration, indent=2))
            ec = ERROR_CODES['poppulation']

    if conf['checks']['check_frequency']:
        # Check frequency
        ddr_freq = int(ram_info['System']['DDR Freq'].lstrip('DDR4-'))
        if ddr_freq == node_configuration['por_ram_freq']:
            ram_config_status['ddr_frequency'] = True
        else:
            ram_config_status['ddr_frequency'] = False
            logger.error('Wrong RAM config: RAM initializated at ' + str(ddr_freq) + ' MT/s instead of ' + str(node_configuration['por_ram_freq']) + ' MT/s')
            ec = ERROR_CODES['ddr_frequency']

    if all(ram_config_status[s] for s in ram_config_status.keys()):
        #logger.info('Founded ' + components.values['vendor'] + ' ' + components.values['model'])
        pass
    else:
        sys.exit(ec)

    if test_instance:
        test_instance.result.component = components

    return ram_config_status

def process_mbist(dbg_log_block, dbg_block_name, socket_id):
    global conf
    logger.info('Processing MemTest...')
    dimm_labels = yaml.load(open(conf['node_configuration']['dimm_labels']), Loader=yaml.BaseLoader)
    def parse_enhanced_warning(type):
        if type == 5:
            logger.error('Warning type: ' + str(type) + '. Founded memory issue'
        failed_rank_match = re.match(r'N([0-9]).C([0-6]).D([0-3]).R[0-9]: MemTest Failure!', line)
        if failed_rank_match:
            #failed_device = ''.join(e for e in failed_rank_match.group(1) if e.isalnum())
            #failed_device = ''.join(filter(str.isalnum, failed_rank_match.group(1)))
            failed_device = dimm_labels[str('.'.join(failed_rank_match.group(1,2,3)))]
            logger.error('Founded DQ error in ' + failed_device)
    sys.exit(0)
            #ident_dimm(failed_device,'warning')
    for line in dbg_log_block:
        print(line)
        enchanced_warning = re.match(r'Enhanced warning of type \([0-9]+\) logged:', line)
        if enchanced_warning:
            warn_type = int(enchanced_waring.group(1))



        
def process_training_info(dbg_log_block, dbg_block_name, socket_id):
    for line in dbg_log_block:
        failed_rank_match = re.match(r'.*(N[0-9].C[0-6].D[0-3].R[0-9]).S[01][0-9]: Failed RdDqDqs', line)
        if failed_rank_match:
            failed_device = failed_rank_match.group(1)
            print('Founded training error ' + failed_device)
            ident_dimm(failed_device,'critical')

def process_smm_ce_handler(dbg_log_block, dbg_block_name, socket_id):
    logger.info("Processing Runtime SMM handlers output...")
#    print(dbg_log_block)
    for line in dbg_log_block:
        failed_rank_match = re.match(r'Last Err Info Node=([0-9]) ddrch=([0-9]] dimm=([0]) rank=([1])', line)
        if failed_rank_match:
            failed_device = failed_rank_match.group(1)
            print('Founded training error ' + failed_device)
            ident_dimm(failed_device,'critical')

def parse_debug_log(args):
    global test_instance
    global conf
    global data_source
    global dbg_log_data
    # TODO: rewrite to class?
    """
    Parse Serial Debug Log for RDIMM/DRAM errors and call specific handlers 
    """
    #import pdb; pdb.set_trace()
    test_configuration = []
    tags = {}
    testplan = defaultdict(list)

#    global rmt_dblock_counter
#    rmt_dblock_counter = defaultdict(int)
#    rmt_data_required = defaultdict(int)
    test_instance = {}
    step_instance = {}

    processed_funcs = []
    func_counter = defaultdict(int)
    block_buffer = defaultdict(list)
    block_processing_queue = []
    mrc_block_name = ''
    mrc_fatal_error_catched = False
    current_processing_block_ended = False

    if conf['goal']['name'] == 'RMT':
        test_instance = RMT(args, conf, ram_info, BasicTestResult(conf, conf['goal']['name'], components))
    if conf['goal']['name'] == 'STEP':
        test_instance = STEP(args, conf, ram_info, BasicTestResult(conf, conf['goal']['name'], components))

    if dbg_log_src_is_logfile(args.source):
        dbg_log_data = open(args.source)
    if dbg_log_src_is_console(args.source):
        data_source = 'das'
        logger.debug('Waiting for data from direct attached serial console' + args.source + '...')
        # TODO: Make do not fumble the console
        dbg_log_data = das_data(args.source, 115200)
    if dbg_log_src_is_sol(args.source):
        data_source = 'sol'
#        global sol_output
#        sol_output = list()
        try:
            logger.info('Trying initialize IPMI SOL session with ' + args.source + '...')
            sol_session = SOL(args.source)
            logger.info("SOL initiated!")
            try:
                def sigterm_handler(sig, frame):
                    print('You pressed Ctrl+C!')
                    sol_session.close()
                    sys.exit(0)


                if signal.signal(signal.SIGINT, sigterm_handler):
                    logger.info("Signal SIGINT registered to carefully close SOL session")

#                import atexit
#                atexit.register(exit_handler)

                logger.info('Waiting for data from SOL console ' + args.source + '...')
                dbg_log_data = sol_session.getdata()
            except Exception as e:
                print(e)
                logger.error("Something goes wrong...")
                sol_session.close()
        except Exception as e:
            print(e)
            logger.error("Can't get SOL data from " + args.source + " source.")

    dbg_block_processing_rules = { 
            'InitFruStrings' : process_chassis_info,
            'DIMMINFO_TABLE' : process_dimm_info,
            'SOCKET_0_TABLE' : process_socket_info,
            'SOCKET_1_TABLE' : process_socket_info,
            'Rx Dq/Dqs Basic' : process_training_info,
            'MemTest' : process_mbist,
            'Corrected Memory Error' : process_smm_ce_handler
    }
    if test_instance:
        dbg_block_processing_rules.update(test_instance.processing_rules())

    # Goal testplan and processors dependencies rules
    # Base part:
    testplan = {
        ram_conf_validator : [ process_socket_info, process_dimm_info ],
        #process_chassis_info : [ console_data_dummy ],
        process_socket_info : [ console_data_dummy ],
        process_dimm_info : [ console_data_dummy ]
    }
    if test_instance:
        testplan.update(test_instance.testplan())

    dbg_block_processing_rules.update(test_instance.processing_rules())
    #testplan_set = dict((globals()[k], set(testplan[globals()[k]])) for k in testplan)
    #testplan_set = dict((eval(k), set(testplan[eval(k)])) for k in testplan)

    testplan_set = dict((k, set(testplan[k])) for k in testplan)

    def resolve_dependecies(testplan_set, processed_funcs):
        #import pdb; pdb.set_trace()
        #print("TESTPLAN_GEN_DICT: " + str(testplan_set))
        #logger.debug("Current processed func: " + str(set(processed_funcs)))
        # values not in keys (items without dep)
        funcs_wo_deps=set(i for v in testplan_set.values() for i in v)-set(testplan_set.keys())

        for p in processed_funcs:
            for k in testplan_set.keys():
                if k == p:
                    logger.debug("Processed func set:" + str(testplan_set[k]))
                    testplan_set.pop(k, None)


#        print("ITEMS_WO_DEPS_VALUES: " + str(funcs_wo_deps) + " TYPE: " + str(type(funcs_wo_deps)))
        # and keys without value (items without dep)
        funcs_wo_deps.update(k for k, v in testplan_set.items() if not v)
#        print("ITEMS_WO_DEPS_KEYS: " + str(funcs_wo_deps))
#        print("ITEMS_TO_DO: " + str(funcs_wo_deps))
#        print("PROCESSED_FUNCS: " + str(processed_funcs))
#        print("ITEMS_TO_DO(STILL): " + str(funcs_wo_deps) + "; LENGHT: " + str(len(funcs_wo_deps)))
        testplan_set=dict(((k, v-set(processed_funcs)) for k, v in testplan_set.items() if v))
        processed_funcs = []
#        print("TESTPLAN_GEN_DICT_CLEANED: " + str(testplan_set))
        if len(funcs_wo_deps) != 0 and next(iter(funcs_wo_deps)) is not None:
            for supplementary_func in funcs_wo_deps:
                if supplementary_func():
                    logger.debug(str(supplementary_func) + " just passed")
                    processed_funcs.append(supplementary_func)
        return testplan_set, processed_funcs

    def wait_data(timeout):
        global data_source
        if data_source in ('sol', 'das'):
            #logger.info('.', end='')
            print('.')
            time.sleep(1)
        

    logger.info('Parsing data from source ' + args.source + '...')

#    while True:
    for line in dbg_log_data:
#        if not dbg_log_data:
#            if wait_data(conf['base']['timeout']):
#                continue
#            else:
#                break
        #print('TYPE: ' + str(type(dbg_log_data)))
        #print('DATA: ' + str(dbg_log_data))

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
#        print(line)
        ansi_escape = re.compile(r'\x1B[@-_][0-?]*[ -/]*[@-~]')
        line = ansi_escape.sub('', line).rstrip('\r\n')

        dbg_block_name = ''

        if MRC_ACPI_START_RE.match(line):
            dbg_block_name = MRC_ACPI_START_RE.match(line).group(1)
            dbg_block_end_re = MRC_ACPI_END_RE

        if MRC_BBLOCK_START_RE.match(line):
            dbg_block_name = MRC_BBLOCK_START_RE.match(line).group(1)
            dbg_block_end_re = MRC_BBLOCK_END_RE

        if MRC_iMC_BLOCK_START_RE.match(line):
            dbg_block_name = MRC_iMC_BLOCK_START_RE.match(line).group(1)
            logger.debug("Founded MRC block: " + dbg_block_name)
            dbg_block_end_re = MRC_iMC_BLOCK_END_RE

        if MRC_SMM_BLOCK_START_RE.match(line):
            dbg_block_name = MRC_SMM_BLOCK_START_RE.match(line).group(1)
            dbg_block_end_re = MRC_SMM_BLOCK_END_RE

        if dbg_block_name:
            try:
                block_processor_name = dbg_block_processing_rules[dbg_block_name]
                block_processing_queue.append({dbg_block_name:dbg_block_end_re})
#                print("ADDED BLOCK: " + str(block_processing_queue))
            except KeyError as e:
                pass

        else:
            #print(line)
            if block_processing_queue:
                current_processing_block_ended = False
                if MRC_FATAL_ERROR_RE.match(line):
                    mrc_fatal_error_catched = True
                current_processing_block_name = ''.join(block_processing_queue[-1].keys())
#                print("CURRENT_BLOCK: " + str(current_processing_block_name))
                current_processing_block_end_re = block_processing_queue[-1][current_processing_block_name]
#                print(current_processing_block_end_re.pattern)
                founded_stop_block_mark = current_processing_block_end_re.match(line)
                if founded_stop_block_mark:
#                    print("STOP_BLOCK_LINE: " + line)
#                    print(founded_stop_block_mark.group(1))
#                    print(current_processing_block_name)
                    if founded_stop_block_mark.group(1) == current_processing_block_name:
                        current_processing_block_ended = True
                if mrc_fatal_error_catched or current_processing_block_ended:
#                    print(current_processing_block_name)
                    if dbg_block_processing_rules[current_processing_block_name]:
                        func = dbg_block_processing_rules[current_processing_block_name]
                        socket_id = re.sub(r'\D', "", current_processing_block_name)
                        if not socket_id:
                            socket_id = None
                        #print(block_buffer[current_processing_block_name])
                        try:
                            func(block_buffer[current_processing_block_name], current_processing_block_name, socket_id)
                            processed_funcs.append(func)
#                           print("BEFORE: " + str(block_processing_queue[-1].keys()))
                            block_processing_queue.pop()
                            mrc_fatal_error_catched = False
                        except Exception, e:
                            #logger.info("Failed to process " + str(current_processing_block_name) + " with func.: " + str(func) + ":" )
                            logger.info("Failed to process {} with func {}, raised: {}".format(current_processing_block_name, func, e))
                            pass
                        # Check for possibility to run supplimentary functions and execute them if possible
                        if testplan.keys():
                            testplan_set, processed_funcs = resolve_dependecies(testplan_set, processed_funcs)
                        else:
                            break
                else:
                    block_buffer[current_processing_block_name].append(line)

    n = 0
    if testplan_set:
        logger.debug("Last chance to reach the goal (" + conf['goal']['name'] + "): " + str(testplan_set))
        testplan_set.pop(console_data_dummy, None)
        while testplan_set:
            testplan_set, processed_funcs = resolve_dependecies(testplan_set, processed_funcs)
            n += 1
            if n > 10:
                logger.error("Failed! Not enough data for accomplish the goals!")
                logger.error(testplan_set.keys())
                break

def main():
    """
    The main function
    """
    global conf
    global args
    global ram_info
    global components
    global environment

    global data_source
    global dbg_log_data

    global LED_EXISTENCE

    args = argument_parsing()
    conf = Conf(OPTIONS, args.config, log=False)
    dbg_log_data = list()

    try:
        init_leds
    except IOError as err:
        print("Warning! Can't find leds for highlighting failed DIMM")

    parse_debug_log(args)

if __name__ == '__main__':
    main()

# vim: tabstop=8 softtabstop=0 expandtab shiftwidth=4 smarttab
