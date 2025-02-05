# -*- coding: utf-8 -*-

from __future__ import print_function

#import argparse

import re
import sys
import json
import logging

from msel import MemorySubsytemEventsLogger

logging.basicConfig(
    level=logging.DEBUG,
    format='[%(asctime)s] {%(filename)s:%(lineno)d} %(levelname)s - %(message)s',
    stream=sys.stdout
)

logger = logging.getLogger()

class STEP:
    """
    Gather Samsung TestBIOS & Enhanced PPR (STEP) progress information, parse and return progress and the final status
    """
    def __init__(self, ram_info):
        self.ram_info = ram_info
        self.dimm_labels = ram_info.sys_conf['poppulation']

        self.testplan = {
            'step.send_results': ['step.process_step'],
            #'step.process_step': ['ram_conf_validator']
        }

        self.dbg_block_processing_rules = { 
            '@SEC Run CPGC Test': 'step.process_step'
        }

    def get_label_from_slot(self, slot_id):
        n, c, d = slot_id
        dimm_label = self.dimm_labels[n][c][d]
        return dimm_label

    def process_step(self, dbg_log_block, dbg_block_name, socket_id):
        logger.info('Processing STEP...')
        self.step_result = {
            'test_mode' : None
        }   
        STEP_TEST_MODE_RE = re.compile(r'^Test Mode : (.*).')
        STEP_FAILED_PATTERN_RE = re.compile(r'\[FailedPatternBitMask (0x[0-9A-F]+)\] N([0-4])\.C([0-6])\.D([0-3])\. FAIL: R([0-1])\.CID([0-9])\.BG([0-9])\.BA([0-9])\.ROW:(0x[0-9a-f]+)\.COL:(0x[0-9a-f]+)\.DQ([0-7][0-9])\.(PPR)?:?([a-zA-Z]+)?\(?([A-Z]+)?\)?')
	STEP_DIMM_RESULT_RE = re.compile(r'^N([0-1])\.C([0-5])\.D([01]):  \[S/N: ([12][0-9][0-4][0-9])_([A-Z0-9]+)\] (Pass|Fail|Empty)\(?([A-Za-z ]+)?\)?')
        for line in dbg_log_block:
            #[FailedPatternBitMask 0x2] N1.C5.D0. FAIL: R1.CID0.BG2.BA3.ROW:0x0001a.COL:0x3f8.DQ24.
            #[FailedPatternBitMask 0x2] N0.C0.D1. FAIL: R1.CID0.BG2.BA3.ROW:0x07f63.COL:0x118.DQ58.PPR:Done(PASS)
            # Process failed patters records
            print(line)	
            return True
            failed_rank_match = re.match(STEP_FAILED_PATTERN_RE, line)
            if failed_rank_match:
                dimm_id = self.get_label_from_slot(failed_rank_match.group(2,3,4))
                print(dimm_id)
                print(failed_rank_match.groups())
                if dimm_id:
                #    sn = self.ram_info.
                    self.ram_info.log_ram_failure
                    print(dir(self.ram_info))
                    self.step_result[dimm_id] = {}
                    print(self.step_result)
                print(step_dimm_result)
                self.step_result[dimm_id].update({ 'serial' : step_dimm_result.group(5) })
                logger.debug("Founded failed pattern: " + str(dimm_id))
            # Process Result Summary
            step_dimm_result = re.match(STEP_DIMM_RESULT_RE, line)
            if step_dimm_result:
                dimm_id = self.get_label_from_slot(step_dimm_result.group(1,2,3))
                logger.info("Found STEP result for " + str(dimm_id))
                # TODO rework to groupdict()
                if not dimm_id in self.step_result:
                    self.step_result[dimm_id] = {}
                if step_dimm_result.group(5):
                    self.step_result[dimm_id].update({ 'serial' : step_dimm_result.group(5) })
                if step_dimm_result.group(6):
                    self.step_result[dimm_id].update({ 'test_status' : step_dimm_result.group(6) })
                if step_dimm_result.group(7):
                    self.step_result[dimm_id].update({ 'ppr_status' : step_dimm_result.group(7) })
            if re.match(STEP_TEST_MODE_RE, line):
                #step_result['Test Mode'] = re.match(STEP_TEST_MODE_RE, line).group(1).strip(' .')
                step_result = dict([[x.strip(' .') for x in line.split(':')]])
        print(json.dumps(self.step_result, indent=2))
        return True

    def result_completeness(self):
        logger.info("Check STEP results completeness...")
        if not self.result.component:
            return False
        else:
            try:
                print(json.dumps(self.result.component, indent=2))
                return True
            except:
                return False

    def send_results(self, dbg_log_block, dbg_block_name, socket_id):
        pass

#if __name__ == '__main__':
#    parser = argparse.ArgumentParser()
#    parser.add_argument('file')
#    args = parser.parse_args()
#
#    step = STEP(args, 'conf', 'ram_info', MemorySubsytemEventsLogger.):
#    # Check from BMC API that installed memory is Samsung 
#    if bmc_api.get_STEP_possibility():

# vim: tabstop=8 softtabstop=0 expandtab shiftwidth=4 smarttab
