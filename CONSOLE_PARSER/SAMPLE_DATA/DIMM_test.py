import unittest
import pca9685pw
import smbus
import time

bus = 8
address = 0b1000000 #address pins [1][A5][A4][A3][A2][A1][A0]
frequency = 600 #hertz 64 recomended for Servos

class TestPCM(unittest.TestCase):

    def test_smbus(self):
        pwm = pca9685pw.Pca9685pw(8,bus,address)
        self.assertIsInstance(pwm, pca9685pw.Pca9685pw)
        self.assertIsInstance(pwm.bus, smbus.SMBus)

    def test_address(self):
        pwm = pca9685pw.Pca9685pw(8,bus,address)
        pwm.defaultBus = bus
        pwm.defaultAddress = address
        self.assertTrue(pwm.defaultAddress == address)

    def test_reset(self):
        pwm = pca9685pw.Pca9685pw(8,bus,address)
        pwm.defaultBus = bus
        pwm.defaultAddress = address
        pwm.reset()

#    def test_setFrequency(self):
#        pwm = pca9685pw.Pca9685pw()
#        pwm.defaultAddress = address
#        pwm.setFrequency(frequency)

#    def test_setTimes(self):
#        pwm = pca9685pw.Pca9685pw(8,bus,address)
#        pwm.setFrequency(frequency)
#        pwm.reset()
#        for i in range(0,16):
#          if ( i % 2 ):
#            value = 4000
#          else:
#            value = 000
#          pwm.setTimes(i,value,4030)
#
#    def test_getTimes(self):
#        pwm = pca9685pw.Pca9685pw()
#        pwm.defaultAddress = address
#        for i in range(0,16):
#          pwm.getTimes(i)

    def test_setPercent(self):
        pwm = pca9685pw.Pca9685pw()
        pwm.defaultAddress = address
        pwm.setFrequency(frequency)
        pwm.reset()
        for i in range(0,16):
          pwm.setFullOff(i)
        pwm.setPercent(4,4)
#        for i in range(0,16):
#          pwm.setPercent(i,4)

#    def test_fadeToState(self):
#        pwm = pca9685pw.Pca9685pw(8,bus,address)
#        pwm.defaultAddress = address
#        pwm.setFrequency(frequency)
#        pwm.setPercent(1,4)
#        pwm.fadeToState(1,255)
#        pwm.fadeToState(1,0)
#        for i in range(0,16):
#          pwm.setFullOff(i)
#
#    def test_fadeRainbow(self):
#        pwm = pca9685pw.Pca9685pw()
#        pwm.defaultAddress = address
#        pwm.setFrequency(frequency)
#        pwm.reset()
#        pwm.setColour(0,255,0,0)
#        pwm.fadeToColour(0,255,128,0)
#        pwm.fadeToColour(0,246,255,0)
#        pwm.fadeToColour(0,0,255,0)
#        pwm.fadeToColour(0,0,0,255)
#        pwm.fadeToColour(0,140,0,255)

if __name__ == '__main__':
    unittest.main()
