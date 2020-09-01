import re
import glob

def find_tiny_usb_i2c_gate():
    I2C_BUS_DEV_NAME_RE = re.compile(r'i2c-tiny-usb')
    i2c_bus_sys_path_list = glob.glob("/sys/class/i2c-dev/*/name")
    for bus_sys_path in i2c_bus_sys_path_list:
#        print("Founded i2c bus path:" + str(bus_sys_path))
        if I2C_BUS_DEV_NAME_RE.match(open(bus_sys_path, 'r').read()):
            i2c_bus_id = int(re.sub(r'/sys/class/i2c-dev/i2c-([0-9])/name', r"\1", bus_sys_path))
            #i2c_bus_id = int(re.sub(r'i2c-([0-9])', r"\1", bus_sys_path.split('/')[4]))
#            print("Matched i2c bus id:" + str(i2c_bus_id))
            return i2c_bus_id
        else:
            if i2c_bus_sys_path_list[:-1] == bus_sys_path:
                return -1
