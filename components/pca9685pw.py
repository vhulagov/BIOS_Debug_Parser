import smbus
import time
import random

class PCA9685PW(object):
    def __init__(self, bus, address, pwm_frequency):
        self.defaultBus = bus
        self.defaultAddress = address
        self.bus = smbus.SMBus(bus)

        self.pca9685Mode1 = 0x0
        self.pca9685Mode2 = 0x1
        self.pca9685PreScale = 0xfe
        self.pca9685OutDrv = 0x2
        self.pca9685OutDrvOpenDrain = 0
        self.pca9685OutDrvTotemPole = 1

        self.ledBlockSize = 4

        self.led0OnL = 6
        self.led0OnH = 7
        self.led0OffL = 8
        self.led0OffH = 9

        self.ledFull = 0x10 # bit4 used to set full On/Off
        self.ledMaxOn = 4096-1.0 #0 based counter

    def reset(self):
        self.bus.write_byte_data(self.defaultAddress, self.pca9685Mode1, 0)

    def prescale_from_frequency(self, freq):
        return int(round((25000000.0/(4096*freq))-1))

    def read_byte_data(self, register):
        return self.bus.read_byte_data(self.defaultAddress, register)

    def write_byte_data(self, register, value):
        self.bus.write_byte_data(self.defaultAddress, register, value)
    
    def set_frequency(self, freq):
        print(freq)
        prescalevalue = self.prescale_from_frequency(freq)
        oldmode = self.read_byte_data(self.pca9685Mode1)
        newmode = oldmode&0x7f|0x10
        self.write_byte_data(self.pca9685Mode1, newmode)
        self.write_byte_data(self.pca9685PreScale, prescalevalue)
        self.write_byte_data(self.pca9685Mode1, oldmode)
        time.sleep(0.005) #5 miliseconds
        self.write_byte_data(self.pca9685Mode1, (oldmode | 0x80)) #set restart bit (causes remembering where was when off)

    def set_times(self, ledNum, onTime, offTime):
        print ledNum, onTime, offTime
        ledOnL = self.led0OnL + self.ledBlockSize * ledNum
        ledOnH = self.led0OnH + self.ledBlockSize * ledNum
        ledOffL = self.led0OffL + self.ledBlockSize * ledNum
        ledOffH = self.led0OffH + self.ledBlockSize * ledNum
        onTimeL = onTime & 0xff
        onTimeH = onTime >> 8
        offTimeL = offTime & 0xff
        offTimeH = offTime >> 8
        #print ledOnL, ledOnH, ledOffL, ledOffH
        #print onTimeL, onTimeH, offTimeL, offTimeH
        self.write_byte_data(ledOnL, onTimeL)
        self.write_byte_data(ledOnH, onTimeH)
        self.write_byte_data(ledOffL, offTimeL)
        self.write_byte_data(ledOffH, offTimeH)

    def get_times(self, ledNum):
        ledOnL = self.led0OnL + self.ledBlockSize * ledNum
        ledOnH = self.led0OnH + self.ledBlockSize * ledNum
        ledOffL = self.led0OffL + self.ledBlockSize * ledNum
        ledOffH = self.led0OffH + self.ledBlockSize * ledNum
        onTimeL = self.read_byte_data(ledOnL)
        onTimeH = self.read_byte_data(ledOnH)
        offTimeL = self.read_byte_data(ledOffL)
        offTimeH = self.read_byte_data(ledOffH)
        #print ledOnL, ledOnH, ledOffL, ledOffH
        #print onTimeL, onTimeH, offTimeL, offTimeH
        print bin(onTimeL), bin(onTimeH), bin(offTimeL), bin(offTimeH)
    
    def set_on(self, ledNum):
        print 'On', ledNum
        ledOnL = self.led0OnL + self.ledBlockSize * ledNum
        ledOnH = self.led0OnH + self.ledBlockSize * ledNum
        ledOffL = self.led0OffL + self.ledBlockSize * ledNum
        ledOffH = self.led0OffH + self.ledBlockSize * ledNum
        self.write_byte_data(ledOnL, 0)
        self.write_byte_data(ledOnH, self.ledFull)
        self.write_byte_data(ledOffL, 0)
        self.write_byte_data(ledOffH, 0)

    def set_off(self, ledNum):
        print 'Off', ledNum
        ledOnL = self.led0OnL + self.ledBlockSize * ledNum
        ledOnH = self.led0OnH + self.ledBlockSize * ledNum
        ledOffL = self.led0OffL + self.ledBlockSize * ledNum
        ledOffH = self.led0OffH + self.ledBlockSize * ledNum
        self.write_byte_data(ledOnL, 0)
        self.write_byte_data(ledOnH, 0)
        self.write_byte_data(ledOffL, 0)
        self.write_byte_data(ledOffH, self.ledFull)
    
    def set_percent(self, ledNum, percentOn):
        print 'set_percent', ledNum, percentOn
        timeOn = int((percentOn/100.0)*self.ledMaxOn)
        if timeOn == 0:
            return self.set_off(ledNum)
        if timeOn == self.ledMaxOn:
            return self.set_on(ledNum)
        maxLeadIn = self.ledMaxOn - timeOn
        start = 0 #random.randint(0, maxLeadIn)
        stop = start+timeOn
        self.set_times(ledNum, start, stop)

    def set_colour(self, ledNum, red, green, blue):
        print 'Colour: ', red, green, blue
        self.set_percent(ledNum, (red/255.0*100))
        self.set_percent(ledNum+1, (green/255.0*100))
        self.set_percent(ledNum+2, (blue/255.0*100))

    def get_percent(self, ledNum):
        ledOnL = self.led0OnL + self.ledBlockSize * ledNum
        ledOnH = self.led0OnH + self.ledBlockSize * ledNum
        ledOffL = self.led0OffL + self.ledBlockSize * ledNum
        ledOffH = self.led0OffH + self.ledBlockSize * ledNum
        onTimeL = self.read_byte_data(ledOnL)
        onTimeH = self.read_byte_data(ledOnH)
        offTimeL = self.read_byte_data(ledOffL)
        offTimeH = self.read_byte_data(ledOffH)
        if (onTimeH == self.ledFull):
            print 'get_percent', 100
            return 100
        if (offTimeH == self.ledFull):
            print 'get_percent', 0
            return 0
        startOnTime = (onTimeH<<8) + onTimeL
        startOffTime = (offTimeH<<8) + offTimeL
        startTimeOn = startOffTime - startOnTime
        percentOn = 100*(startTimeOn/self.ledMaxOn)
        print 'get_percent', percentOn
        return percentOn

    def fade_to_colour(self, ledNum, red, green, blue):
        steps = 100
        totalTime = 2.0
        startRed = self.get_percent(ledNum)
        startGreen = self.get_percent(ledNum+1)
        startBlue = self.get_percent(ledNum+2)
        endRed = (red/255.0*100)
        endGreen = (green/255.0*100)
        endBlue = (blue/255.0*100)
        redDiff = endRed - startRed
        greenDiff = endGreen - startGreen
        blueDiff = endBlue - startBlue
        print 'start', startRed, startGreen, startBlue
        print 'end', endRed, endGreen, endBlue
        for i in range(0, steps):
            self.set_percent(ledNum, startRed+(redDiff/steps)*i)
            self.set_percent(ledNum+1, startGreen+(greenDiff/steps)*i)
            self.set_percent(ledNum+2, startBlue+(blueDiff/steps)*i)
            time.sleep(totalTime/steps)
        self.set_colour(ledNum, red, green, blue)

    def fade_to_state(self, ledNum, goal):
        steps = 100
        totalTime = 20.0
        startState = self.get_percent(ledNum)
        endState = (goal/255.0*100)
        StateDiff = endState - startState
        print 'start', startState
        print 'end', endState
        for i in range(0, steps):
            self.set_percent(ledNum, startState+(StateDiff/steps)*i)
            time.sleep(totalTime/steps)
