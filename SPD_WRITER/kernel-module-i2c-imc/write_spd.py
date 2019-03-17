#!/usr/bin/python

from smbus2 import SMBus, SMBusWrapper
import time
import os
import sys

i2c_bus_id = 8
spd_base_addr = 0x50          # EE1004 i2C spd_base_addr - A0, A1, A2 N/A Grounded
spd_page_selector_addr = 0x37 # Selects SPD page 1 (bytes 256-512) on all DIMMs
end_user_reg_offset = 0x80    # Offset of End User Programmable region (writable SPD segment #4) 
n_bytes = 127                 # Available space for test report data

dataset_file = './input.txt'

def read_file(file_name):
    '''Reads a file, and returns a formated list of accepted char '''
    try:
        # Gets file size of file
        size = os.path.getsize(file_name)
        print("Data size:" + str(size))
        # Check data size fits to available space
        if size > n_bytes:
            print("size of file is to big, please limit to 127 Bytes")
            sys.exit(9)
        my_file = open(file_name, "r")
        return char2_ascii(my_file)                      

    except Exception as e:
        raise

def ascii2_char(list_data):
    '''Function that converts a list of ascii to char '''
    data = []
    words = ""

    for i in range(0, len(list_data)):                  #iterates through data
        if 0<= list_data[i] <= 126:                     #ascii range (0-126)
            if list_data[i] == 10 and len(words) != "": #newline found append sentence
                data.append(words)
                words = ""
            else:                                       #regular char, build sentence
                words += chr(list_data[i])                  
        if i == len(list_data)-1 and words != "":       #end of file, add sentence
            data.append(words)
    return data

def char2_ascii(string_data):
    '''Function that converts list of chr to ascii '''
    ascii_values = []
    for sentence in string_data:
        for char in sentence:
            ascii_values.append(char.decode('ascii'))
            #ascii_values.append(ord(char))
    return ascii_values

def factory_reset(active=False):
    '''Resets ALL memory, use with caution '''
    if active == True:                                  #Safety, user must trigger
        #print("Reseting EEPROM: ETA 40.95 seconds")
        with SMBusWrapper(i2c_bus_id) as bus:
            bus.write_byte_data(spd_page_selector_addr, 0, 0)
            for byte in range(n_bytes):           
                if byte % 32 == 0:
                    current = 31 + byte
                    clsbyte = current & 0x00FF
                    cmsbyte = current >> 8
                    
                    lsbyte = byte & 0x00FF
                    msbyte = byte >> 8
                    writestring = [lsbyte] + [255]*31

                    bus.write_i2c_block_data(spd_base_addr, msbyte, writestring)
                    time.sleep(0.1)
                    bus.write_i2c_block_data(spd_base_addr, cmsbyte, [clsbyte, 255])
                    time.sleep(0.1)
                    #print('---0x{:4x} {}'.format(byte, byte))
                    #print('lo 0x{:4x} {}'.format(lsbyte, lsbyte))
                    #print('hi 0x{:4x} {}'.format(msbyte, msbyte))

    else:
        print("factory activity status set to false, no changes!")


def read(dev_addr=spd_base_addr, start_addr=end_user_reg_offset):
    ''' Returns a list of eeprom data read, within the normal ascii range (0-126)'''
    with SMBusWrapper(i2c_bus_id) as bus:
        eeprom_data = []                                #Holds read eeprom data
        bus.write_byte_data(spd_page_selector_addr, 0, 0)
        for value in range(end_user_reg_offset, n_bytes):         #Iterates through memory
            eeprom_data.append(bus.read_byte(spd_base_addr))  #Appends read byte
        #sentences = ascii2_char(eeprom_data)            #converts bytes to chr equiv
        #return sentences                                
        return eeprom_data


def read_all():
    '''Reads all eeprom data and returns list as ascii code'''
    with SMBusWrapper(i2c_bus_id) as bus:
        data = []                                       #Holds read eeprom data
        bus.write_byte_data(spd_page_selector_addr, 0,0)               
        for value in range(0, 0xFF):                    #Iterates through memory
            data.append(bus.read_byte(spd_base_addr))
        return data


def write(dev_addr, start_addr, dataset):
    data = []
    #dataset_ascii = dataset.decode('ascii') 
    print(dataset)
    with SMBusWrapper(i2c_bus_id) as bus:
        print("Selecting 2-nd page for accessing SPD upper 256 bytes...")
        bus.write_byte_data(spd_page_selector_addr, 0, 0)
        for byte in range(len(dataset)):
            print("Writing byte #" + str(byte))
            #if byte % 32 == 0 and byte > 0:
            if byte > 0:
                print(byte)
                lsbyte = byte & 0x00FF
                msbyte = byte >> 8
                print(data)
                #import pdb; pdb.set_trace()
                writestring = [lsbyte] + data[0:len(data)-1]
                print("WRITESTRING:")
                print(msbyte, len(writestring))
                bus.write_i2c_block_data(spd_base_addr, msbyte, writestring)
                time.sleep(0.1)

                current = (byte - 1) + 32
                clsbyte = current & 0x00FF
                cmsbyte = current >> 8
                print(current, clsbyte, cmsbyte, chr(data[len(data)-1]) )
                
                writestring = [clsbyte] + [data[len(data)-1]]
                print(writestring, len(writestring))
                #import pdb; pdb.set_trace()
                
                bus.write_i2c_block_data(spd_base_addr, cmsbyte, writestring)
                time.sleep(0.1)
                data = []

            data.append(dataset[byte])


#############################################################################

dataset_raw = read_file(dataset_file)
#factory_reset(True)                    #Resets eeprom
        
print(read())                           #returns readable eeprom data as list

write(spd_base_addr, end_user_reg_offset, dataset_raw)

#print(read_all())                      #returns all eeprom data as list
print(read())                      #returns all eeprom data as list
