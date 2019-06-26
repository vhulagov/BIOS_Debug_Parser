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
    def __init__(self, conf, ram_info, test_result):
        self.margin_params = ['RxDqs-', 'RxDqs+', 'RxV-', 'RxV+', 'TxDq-', 'TxDq+', 'TxV-', 'TxV+', 'Cmd-', 'Cmd+', 'CmdV-', 'CmdV+', 'Ctl-', 'Ctl+']

        self.dimm_params = ['DIMM vendor', 'DRAM vendor', 'RCD vendor', 'Organisation', 'Form factor', 'Freq', 'Prod. week', 'PN', 'hex']

        self.ram_info = ram_info
        self.conf = conf
        self.result = test_result
        self.result.name = 'RMT'

        def tree():
            return defaultdict(tree)

        self.rmt_results = tree()
        self.rmt_worst_case_result = {}

        self.guidelines_all = yaml.load(open(conf['RMT']['guidelines']), Loader=yaml.SafeLoader)
        self.dimm_labels = yaml.load(open(conf['node_configuration']['dimm_labels']), Loader=yaml.SafeLoader)

    def testplan(self):
    #testplan = yaml.load(open(conf['signal_integrity']['goal_dependencies']), Loader=yaml.BaseLoader)
    #testplan_set = dict((globals()[k], set(testplan[globals()[k]])) for k in testplan)
    #testplan_set = dict((eval(k), set(testplan[eval(k)])) for k in testplan)
#    return testplan = {
#    #        send_component_info : [ ram_conf_validator ],
#        send_rmt_results : [ rmt_instance.qualification ],
#        ram_conf_validator : [ process_socket_info, process_dimm_info ],
#        rmt_instance.get_worst_case : [ rmt_instance.result_completeness ],
#        rmt_instance.result_completeness : [ process_dimm_info ],
#        rmt_instance.qualification : [ rmt_instance.get_worst_case, ram_conf_validator ],
#        process_socket_info : [ console_data_dummy ],
#        process_dimm_info : [ console_data_dummy ]
#    }
        testplan = {
        #     send_component_info : [ ram_conf_validator ],
        #     self.result_completeness : [ process_dimm_info ],
            self.send_results : [ self.qualification ],
            self.qualification : [ self.get_worst_case ],
            self.get_worst_case : [ self.result_completeness ]
        }
        return testplan

    def processing_rules(self):
        dbg_block_processing_rules = {
            'BSSA_RMT' : self.process_rmt_results,
            'RMT_N0' : self.process_rmt_results,
            'RMT_N1' : self.process_rmt_results,
        }
        return dbg_block_processing_rules

    def guidelines(self):
        #print(json.dumps(self.ram_info['System']['DDR Freq'], indent=2))
        logger.info("DDR frequency: " + str(self.ram_info['System']['DDR Freq']))
        #json.dumps(self.guidelines_all, indent=4)
        guidelines = self.guidelines_all['common'].copy()
        guidelines.update(self.guidelines_all[self.ram_info['System']['DDR Freq']])
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
        if not self.result.component:
            return False

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
        return self.result.send_via_api(self.conf['report']['api_url'])

# vim: tabstop=8 softtabstop=0 expandtab shiftwidth=4 smarttab
