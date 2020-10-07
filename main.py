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
import cv2

import smbus
import serial

from components.ina219 import INA219
from components.pca9685pw import PCA9685PW

from elevator import Elevator

I2C_BUS_DEV_NAME_RE = re.compile(r'i2c-tiny-usb')

pca9685pw_addr = 0x40 # Address pins [1][A5][A4][A3][A2][A1][A0]
dc_motor_ina219_addr = 0x41 # Address pins [1][0][0][0][0][A0][A1]

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


def action():
        # Press Esc on keyboard to exit
        key = cv2.waitKey(25)
        if key == 27:
            print("Interrupt")
            break
        elif k == -1:  # normally -1 returned,so don't print it
            continue

        elif key == 82 # UP

        elif key == 84 # DOWN

        elif key == 81 # LEFT

        elif key == 83 # RIGHT

        elif key == ord('e'):
            print('e')

        elif key & 0xFF == ord('w'):
            print('w')

if __name__ == '__main__':
    logger.info('******************************************')
    logger.info('Starting up...')
    i2c_bus_id = find_tiny_usb_i2c_gate()
    if i2c_bus_id is None or type(i2c_bus_id) is not int:
        logger.error("I2C bus is not found!")
        sys.exit(1)
    logger.info("Founded USB-I2C gate on bus: " + str(i2c_bus_id))

    elevator = Elevator(i2c_bus_id, pca9685pw_addr, dc_motor_pwm_frequency)
    dc_motor_meas = INA219(dc_motor_ina219_addr, i2c_bus_id)

    # TODO move to thread/subprocess
    try:
        print('BusVoltage (in Volts) =', dc_motor_meas.getLoadVoltage())
        print('ShuntVoltage (in Volts) =', dc_motor_meas.getShuntVoltage())
        if regs[5] != 0:
            print('LoadCurrent (in Amps) =', dc_motor_meas.getLoadCurrent())
            print('LoadPower (in Watts) =', dc_motor_meas.getPowerUsed())
    except OSError:
        print('Connection to INA219 failed.')
        sys.exit(121)

    # Capturing — 1. detects object and translate distance betwen object
    # Sensing — 2. capture sensor values
    # Acting — control motors and other actuators
    capturing_q = multiprocessing.Queue()
    sensing_q = multiprocessing.Queue()
    acting_q = multiprocessing.Queue()
        
    multiprocessing.Process(target=see, args=(eye_q, memorize_q)).start()
    multiprocessing.Process(target=learn, args=(memorize_q, brain_q)).start()
    multiprocessing.Process(target=display, args=(eye_q, brain_q)).start()


    try:
        raw_input('')
    except KeyboardInterrupt:
        map(lambda x: x.terminate(), multiprocessing.active_children())


# vim: tabstop=8 softtabstop=0 expandtab shiftwidth=4 smarttab
