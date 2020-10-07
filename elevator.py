from components.pca9685pw import PCA9685PW
import smbus
import time

class Elevator(object):
    def __init__(self, i2c_bus, PCA9685_i2c_address, dc_motor_pwm_frequency):
        self.pwm = PCA9685PW(i2c_bus, PCA9685_i2c_address, dc_motor_pwm_frequency)
        self.r_en_ch = 0 # (high) Enable rotating clockwise / Elevator goes up
        self.l_en_ch = 1 # and counterclockwise / Elevator goes down
        self.r_pwm_ch = 2 # Controlling rotating speed by PWM value for clockwise direction
        self.l_pwm_ch = 3

    # TODO: calibrate speed, then calc path from speed*time
    def move_down(self, speed, time):
        self.pwm.reset()
        self.pwm.set_off(self.l_pwm_ch)
        self.pwm.set_percent(self.r_pwm_ch, speed)
        time.sleep(time)

    def move_up(self, speed, time):
        self.pwm.reset()
        self.pwm.set_off(self.r_pwm_ch)
        self.pwm.set_percent(self.l_pwm_ch,speed)
        time.sleep(time)
