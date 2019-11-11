#!/usr/bin/env python

import sys
import signal
import io

from contextlib import contextmanager
from select import select

from pyghmi.ipmi import console

#from hwlib.common import ignored
@contextmanager
def ignored(*exceptions):
    """Elegant ignoring of exceptions using with statement"""
    try:
        yield
    except exceptions:
        pass

#from hwlib.strtools import isplitlines, only_ascii
def isplitlines(lines, keepends=False):
    """Iterator implementation of str/bytes/bytearray splitlines method"""
    if isinstance(lines, (bytearray, bytes)):
        delim, extra_delim = (b'\n', b'\r')
    else:
        delim, extra_delim = ('\n', '\r')
    prev_pos = 0
    with ignored(ValueError):
        while True:
            pos = lines.index(delim, prev_pos)
            end_pos = pos
            if keepends:
                end_pos += 1
            elif pos > 0 and lines[pos-1] == extra_delim:
                end_pos -= 1
            yield lines[prev_pos:end_pos]
            prev_pos = pos+1
    if prev_pos < len(lines):
        line = lines[prev_pos:]
        yield line if keepends else line.rstrip(delim + extra_delim)

class SOL:
    def __init__(self, bmc):
        self.bmc = bmc 
        self.sol_data = bytearray()
        # Timeout for SOL session
        self.sol_timeout = 600
        # Timeout for data stream
        self.data_timeout = 0.01
        self.sol_data_lines = list()
        self.sol_session = console.Console(bmc=self.bmc, userid='ADMIN', password='ADMIN',
                               iohandler=self.put_data, force=True)

#    def read_stream(self, stream):
#        readable = select([stream], [], [], self.timeout)[0]
#        try:
#            return readable[0].read() if readable else b''
#        except IOError:
#            return b''

    def try_to_decode(self, output):
        """Convert bytes to acsii string by all means"""
        try:
            return output.decode('utf8')
        except (UnicodeDecodeError, UnicodeEncodeError):
            return only_ascii(output)

    def put_data(self, data):
        #self.sol_data += self.read_stream(data)
        self.sol_data += data
 
    def get_data(self):
        line = ''
        while True:
            if self.waitdata():
                #print('There is must be some data here...')
                n_full_lines = self.sol_data.count(b'\n')
                if n_full_lines:
                    line_iter = isplitlines(self.sol_data)
                    for line_index, line in enumerate(line_iter):
                        if line_index >= n_full_lines:
                            self.sol_data = line
                            break
                        yield self.try_to_decode(line)
                    else:
                        # hack to clear existing bytearray
                        self.sol_data[:] = b''
                    
    def waitdata(self):
        return not self.sol_session.wait_for_rsp(timeout=600)

    def close(self):
        return self.sol_session.close()


def main():
     bios_dbg_data = ''
     try:
         sol = SOL(sys.argv[1])
         try:
             def signal_handler(sig, frame):
                 sol.close()
                 sys.exit(0)

             signal.signal(signal.SIGINT, signal_handler)
             bios_dbg_data = sol.get_data()

             for line in bios_dbg_data:
                 #print("You can parse this line now: " + str(line))
                 print(line)
                 #process(line)
                 #...
         except Exception as e:
             print('SOL pipeline fails: ' + str(e))
             sol.close()
     except Exception as e:
         print('SOL initialisation fails: ' + str(e))
         print(str(e))


if __name__ == '__main__':
     sys.exit(main())

# vim: tabstop=8 softtabstop=0 expandtab shiftwidth=4 smarttab
