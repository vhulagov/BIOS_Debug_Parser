global LED_EXISTENCE

# Led highlighting is turned off by default
LED_EXISTENCE = False

init_leds():
    # For LED highlighting using PCA9685
    import smbus
    import pca9685pw

    # Settings for PCA9685
    PCA9685_I2C_BUS = 8 # bus id
    PCA9685_I2C_ADDRESS = 0b1000000 # address pins [1][A5][A4][A3][A2][A1][A0]
    LED_PWM_FREQ = 600 # hertz 64 recomended for Servos

    # For single socket platform
    LED_DIMM_MATCH_TABLE = {
        '0.0.0' : 0,
        '0.0.0' : 0,
        '0.0.1' : 2,
        '0.0.1' : 2,
        '0.1.0' : 4,
        '0.1.0' : 4,
        '0.1.1' : 6,
        '0.1.1' : 6,
        '0.2.0' : 8,
        '0.2.0' : 8,
        '0.2.1' : 10,
        '0.2.1' : 10,
        '0.3.0' : 12,
        '0.3.0' : 12,
        '0.3.1' : 14,
        '0.3.1' : 1
    }

    pwm = pca9685pw.Pca9685pw(8,PCA9685_I2C_BUS,PCA9685_I2C_ADDRESS)
    pwm.defaultAddress = PCA9685_I2C_ADDRESS
    pwm.setFrequency(LED_PWM_FREQ)
    pwm.reset()
    LED_EXISTENCE = True
    for i in range(0,16):
      pwm.setFullOff(i)

def ident_dimm(device_rank, state):
    global LED_EXISTENCE
    if LED_EXISTENCE:
        severity_mapping = {
            'critical' : 100,
            'warning' : 20,
            }
        led_id = LED_DIMM_MATCH_TABLE[device_rank]
        if severity_mapping[state]:
            pwm = pca9685pw.Pca9685pw(8,PCA9685_I2C_BUS,PCA9685_I2C_ADDRESS)
            pwm.setPercent(led_id,severity_mapping[state])
        else:
            print("Can't find leds for highlighting failed DIMM")


