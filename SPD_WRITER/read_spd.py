# Copyright 2015 Lenovo
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""This implements parsing of DDR SPD data.  This is offered up in a pass
through fashion by some service processors.

For now, just doing DDR3 and DDR4

In many cases, astute readers will note that some of the lookup tables
should be a matter of math rather than lookup.  However the SPD
specification explicitly reserves values not in the lookup tables for
future use.  It has happened, for example, that a spec was amended
with discontinuous values for a field that was until that point
possible to derive in a formulaic way
"""
import sys
import smbus
import struct

import re

import logging

from jedec_vids import jedec_ids
import i2c_tiny_usb

memory_types = {
    1: "STD FPM DRAM",
    2: "EDO",
    3: "Pipelined Nibble",
    4: "SDRAM",
    5: "ROM",
    6: "DDR SGRAM",
    7: "DDR SDRAM",
    8: "DDR2 SDRAM",
    9: "DDR2 SDRAM FB-DIMM",
    10: "DDR2 SDRAM FB-DIMM PROBE",
    11: "DDR3 SDRAM",
    12: "DDR4 SDRAM",
}

module_types = {
    1: "RDIMM",
    2: "UDIMM",
    3: "SODIMM",
    4: "Micro-DIMM",
    5: "Mini-RDIMM",
    6: "Mini-UDIMM",
}

ddr3_module_capacity = {
    0: 256,
    1: 512,
    2: 1024,
    3: 2048,
    4: 4096,
    5: 8192,
    6: 16384,
    7: 32768,
}

ddr3_dev_width = {
    0: 4,
    1: 8,
    2: 16,
    3: 32,
}

ddr3_ranks = {
    0: 1,
    1: 2,
    2: 3,
    3: 4
}

ddr3_bus_width = {
    0: 8,
    1: 16,
    2: 32,
    3: 64,
}

def speed_from_clock(clock):
    return int(clock * 8 - (clock * 8 % 100))


def decode_manufacturer(index, mfg):
    index &= 0x7f
    try:
        return jedec_ids[index][mfg]
    except (KeyError, IndexError):
        return 'Unknown ({0}, {1})'.format(index, mfg)


def decode_spd_date(year, week):
    if year == 0 and week == 0:
        return 'Unknown'
    return '20{0:02x}-W{1:x}'.format(year, week)


class SPD(object):
    def __init__(self, bytedata):
        """Parsed memory information

        Parse bytedata input and provide a structured detail about the
        described memory component

        :param bytedata: A bytearray of data to decode
        :return:
        """
        self.rawdata = bytearray(bytedata)
        spd = self.rawdata
        self.info = {'memory_type': memory_types.get(spd[2], 'Unknown')}
        if spd[2] == 11:
            self._decode_ddr3()
        elif spd[2] == 12:
            self._decode_ddr4()

    def _decode_ddr3(self):
        spd = self.rawdata
        finetime = (spd[9] >> 4) / (spd[9] & 0xf)
        fineoffset = spd[34]
        if fineoffset & 0b10000000:
            # Take two's complement for negative offset
            fineoffset = 0 - ((fineoffset ^ 0xff) + 1)
        fineoffset = (finetime * fineoffset) * 10 ** -3
        mtb = spd[10] / float(spd[11])
        clock = 2 // ((mtb * spd[12] + fineoffset) * 10 ** -3)
        self.info['speed'] = speed_from_clock(clock)
        self.info['ecc'] = (spd[8] & 0b11000) != 0
        self.info['module_type'] = module_types.get(spd[3] & 0xf, 'Unknown')
        sdramcap = ddr3_module_capacity[spd[4] & 0xf]
        buswidth = ddr3_bus_width[spd[8] & 0b111]
        sdramwidth = ddr3_dev_width[spd[7] & 0b111]
        ranks = ddr3_ranks[(spd[7] & 0b111000) >> 3]
        self.info['capacity_mb'] = sdramcap / 8 * buswidth / sdramwidth * ranks
        self.info['manufacturer'] = decode_manufacturer(spd[117], spd[118])
        self.info['manufacture_location'] = spd[119]
        self.info['manufacture_date'] = decode_spd_date(spd[120], spd[121])
        self.info['serial'] = hex(struct.unpack(
            '>I', struct.pack('4B', *spd[122:126]))[0])[2:].rjust(8, '0')
        self.info['model'] = struct.pack('18B', *spd[128:146]).strip(
            '\x00\xff ')

    def _decode_ddr4(self):
        spd = self.rawdata
        if spd[17] == 0:
            fineoffset = spd[125]
            if fineoffset & 0b10000000:
                fineoffset = 0 - ((fineoffset ^ 0xff) + 1)
            clock = 2 // ((0.125 * spd[18] + fineoffset * 0.001) * 0.001)
            self.info['speed'] = speed_from_clock(clock)
        else:
            self.info['speed'] = 'Unknown'
        self.info['ecc'] = (spd[13] & 0b11000) == 0b1000
        self.info['module_type'] = module_types.get(spd[3] & 0xf,
                                                    'Unknown')
        sdramcap = ddr3_module_capacity[spd[4] & 0xf]
        buswidth = ddr3_bus_width[spd[13] & 0b111]
        sdramwidth = ddr3_dev_width[spd[12] & 0b111]
        ranks = ddr3_ranks[(spd[12] & 0b111000) >> 3]
        self.info['capacity_mb'] = sdramcap / 8 * buswidth / sdramwidth * ranks
        self.info['manufacturer'] = decode_manufacturer(spd[320], spd[321])
        self.info['manufacture_location'] = spd[322]
        self.info['manufacture_date'] = decode_spd_date(spd[323], spd[324])
        self.info['serial_raw'] = spd[325:329]
        #struct.unpack('>I', struct.pack('4B', *spd[325:329]))[0])[2:].rjust(8, '0')
        self.info['serial'] = hex(struct.unpack(
            '>I', struct.pack('4B', *spd[325:329]))[0])[2:].rjust(8, '0')
        self.info['model'] = struct.pack('18B', *spd[329:347]).strip(
            b'\x00\xff ')

logging.basicConfig(
    level=logging.DEBUG,
    format='[%(asctime)s] {%(filename)s:%(lineno)d} %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger()

spd_pg_addr = 0x52
spd_sel_pg1 = 0x36
spd_sel_pg2 = 0x37

if __name__ == '__main__':
    i2c_bus_id = i2c_tiny_usb.find_tiny_usb_i2c_gate()
    if i2c_bus_id is None or type(i2c_bus_id) is not int:
        logger.error("I2C bus is not found!")
        sys.exit(1)

    logger.info("Discovered USB-I2C gate on bus: " + str(i2c_bus_id))

    bus = smbus.SMBus(i2c_bus_id)
    spd_raw = []
    for page in spd_sel_pg1, spd_sel_pg2:
        bus.write_byte_data(page, 0, 0)
        for b in range(0, 8):
            spd_raw += bus.read_i2c_block_data(spd_pg_addr, b * 32, 32)
    if len(spd_raw) != 512:
        print("Looks like some data corrupted")
        sys.exit(1)
    spd_obj = SPD(spd_raw)
    spd_obj._decode_ddr4()
    print(spd_obj.info)
    spd_obj.info['serial_raw']


# vim: tabstop=4 shiftwidth=4 softtabstop=4
