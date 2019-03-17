#!/usr/bin/env python
# -*- coding: utf-8 -*-

#
# This program runs 
#

import os
import sys, inspect
import time
import glob

import logging
import re

import smbus
import serial

from components.ina219 import INA219
from components.pca9685pw import PCA9685PW

from elevator import Elevator

I2C_BUS_DEV_NAME_RE = re.compile(r'i2c-tiny-usb')

pca9685pw_addr = 0x40 # Address pins [1][A5][A4][A3][A2][A1][A0]
motor_ina219_addr = 0x41 # Address pins [1][0][0][0][0][A0][A1]

dc_motor_pwm_frequency = 100 # Hertz 64 recomended for Servos

logging.basicConfig(
    level=logging.DEBUG,
    format='[%(asctime)s] {%(filename)s:%(lineno)d} %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger()

def find_tiny_usb_i2c_gate():
    i2c_bus_sys_path_list = glob.glob("/sys/class/i2c-dev/*/name")
    for bus_sys_path in i2c_bus_sys_path_list:
        logger.debug("Founded i2c bus path:" + str(bus_sys_path))
        if I2C_BUS_DEV_NAME_RE.match(open(bus_sys_path, 'r').read()):
            i2c_bus_id = int(re.sub(r'/sys/class/i2c-dev/i2c-([0-9])/name', r"\1", bus_sys_path))
            #i2c_bus_id = int(re.sub(r'i2c-([0-9])', r"\1", bus_sys_path.split('/')[4]))
            logger.debug("Matched i2c bus id:" + str(i2c_bus_id))
            return i2c_bus_id
        else:
            if i2c_bus_sys_path_list[:-1] == bus_sys_path:
                return -1

if __name__ == '__main__':
    logger.info('******************************************')
    logger.info('Starting up...')
    i2c_bus_id = find_tiny_usb_i2c_gate()
    if i2c_bus_id is None or type(i2c_bus_id) is not int:
        logger.error("I2C bus is not found!")
        exit(1)
    logger.info("Founded USB-I2C gate on bus: " + str(i2c_bus_id))

    elevator = Elevator(i2c_bus_id, pca9685pw_addr, dc_motor_pwm_frequency)

# vim: tabstop=8 softtabstop=0 expandtab shiftwidth=4 smarttab
