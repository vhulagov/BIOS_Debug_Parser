# -*- coding: utf-8 -*-

from __future__ import print_function

import re
import json
import yaml

from collections import defaultdict

import benchmark.common
from benchmark.common import log_msg, yank_api
from benchmark.conf import Conf, parse_list
from benchmark.test_result import BasicTestResult


# Exit error codes
ERR_RAM_PN_MIXED = 102
ERR_RAM_CNT_INCORRECT = 103
ERR_RAM_LOW_FREQ = 104
ERR_RMT_DATA_MISSING = 120

#class RMT(ram_info, rmt_block):
class RMT:
    """
    Gather Intel Rank Margin Tool, parse and return the output
    """
    def __init__(self, conf, ram_info, guidelines_file):
        self.margin_params = ['RxDqs-', 'RxDqs+', 'RxV-', 'RxV+', 'TxDq-', 'TxDq+', 'TxV-', 'TxV+', 'Cmd-', 'Cmd+', 'CmdV-', 'CmdV+', 'Ctl-', 'Ctl+']

        self.dimm_params = ['DIMM vendor', 'DRAM vendor', 'RCD vendor', 'Organisation', 'Form factor', 'Freq', 'Prod. week', 'PN', 'hex']

        self.ram_info = ram_info

        def tree():
            return defaultdict(tree)

        self.rmt_results = {}
        self.rmt_worst_case_result = {}

#        self.test_name = 'signal_integrity'
#        self.config = conf[self.test_name]
        self.guidelines_file = guidelines_file
        # import pdb; pdb.set_trace()
        self.test_configuration = []
        self.environment = {}
        self.tags = {}
        self.test_result = {}
        self.idle_latencies_fullset = []
#        self.rmt_data_required = defaultdict(int)
#        self.rmt_data_required.update({
#            'socket_0_info' : 1,
#            'socket_1_info' : 1,
#            'dimm_info' : 1
#            })
        self.rmt_data_completeness = False

    def guidelines(self):
        #self.ram_info
        #log_msg(ram_info['System']['DDR Freq'])
        guidelines_raw = yaml.load(open(self.guidelines_file))
        guidelines = guidelines_raw['common'].copy()
        print(self.ram_info.keys())
        guidelines.update(guidelines_raw[self.ram_info['System']['DDR Freq']])
        return guidelines

    def qualification(self):
	rmt_result_decision = False
	worst_margin = {}
	guidelines = get_guidelines(guidelines_file)
	print("RMT guidelines: " + str(guidelines))
	print("Worst case result: " + str(rmt_worst_case_result))
	rmt_result_decision = not any(abs(guidelines[x])>abs(rmt_worst_case_result[x]) for x in guidelines.keys())
	init_value = next(iter(rmt_worst_case_result))
	worst_margin[init_value] = rmt_worst_case_result[init_value]
	for param in margin_params:
	    rmt_diff = abs(rmt_worst_case_result[param])-abs(guidelines[param])
	    if rmt_diff > 0:
		#print("POSITIVE")
		if abs(abs(rmt_worst_case_result[param])-guidelines[param])<worst_margin.itervalues().next():
		    worst_margin = {}
		    worst_margin[param] = rmt_diff
	    else:
		#print("NEGATIVE(" + str(param) +"):" + str(rmt_worst_case_result[param]) + " " + str(guidelines[param]))
		if abs(rmt_worst_case_result[param])-guidelines[param]<worst_margin.itervalues().next():
		    worst_margin = {}
		    worst_margin[param] = rmt_diff
	return rmt_result_decision, worst_margin

#        rmt_result_decision = False
#        worst_margin = {}
#        guidelines = self.guidelines()
#        decision = any(abs(guidelines[x])>abs(self.rmt_worst_case_result[x]) for x in guidelines.keys())
#        if not decision:
#            init_value = next(iter(self.rmt_worst_case_result))
#            worst_margin[init_value] = self.rmt_worst_case_result[init_value]
#            for param in self.margin_params:
#                if abs(abs(self.rmt_worst_case_result[param])-abs(guidelines[param]))<worst_margin.itervalues().next():
#                    worst_margin = {}
#                    worst_margin[param] = abs(self.rmt_worst_case_result[param])-abs(guidelines[param])
#                    rmt_result_decision = True
#        return rmt_result_decision, worst_margin

    def result_completeness(self):
        print("Check RMT results completeness...")
        #node_id, chan_id, dimm_id, rank_id = self.rmt_results.keys().split('.')
        return True
        
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
        print("Processing RMT results...")
        self.rmt_worst_case_result_node = {}

        for line in rmt_block:
            rmt_rank = re.match(r'N[0-1]\.C[0-5]\.D[01]\.R[0-3]', line)
            split_line = line.split()
            if not line or not rmt_rank or len(split_line) != 15: 
                continue
            if not split_line[1].lstrip('-').isdigit():
                continue
            if rmt_rank:
                try:
                  margins_list = map(int,split_line[1:])
                except:
                  log_msg("The RMT result is rejected. Format violated:", force=True)
                  print(line)
                  return -1

                margin_steps = dict(zip(self.margin_params, margins_list))
                #self.rmt_results[node_id][chan_id][dimm_id][rank_id] = margin_steps
                self.rmt_results[rmt_rank] = margin_steps
#        json.dumps(self.rmt_results, indent=2)

        if self.rmt_results:
            for key in self.margin_params:
                self.rmt_worst_case_result_node[key] = (min(self.rmt_results.values(), key=lambda x: abs(x[key]))[key])

            if self.rmt_worst_case_result:
                for key in self.margin_params:
                    self.rmt_worst_case_result[key] = min(self.rmt_worst_case_result_node[key], self.rmt_worst_case_result[key])
            else:
                self.rmt_worst_case_result = self.rmt_worst_case_result_node
            
#            log_msg("RMT worst case result for socket " + str(socket_id))
#            log_msg(json.dumps(self.rmt_worst_case_result, indent=2))
#            if ram_info:
#                if rmt_result_completeness:
                    
            
            return self.rmt_results, self.rmt_worst_case_result

    def result_finalyze(self):
        result = TestResult(conf, test_name)
        analyze_rmt(args, conf, result)
        result.component = components
        result.finish()

        if rmt_data_completeness:
            rmt_result_decision, worst_margin = qualification(self.rmt_worst_case_result, args.guidelines)
        else:
            log_msg('FAIL! Not enough RMT data!', force=True)
            sys.exit(ERR_RMT_DATA_MISSING)

        result.add_data(['worst_margin'], worst_margin)
        if rmt_result_decision:
            log_msg('PASS', force=True)
        else:
            test_result.set_status(error='Margin is too bad')

#        model = 'Unknown'
#        if result.component and not args.disable_sending:
#            model = result.component[0].get('model')
#            result.send_component_info(conf['report']['api_url'], result.component, args.startrek)
#        tags = [model]
#        if args.tags:
#            tags.extend(tag.strip() for tag in args.tags.split(','))
#        TestResult.add_tags(tags)
#        log_msg(json.dumps(result.get_result_dict(), indent=2), force=True)
#        filename = '{0}_{1}_{2}.json'.format(model, test_name, result.started_at)
#        result.save_to_file(filename)
#        if not args.disable_sending:
#            result.send_via_api(conf['report']['api_url'])
#
#       
#        TestResult.environment['baseboard'] = baseboard_mfg + " " + baseboard_product
#        TestResult.environment['inventory'] = baseboard_serial
#        TestResult.environment['bmc version'] = bmc_version.lstrip('0')
#        result.add_data(['worst_case'], self.rmt_worst_case_result)

# vim: tabstop=8 softtabstop=0 expandtab shiftwidth=4 smarttab
