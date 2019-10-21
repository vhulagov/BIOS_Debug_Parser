# -*- coding: utf-8 -*-

from __future__ import print_function

import struct
import uuid

import sys
import argparse
import os.path

class SMBios(object):
    '''
    Decode smbios.bin

    Ref to SMBios SPEC Ver: 2.7.1,
    Chapter 5.2.1:
    struct SMBIOSEntryPoint {
     char EntryPointString[4];    //This is _SM_
     uchar Checksum;              //This value summed with all the values of the table, should be 0 (overflow)
     uchar Length;                //Length of the Entry Point Table. Since version 2.1 of SMBIOS, this is 0x1F
     uchar MajorVersion;          //Major Version of SMBIOS
     uchar MinorVersion;          //Minor Version of SMBIOS
     ushort MaxStructureSize;     //Maximum size of a SMBIOS Structure (we will se later)
     uchar EntryPointRevision;    //...
     char FormattedArea[5];       //...
     char EntryPointString2[5];   //This is _DMI_
     uchar Checksum2;             //Checksum for values from EntryPointString2 to the end of table
     ushort TableLength;          //Length of the Table containing all the structures
     uint TableAddress;         //Address of the Table
     ushort NumberOfStructures;   //Number of structures in the table
     uchar BCDRevision;           //Unused
     uchar pad;                   //pad.
    };

    Chapter 6.1.2:
    struct SMBIOSHeader {
     uchar Type;
     uchar Length;
     ushort Handle;
    };
    '''
    _fmt_entry = "4sBBBBHb5s5sBHIHBB"
    '''
    spec filename: DSP0134_3.0.0.pdf
    Entry Format 3.0. Ref to SMBios SPEC Ver:3.0.0, Chapter:5.2.2
    struct SMBIOSEntryPoint {
     char EntryPointString[5];    //This is '_SM3_'
     uchar Checksum;              //This value summed with all the values of the table, should be 0 (overflow)
     uchar Length;                //Length of the Entry Point Table. this is 0x18 in spec 3.0
     uchar MajorVersion;          //Major Version of SMBIOS
     uchar MinorVersion;          //Minor Version of SMBIOS
     uchar docrev;                //docrev
     uchar entry_point_rev;       //01h in spec 3.
     uchar reserved;              //Address of the Table
     ulong MaxSizeOfStructures;   //Max size of the table
     uint64_t TableAddress;       //offset of all tables.
    };
    '''
    _fmt3_entry = "5sBBBBBBBIQ"
    _fmt_header = "BBH"
    Id_Checksum = 1
    Id_MaxStructureSize = 5
    Id_Checksum2 = 9
    Id_TotalLength = 10
    Id_TableAddress = 11
    Id_NumberOfStructures = 12
    TYPE_BIOSInformation = 0
    TYPE_SystemInformation = 1
    TYPE_BaseboardInformation = 2
    TYPE_ChassisInformation = 3
    TYPE_ProcessorInformation = 4
    TYPE_PhysicalMemoryArrayInformation = 16
    TYPE_MemoryDevice = 17

    def __init__(self, src):
        '''
        Open SMBIOS binary file or data and decode it.
        '''
        self.__dict = []
        self.__entry = None
        self.smbios = {}
        self.__type0_index = None
        self.__type1_index = None
        self.__type2_index = None
        self.__type3_index = None
        self.__type4_index_list = []
        self.__type16_index_list = []
        self.__type17_index_list = []
        if os.path.isfile(src):
            print("Input data is a file")
            with open(src, "rb") as fin:
                self._buf = fin.read()
        else:
            print("Input data is a stream")
            self._buf = src
        if self.__decode3():
            print("Detected SMBIOS v3")
        elif self.__decode():
            print("Detected SMBIOS v2")
        #elif self.__decode_no_entry():
        else:
            raise Exception("can't identify SMBIOS version")

    def __decode3(self):
        print("Unpack Entry Table")
        # unpack Entry Table
        print(self._buf)
        entry = struct.unpack_from(SMBios._fmt3_entry, self._buf, 0)
        if not (entry[0] == "_SM3_" and entry[3] == 3):
            return False
        self.__entry = entry
        # get offset from header['TableAddress'].
        print("Get offset from header['TableAddress']")
        #print(entry[9])
        offset = entry[9]
        while offset < len(self._buf):
            offset = self.__decode_entry(offset)
        return True

#    def __decode_no_entry(self):
#        # process special file without Entry Table
#        print("Process special file without Entry Table")
#        try:
#            offset = 0
#            while offset < len(self._buf):
#                offset = self.__decode_entry(offset)
#            self.save = self.__save
#            # setup default entry table.
#            print("Setup default entry table.")
#            self.__entry = ('_SM_', 62, 31, 2, 0, 1086, 0, '\x00\x00\x00\x00\x00', '_DMI_', 110, 6431, 32, 114, 48, 0)
#            return True
#        except Exception:
#            return False

    def __decode(self):
        """
        Decode the SMBIOSEntryPoint
        """
        # unpack Entry Table
        entry = struct.unpack_from(SMBios._fmt_entry, self._buf, 0)
        if not (entry[0] == "_SM_"):
            return False

        self.save = self.__save
        self.__entry = entry
        offset = struct.calcsize(SMBios._fmt_entry)
        for _ in range(0, entry[12]):
            offset = self.__decode_entry(offset)
        return True

    def __decode_entry(self, offset):
        header = struct.unpack_from(SMBios._fmt_header, self._buf, offset)
        start = offset
        offset += header[1]
        while self._buf[offset] != '\0' or self._buf[offset + 1] != '\0':
            offset += 1
        offset += 2
        structure = self._buf[start:offset]
        #print(header[0])

        if header[0] == SMBios.TYPE_BIOSInformation:
            self.__type0_index = len(self.__dict)
        if header[0] == SMBios.TYPE_SystemInformation:
            self.__type1_index = len(self.__dict)
        if header[0] == SMBios.TYPE_ChassisInformation:
            self.__type3_index = len(self.__dict)
        if header[0] == SMBios.TYPE_BaseboardInformation:
            self.__type2_index = len(self.__dict)
        if header[0] == SMBios.TYPE_ProcessorInformation:
            self.__type4_index_list.append(len(self.__dict))
        if header[0] == SMBios.TYPE_PhysicalMemoryArrayInformation:
            self.__type16_index_list.append(len(self.__dict))
        if header[0] == SMBios.TYPE_MemoryDevice:
            self.__type17_index_list.append(len(self.__dict))

        self.__dict.append(structure)
        return offset

    def __get_checksum(self, buf):
        check_sum = sum(bytearray(buf))
        return (-check_sum) & 0xff

    def _unpack_table(self, fmt, src):
        # unpack data. drop end of fmt if src is not long enough.
        length = ord(src[1])
        pad = 0
        while struct.calcsize(fmt) > length:
            fmt = fmt[:-1]
            pad = pad + 1
        result = list(struct.unpack_from(fmt, src))
        result.extend([0] * pad)
        strings = src[length:].split('\0')
        return result, strings

    def _pack_table(self, fmt, info, strings):
        # pack data. drop end of src if fmt is smaller.
        info[1] = struct.calcsize(fmt)
        result = struct.pack(fmt, *info)
        result += '\0'.join(strings)
        return result

    def decode_all_data(self):
        self.decode_type0()
        self.decode_type1()
#        self.decode_type2()
#        self.decode_type3()
#        self.decode_type4()
#        self.decode_type17()

    def __update_string(self, string_values, index, value):
        if value is None:
            return index
        if index <= 0:
            index = len(string_values) - 2
            string_values.insert(index, value)
            index += 1
        else:
            string_values[index - 1] = value
        return index

    def decode_type0(self):
        self.smbios['type0'] = {}
        bios_info_fmt = "BBHBBHBBQ16sBBBB"
        # fetch the BIOS Information
        bios_info = self.__dict[self.__type0_index]
        # __decode header.
        info, string_values = self._unpack_table(bios_info_fmt, bios_info)

        self.smbios['type0'] = {
            'bios_vendor': string_values[0],
            'bios_version': string_values[1],
            'bios_release_date': string_values[2],
            'bios_address': string_values[3]
#            'bios_runtime_size': string_values[4]
#            'bios_rom_size': string_values[5],
#            'bios_characteristics': string_values[6],
#            'bios_revision': string_values[7],
#            'firmware_revision': string_values[8]
            }
        print(self.smbios)

    def decode_type1(self):
        '''
        support following fields,
        sn, uuid, and sku_number,
        '''
        self.smbios['type1'] = {}
        # Refer to Chapter 7.2
        sys_info_fmt = "BBHBBBB16sBBB"
        # fetch the System Information Structure
        sys_info = self.__dict[self.__type1_index]
        # __decode header.
        info, string_values = self._unpack_table(sys_info_fmt, sys_info)

        #[1, 27, 1, 1, 2, 3, 4, '\x00\x80\x93\xdbt\xfd\xe7\x11\x80\x00\xb4.\x99/Z\x14', 6, 5, 6]
        #['Yandex', 'T175-N41-Y3N', '0100', '102701401', '01234567890123456789AB', 'Server', '', '']
        self.smbios['type1'] = {
            'system_vendor': string_values[0],
            'system_model': string_values[1]
            }
    def decode_type1(self):
        '''
        support following fields,
        sn, uuid, and sku_number,
        '''
        self.smbios['type1'] = {}
        # Refer to Chapter 7.2
        sys_info_fmt = "BBHBBBB16sBBB"
        # fetch the System Information Structure
        sys_info = self.__dict[self.__type1_index]
        # __decode header.
        info, string_values = self._unpack_table(sys_info_fmt, sys_info)

        #[1, 27, 1, 1, 2, 3, 4, '\x00\x80\x93\xdbt\xfd\xe7\x11\x80\x00\xb4.\x99/Z\x14', 6, 5, 6]
        #['Yandex', 'T175-N41-Y3N', '0100', '102701401', '01234567890123456789AB', 'Server', '', '']
        self.smbios['type1'] = {
            'system_vendor': string_values[0],
            'system_model': string_values[1]
            }
        print(self.smbios['type1'])

    def decode_type2(self):
        self.smbios['type2'] = {}
        if self.__type2_index is None or info_map is None:
            return
        # Ref to SMBios SPEC Ver: 3.0.0, Chapter 7.3

        board_info_fmt = "=BBHBBBBBBBHBB"
        board_info = self.__dict[self.__type2_index]
        info, string_values = self._unpack_table(board_info_fmt, board_info)


    def decode_type3(self):
        '''
        support following fields,
        sn,
        '''
        if self.__type3_index is None or info_map is None:
            return
        # Ref to SMBios SPEC Ver: 3.0.0, Chapter 7.4
        # '=' force byte alignemnt.
        chassis_info_fmt = "=BBHBBBBBBBBBIBBBB"
        # fetch the System Information Structure
        chassis_info = self.__dict[self.__type3_index]
        # decode header.
        info, string_values = self._unpack_table(chassis_info_fmt, chassis_info)
        # check contained element count * size
        if info[1] > struct.calcsize(chassis_info_fmt):
            chassis_info_fmt = chassis_info_fmt + "{}s".format(info[1] - struct.calcsize(chassis_info_fmt))
            info.append(chassis_info[struct.calcsize(chassis_info_fmt):info[1]])

        # modify SN string.
        sn_index = info[6]  # position number of SN.
        info[6] = self.__update_string(string_values, sn_index, info_map.get('sn'))

        # pack modified data and save it
        self.__dict[self.__type3_index] = self._pack_table(chassis_info_fmt, info, string_values)

    def decode_type4(self, cpu):
        '''
        support following fields,
        sn, version, core number, speed, max speed, part number and asset tag.
        '''
        if len(self.__type4_index_list) == 0 or cpu is None:
            return
        # Format of Processor Information (Type 4). Ref Chapter 7.5
        pro_info_fmt = '=BBHBBBBQBBHHHBBHHHBBBBBBHHHHH'
        for idx in self.__type4_index_list:
            info = self.__dict[idx]
            # unpack table.
            pro_info, string_values = self._unpack_table(pro_info_fmt, info)

            # pro_info[7] = 0 # process ID
            # update Processor Version
            pro_info[8] = self.__update_string(string_values, pro_info[8], cpu.get("version"))
            pro_info[11] = cpu.get('max_speed', 4000)  # max spped. MHz
            pro_info[12] = cpu.get('speed', 1800)  # current speed. MHz

            # update sn
            pro_info[18] = self.__update_string(string_values, pro_info[18], cpu.get('sn'))
            # update asset tag
            pro_info[19] = self.__update_string(string_values, pro_info[19], cpu.get('asset_tag'))
            # update part number
            pro_info[20] = self.__update_string(string_values, pro_info[20], cpu.get('part_number'))

            core_number = cpu.get("cores", 4)
            pro_info[21] = core_number  # Core Count
            pro_info[22] = core_number  # Core Enabled
            pro_info[23] = core_number  # Thread Count
            # Core count 2, Core Enabled 2 and Thread Count 2 set to same value if core count < 255.
            pro_info[26] = core_number  # Core Count 2.
            pro_info[27] = core_number  # Core Enabled 2
            pro_info[28] = core_number  # Thread Count 2

            # pack the table
            self.__dict[idx] = self._pack_table(pro_info_fmt, pro_info, string_values)

    def check_type16(self, total_count):
        if len(self.__type16_index_list) == 0:
            raise Exception("Type 16 - Physical Memory Array is missing")
        fmt = '=BBHBBBIHHQ'
        count = 0
        for idx in self.__type16_index_list:
            raw = self.__dict[idx]
            info, _ = self._unpack_table(fmt, raw)
            # support there is 24 memory slots on board.
            # if not, Slot number in Type16 Physical Memory Array must be modified.
            # 8th field "Number of Memory Devices"
            count += info[8]
        if count < total_count:
            raise Exception('Not enough dimm slots. Provides: {}, expected: {}'.format(count, total_count))

    def decode_type17(self, dimm=None):
        '''
        support following fields,
        sn, size, part number, manufactuer, asset tag, part number and number of dimm
        '''
        if dimm is None:
            # don't modify memory device array.
            return

        self.check_type16(len(dimm))
        if len(self.__type4_index_list) == 0:
            raise Exception("Type 17 - Memory Device is missing")
        # Cha 7.18, Table 73
        mem_info_fmt = '=BBHHHHHHBBBBBHHBBBBBIHHHH'

        class mem_dev_struct(list):
            fields = [
                "type",
                "length",
                "handle",
                "physical memory array handle",
                "memory error information handle",
                "total width",
                "data width",
                "size",
                "form factor",
                "device set",
                "device locator",
                "ban locator",
                "memory type",
                "type detail",
                "speed",
                "manufactuer",
                "sn",
                "asset tag",
                "part number",
                "attributes",
                "extended size",
                "configured memory clock speed",
                "min volt",
                "max volt",
                "config volt"]

            def __setitem__(self, key, value):
                if isinstance(key, str):
                    key = self.fields.index(key)
                super(mem_dev_struct, self).__setitem__(key, value)

            def __getitem__(self, key):
                if isinstance(key, str):
                    key = self.fields.index(key)
                return super(mem_dev_struct, self).__getitem__(key)

        all_targets = []
        for idx in self.__type17_index_list:
            mem_info = self.__dict[idx]
            info, string_values = self._unpack_table(mem_info_fmt, mem_info)
            info = mem_dev_struct(info)
            # found memory device by device locator
            dev_locator = string_values[info["device locator"] - 1]
            all_targets.append({"idx": idx, "locator": dev_locator, "info": info, "strings": string_values})

        for dimm_info in dimm:
            locator = dimm_info.get("locator")
            target = filter(lambda x: x["locator"] == locator, all_targets)
            if len(target) == 0:
                raise Exception("Expected memory locator {} not found in Type17 list".format(locator))
            target[0]["expected"] = dimm_info

        for target in all_targets:
            dimm_info = target.get("expected", {})
            info = target["info"]
            string_values = target["strings"]
            size = dimm_info.get('size', 0)
            if size:
                # modify target memory device.
                info["total width"] = 72
                info["data width"] = 64

                # according to spec,
                # info['size'] & 0x8000 == 1, unit = KB.
                # info['size'] & 0x8000 == 0, unit = MB.
                if size < 1024 * 1024:
                    size = size / 1024
                    info["size"] = 0x8000 + size
                else:
                    size = size / 1024 / 1024
                    info["size"] = size
                info["form factor"] = 9
                info["device set"] = 0
                info["device locator"] = 1
                info["ban locator"] = 2
                info["memory type"] = 26
                info["type detail"] = 128
                info["speed"] = 2666
                info["attributes"] = 2
                info["extended size"] = 0
                info["configured memory clock speed"] = 2666
                info["manufactuer"] = self.__update_string(string_values, info["manufactuer"],
                                                           dimm_info.get('manufactuer', 'Hynix'))
                info["sn"] = self.__update_string(string_values, info["sn"], dimm_info.get('sn'))
                info["asset tag"] = self.__update_string(string_values, info["asset tag"],
                                                         dimm_info.get('asset_tag', string_values[0] + '_AssetTag'))
                info["part number"] = self.__update_string(string_values, info["part number"],
                                                           dimm_info.get('part_number', 'HMA82GR7AFR8N-VK'))
            else:
                info["total width"] = 0
                info["data width"] = 0
                info["size"] = 0
                info["form factor"] = 2
                info["device set"] = 0
                info["device locator"] = 1
                info["ban locator"] = 2
                info["memory type"] = 2
                info["type detail"] = 0
                info["speed"] = 0
                info["attributes"] = 0
                info["extended size"] = 0
                info["configured memory clock speed"] = 0

                info["manufactuer"] = self.__update_string(string_values, info["manufactuer"], "NO DIMM")
                info["sn"] = self.__update_string(string_values, info["sn"], "NO DIMM")
                info["asset tag"] = self.__update_string(string_values, info["asset tag"], "NO DIMM")
                info["part number"] = self.__update_string(string_values, info["part number"], "NO DIMM")

            idx = target["idx"]
            # pack modified data and save it
            self.__dict[idx] = self._pack_table(mem_info_fmt, info, string_values)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('src')
    args = parser.parse_args()

    smbios = SMBios(args.src)
    smbios.decode_type0()
