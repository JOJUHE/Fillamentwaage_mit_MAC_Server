# This file is executed on every boot (including wake-boot from deepsleep)
#import esp
#esp.osdebug(None)
#import webrepl


from machine import Pin, UART, WDT
import time
import os
import neopixel

SAFE_PIN = Pin(0, Pin.IN, Pin.PULL_UP)   # BOOT-Taste = GPIO 0
np = neopixel.NeoPixel(Pin(48), 1)       # Onboard-Neopixel ESP32-S3


time.sleep(2)  # Zeit zum Drücken der BOOT-Taste
# Wenn Pin 0 gedrückt → Safe-Mode aktivieren
if SAFE_PIN.value() == 0:
    np[0] = (5, 0, 0)   # Rot = Safe Mode
    np.write()        
    print("SAFE MODE aktiviert – main.py wird NICHT gestartet")
    while True:
        utime.sleep_ms(1000)    
else:
    np[0] = (0, 5, 0)    # Grün = Normalstart
    np.write()
    # Wenn wir hier sind → Normalstart
    # Watchdog aktivieren
    # wdt = WDT(timeout=20000)
    print("Watchdog aktiviert")    
    