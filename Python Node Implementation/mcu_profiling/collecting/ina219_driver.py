from machine import I2C, Pin
import time

class INA219:
    def __init__(self, i2c, addr=0x40):
        self.i2c = i2c
        self.addr = addr
        self._cal_value = 0
        self._current_lsb = 0
        self._power_lsb = 0
        self.set_calibration_32V_2A()

    def _write(self, register, data):
        self.i2c.writeto_mem(self.addr, register, bytes([data >> 8, data & 0xFF]))

    def _read(self, register):
        data = self.i2c.readfrom_mem(self.addr, register, 2)
        return int.from_bytes(data, 'big')

    def set_calibration_32V_2A(self):
        self._current_lsb = 0.1  # mA
        self._power_lsb = 2.0    # mW
        self._cal_value = 4096
        self._write(0x05, self._cal_value)
        # Config register: 32V range, Gain 8 (320mV), 12bit bus, 12bit shunt, Continuous
        self._write(0x00, 0x399F)

    def get_shunt_voltage(self):
        val = self._read(0x01)
        if val > 32767: val -= 65536
        return val * 0.01 # mV

    def get_bus_voltage(self):
        val = self._read(0x02)
        return (val >> 3) * 0.004 # V

    def get_current(self):
        # Sometimes needs re-calibration if power cycled
        # self._write(0x05, self._cal_value) 
        raw = self._read(0x04)
        if raw > 32767: raw -= 65536
        return raw * self._current_lsb # mA