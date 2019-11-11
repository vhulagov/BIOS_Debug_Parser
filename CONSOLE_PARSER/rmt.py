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

class RMT:
    """
    Gather Intel Rank Margin Tool, parse and return the output
    """
    def __init__(self, ram_info, rmt_guidelines):
        self.margin_params = ['RxDqs-', 'RxDqs+', 'RxV-', 'RxV+', 'TxDq-', 'TxDq+', 'TxV-', 'TxV+', 'Cmd-', 'Cmd+', 'CmdV-', 'CmdV+', 'Ctl-', 'Ctl+']

        self.dimm_params = ['DIMM vendor', 'DRAM vendor', 'RCD vendor', 'Organisation', 'Form factor', 'Freq', 'Prod. week', 'PN', 'hex']

        self.ram_info = ram_info
        self.rmt_guidelines = rmt_guidelines

        def tree():
            return defaultdict(tree)

        self.rmt_results = tree()
        self.rmt_worst_case_result = {}
        self.dbg_block_processing_rules = {
            'BSSA_RMT' : 'process_rmt_results',
            'RMT_N0' : 'process_rmt_results',
            'RMT_N1' : 'process_rmt_results',
        }
        self.testplan = {
        #     send_component_info : [ ram_conf_validator ],
        #     self.result_completeness : [ process_dimm_info ],
            'send_results': [ 'qualification' ],
            'qualification': [ 'get_worst_case' ],
            'get_worst_case': [ 'result_completeness' ]
        }

    def guidelines(self):
        #print(json.dumps(self.ram_info['System']['DDR Freq'], indent=2))
        logger.info("DDR frequency: " + str(self.ram_info['System']['DDR Freq']))
        #json.dumps(self.rmt_guidelines, indent=4)
        guidelines = self.rmt_guidelines['common'].copy()
        guidelines.update(self.rmt_guidelines[self.ram_info['System']['DDR Freq']])
        return guidelines

    def process_rmt_results(self, rmt_block, rmt_block_name, socket_id):
        """
        Rank (given in Nx.Cx.Dx.Rx) Node/Channel/DIMM/Rank Indicator
        RxDqs- (RxDqLeft) Read DQ timing margin, left side direction
        RxDqs+ (RxDqRight) Read DQ timing margin, right side direction
        RxV- (RxVLow) Read DQ VREF margin, low side direction
        RxV+ (RxVHigh) Read DQ VREF margin, high side direction
        TxDq- (TxDqLeft) Write DQ timing margin, left direction
        TxDq+ (TxDqRight) Write DQ timing margin, right direction
        TxV- (TxVLow) Write DQ VREF margin, low side direction
        TxV+ (TxVHigh) Write DQ VREF margin, high side direction
        """
        logger.info("Processing RMT results...")

        rmt_rank_margin = {}
        for line in rmt_block:
            rmt_rank_match = re.match(r'N([0-1])\.C([0-5])\.D([01])\.R([0-3])', line)
            split_line = line.split()
            if not line or not rmt_rank_match or len(split_line) != 15:
                continue
            if not split_line[1].lstrip('-').isdigit():
                continue
            if rmt_rank_match:
                try:
                    margins_list = map(int,split_line[1:])
                    rmt_dimm = '.'.join(rmt_rank_match.group(1,2,3))
                    rmt_dimm_label = str(self.dimm_labels[rmt_dimm])
                    rmt_rank = 'R' + rmt_rank_match.group(4)
                    #rmt_rank_margin[rmt_rank] = dict(zip(self.margin_params, margins_list))
                    self.rmt_results[rmt_dimm_label][rmt_rank] = dict(zip(self.margin_params, margins_list))
                except:
                    logger.debug("The RMT result is rejected. Format violated:")
                    logger.debug(line)
                    return False
        return True

    def result_completeness(self):
        logger.info("Check RMT results completeness...")
        guidelines = self.guidelines()
        try:
            print(self.rmt_worst_case_result[x].keys()[0] for x in guidelines.keys())
            return True
        except:
            return False
        return True

    def get_worst_case(self):
        def tree():
            return defaultdict(tree)

        worst_margin_dimm = tree()
        worst_margin = {}
        mparam_value = {}
        if self.rmt_results:
            for mparam in self.margin_params:
                self.rmt_worst_case_result[mparam] = {}
                #logger.debug("PARAM: " + mparam)
                for dimm, rank in self.rmt_results.items():
                    worst_margin_dimm[dimm] = min(rank.values(), key=lambda x: abs(x[mparam]))
#                self.rmt_worst_case_result[mparam] = min(worst_margin_dimm.values(), key=lambda x: abs(x[mparam]))[mparam]
                rmt_worst_case_result_min = min(worst_margin_dimm.values(), key=lambda x: abs(x[mparam]))[mparam]
                self.rmt_worst_case_result[mparam][rmt_worst_case_result_min] = list()
                for dimm, params in worst_margin_dimm.items():
                    try:
                        worst_dimm = params.values().index(rmt_worst_case_result_min)
                        self.rmt_worst_case_result[mparam][rmt_worst_case_result_min].append(dimm)
                    except ValueError:
                        continue
            #logger.debug(json.dumps(self.rmt_worst_case_result, indent=2))
        return True

    def qualification(self):
        outcome = False
        worst_margin = {}
        guidelines = self.guidelines()
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
        logger.info("RMT guidelines: " + str(guidelines))
        logger.info("Worst case result: " + str(self.rmt_worst_case_result))
        init_value = next(iter(self.rmt_worst_case_result))
        # Getting worst parameter from worst case margin
        worst_margin[init_value] = self.rmt_worst_case_result[init_value]
        for param in self.margin_params:
            param_value_abs = abs(self.rmt_worst_case_result[param].keys()[0])
            rmt_diff = param_value_abs-abs(guidelines[param])
            if rmt_diff > 0:
                logger.debug("RMT param(" + str(param) + "): passed " + str(param_value_abs) + " > " + str(guidelines[param]))
                if abs(param_value_abs-guidelines[param])<worst_margin.itervalues().next():
                    worst_margin = {}
                    worst_margin[param] = rmt_diff
            else:
                logger.error("RMT result lower than threshold(" + str(param) + ":" + str(guidelines[param]) + \
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
