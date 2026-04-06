# =========================================================
# HX711 – MicroPython Treiber für ESP32-S3
# DOUT = GPIO 4  |  SCK = GPIO 5
# =========================================================

from machine import Pin
import utime

class HX711:
    def __init__(self, dout=4, sck=5, gain=128):
        self.pDOUT = Pin(dout, Pin.IN, Pin.PULL_DOWN)
        self.pSCK  = Pin(sck,  Pin.OUT)
        self.pSCK.value(0)
        self.OFFSET = 0
        self.SCALE  = 1.0
        self.GAIN   = 0
        self.set_gain(gain)
        print("[HX711] Initialisiert – DOUT:{} SCK:{}".format(dout, sck))

    def set_gain(self, gain):
        if gain == 128:
            self.GAIN = 1   # Kanal A, Gain 128
        elif gain == 64:
            self.GAIN = 3   # Kanal A, Gain 64
        elif gain == 32:
            self.GAIN = 2   # Kanal B, Gain 32
        else:
            raise ValueError("Ungültiger Gain: {}".format(gain))
        self._read_raw()   # Einmal lesen um Gain zu setzen

    def is_ready(self):
        return self.pDOUT.value() == 0

    def _read_raw(self):
        # Warten bis Daten bereit
        timeout = 0
        while not self.is_ready():
            utime.sleep_ms(1)
            timeout += 1
            if timeout > 1000:
                print("[HX711] Timeout – kein Signal!")
                return 0

        data = 0
        for _ in range(24):
            self.pSCK.value(1)
            utime.sleep_us(1)
            data = (data << 1) | self.pDOUT.value()
            self.pSCK.value(0)
            utime.sleep_us(1)

        # Gain-Pulse für nächste Messung setzen
        for _ in range(self.GAIN):
            self.pSCK.value(1)
            utime.sleep_us(1)
            self.pSCK.value(0)
            utime.sleep_us(1)

        # 24-Bit 2er-Komplement → vorzeichenbehaftet
        if data & 0x800000:
            data -= 0x1000000

        return data

    def read_average(self, times=10):
        """Mehrfach messen und Mittelwert bilden (Ausreißer werden entfernt)."""
        vals = [self._read_raw() for _ in range(times)]
        vals.sort()
        if len(vals) > 4:
            vals = vals[2:-2]  # obere + untere 2 Ausreißer entfernen
        return sum(vals) / len(vals)

    def tare(self, times=15):
        """Tarieren – aktuelles Gewicht als Nullpunkt speichern."""
        self.OFFSET = self.read_average(times)
        print("[HX711] Tara gesetzt, OFFSET = {:.0f}".format(self.OFFSET))

    def get_raw(self):
        return self._read_raw() - self.OFFSET

    def get_grams(self, times=5):
        """Gewicht in Gramm zurückgeben."""
        if self.SCALE == 1.0:
            return None  # Noch nicht kalibriert
        raw = self.read_average(times) - self.OFFSET
        return round(raw / self.SCALE, 1)

    def calibrate(self, known_weight_g, times=15):
        """
        Kalibrieren mit bekanntem Gewicht.
        Vorher tarieren! Dann Gewicht auflegen und diese Funktion aufrufen.
        """
        raw = self.read_average(times) - self.OFFSET
        if raw == 0:
            print("[HX711] Kalibrierung fehlgeschlagen – kein Signal")
            return None
        self.SCALE = raw / known_weight_g
        print("[HX711] Kalibriert: SCALE = {:.2f}  (raw={:.0f} / {}g)".format(
            self.SCALE, raw, known_weight_g))
        return self.SCALE

    def get_scale(self):
        return self.SCALE

    def set_scale(self, scale):
        self.SCALE = scale

    def set_offset(self, offset):
        self.OFFSET = offset

    def power_down(self):
        self.pSCK.value(0)
        self.pSCK.value(1)

    def power_up(self):
        self.pSCK.value(0)
        utime.sleep_ms(400)
