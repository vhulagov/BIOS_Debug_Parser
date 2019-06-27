# -*- coding: utf-8 -*-

from __future__ import print_function

import re
import sys
import json
import yaml
import logging

import itertools
from collections import defaultdict

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
    def __init__(self, args, conf, ram_info, test_result):
        self.args = args
        self.conf = conf
        self.ram_info = ram_info
        self.result = test_result
        self.result.name = 'STEP'
        self.step_result = {}

        def tree():
            return defaultdict(tree)

        self.dimm_labels = yaml.load(open(conf['node_configuration']['dimm_labels']), Loader=yaml.SafeLoader)

    def testplan(self):
        testplan = {
            self.send_results : [ self.qualification ],
            self.qualification : [ self.result_completeness ]
        }
        return testplan

    def processing_rules(self):
        dbg_block_processing_rules = { 
            '@SEC Run CPGC Test' : self.process_step
        }
        return dbg_block_processing_rules

    def process_step(self, dbg_log_block, dbg_block_name, socket_id):
        logger.info('Processing STEP...')
        self.step_result = {
            'test_mode' : None
        }   
        STEP_TEST_MODE_RE = re.compile(r'^Test Mode : (.*).')
        STEP_FAILED_PATTERN_RE = re.compile(r'\[FailedPatternBitMask (0x[0-9]+)\] N([0-4])\.C([0-6])\.D([0-3])\. FAIL: R([0-1])\.CID([0-9]).BG([0-9])\.BA([0-9])\.ROW:(0x[0-9a-f]*)\.COL:(0x[0-9a-f])\.DQ([0-7][0-9])\.')
	STEP_DIMM_RESULT_RE = re.compile(r'^N([0-1])\.C([0-5])\.D([01]):  \[S/N: ([12][0-9][0-4][0-9])_([A-Z0-9]+)\] (Pass|Fail|Empty)\(?(.+?)\)?')
        dimm_labels = yaml.load(open(self.conf['node_configuration']['dimm_labels']), Loader=yaml.BaseLoader)
        print(json.dumps(self.ram_info, indent=2))
        for line in dbg_log_block:
            #print(line)
            #[FailedPatternBitMask 0x2] N1.C5.D0. FAIL: R1.CID0.BG2.BA3.ROW:0x0001a.COL:0x3f8.DQ24.
            if re.match(STEP_TEST_MODE_RE, line):
                #step_result['Test Mode'] = re.match(STEP_TEST_MODE_RE, line).group(1).strip(' .')
                step_result = dict([[x.strip(' .') for x in line.split(':')]])
            # Process failed patters records
            if re.match(STEP_FAILED_PATTERN_RE, line):
		print(line)	
                failed_rank_match = re.match(STEP_FAILED_PATTERN_RE, line).group(0)
                print(failed_rank_match)
                try:
                    rmt_dimm = '.'.join(rmt_rank_match.group(1,2,3))
                    rmt_dimm_label = str(self.dimm_labels[rmt_dimm])
                    self.step_results[rmt_dimm_label][rmt_rank] = dict(zip(self.margin_params, margins_list))
                except:
                    logger.debug("The STEP result is rejected. Format violated: " + line)
                    return False
            # Process Result Summary
            step_dimm_result = re.match(STEP_DIMM_RESULT_RE, line)
            if step_dimm_result:
                dimm_id = '.'.join(step_dimm_result.group(1,2,3))
                #print(step_dimm_result.lastindex)
                dimm_slot = dimm_labels[dimm_id]
                logger.info("Found STEP result for " + dimm_slot)
#                if step_dimm_result.group(5):
#                    self.step_result[dimm_slot].update({ 'serial' : step_dimm_result.group(5) })
#                if step_dimm_result.group(6):
#                    self.step_result[dimm_slot].update({ 'test_status' : step_dimm_result.group(6) })
                if step_dimm_result.group(7):
#                    self.step_result[dimm_slot].update({ 'ppr_status' : step_dimm_result.group(7) })
                    self.step_result[dimm_slot] = { 'ppr_status' : step_dimm_result.group(7) }
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

    def qualification(self):
        return True
        outcome = False
        worst_margin = {}
        # Check if all parameters satisfy the margin thresholds (guidelines)
        #print(json.dumps(self.rmt_worst_case_result.keys()))
        #print(guidelines)

        outcome = not any(abs(guidelines[x])>abs(self.rmt_worst_case_result[x].keys()[0]) for x in guidelines.keys())
        if not outcome:
            self.result.set_status(error='Margin is too bad')
        #self.result.add_data(['guidelines'], guidelines)
        self.result.config['guidelines'] = guidelines
        self.result.add_data(['rmt'], self.rmt_results)
        self.result.add_data(['worst_case'], self.rmt_worst_case_result)
        logger.info("STEP guidelines: " + str(guidelines))
        logger.info("Worst case result: " + str(self.rmt_worst_case_result))
        init_value = next(iter(self.rmt_worst_case_result))
        # Getting worst parameter from worst case margin
        worst_margin[init_value] = self.rmt_worst_case_result[init_value]
        for param in self.margin_params:
            param_value_abs = abs(self.rmt_worst_case_result[param].keys()[0])
            rmt_diff = param_value_abs-abs(guidelines[param])
            if rmt_diff > 0:
                logger.debug("STEP param(" + str(param) + "): passed " + str(param_value_abs) + " > " + str(guidelines[param]))
                if abs(param_value_abs-guidelines[param])<worst_margin.itervalues().next():
                    worst_margin = {}
                    worst_margin[param] = rmt_diff
            else:
                logger.error("STEP result lower than threshold(" + str(param) + ":" + str(guidelines[param]) + \
                "):" + str(param_value_abs))
                if param_value_abs-guidelines[param]<worst_margin.itervalues().next():
                    worst_margin = {}
                    worst_margin[param] = rmt_diff
        self.result.add_data(['worst_margin'], worst_margin)
        self.result.finish()

#    #environment['baseboard'] = baseboard_mfg + " " + baseboard_product
#    #environment['inventory'] = baseboard_serial
#    #environment['bmc version'] = bmc_version.lstrip('0')
#    model = 'Unknown'
#    if rmt_instance.result.component:
#        model = rmt_instance.result.component[0].get('model')
#    #    tags = [model]
#    #    if args.tags:
#    #        tags.extend(tag.strip() for tag in args.tags.split(','))
#    #    rmt_instance.result.add_tags(tags)

        return True

    def send_results(self):
        if self.args.disable_sending:
            print(json.dumps(self.result.get_result_dict(), indent=2))
            return True
        else:
            return self.result.send_via_api(self.conf['report']['api_url'])

# vim: tabstop=8 softtabstop=0 expandtab shiftwidth=4 smarttab
