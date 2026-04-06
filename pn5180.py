# =========================================================
# PN5180 – MicroPython Treiber fuer ESP32-S3
# ISO 15693 (NFC-V) fuer ICODE SLIX / SLIX2 Tags
#
# Pinbelegung:
#   MOSI  = GPIO 35
#   MISO  = GPIO 37
#   SCK   = GPIO 36
#   NSS   = GPIO 10  (Chip Select, aktiv LOW)
#   BUSY  = GPIO 38  (HIGH = beschaeftigt)
#   RST   = GPIO 39
#   VCC   = 3.3V     (Logik)
#   VDDPA = 5V       (HF-Antenne!)
#   GND   = GND
#
# Bugfixes gegenueber Original:
#   1. RF_ON benoetigt Parameter-Byte: [0x16, 0x00] statt [0x16]
#      -> Ohne 0x00 ignoriert der Chip den Befehl komplett
#   2. SYSTEM_CONFIG = IDLE nach Reset (beendet LPCD-Modus)
#   3. TRANSCEIVE vor SEND_DATA aktivieren
#   4. TIMER1 manuell setzen (LOAD_RF_CONFIG setzt ihn nicht)
#   5. CRC_TX manuell setzen (LOAD_RF_CONFIG setzt ihn nicht)
#   6. Korrekte BUSY-Behandlung: HIGH->LOW nach jedem Befehl
# =========================================================

from machine import Pin, SPI
import utime

class PN5180:
    VERSION = "1.4.0"  # 1.4: inventory UID fix data[2:10], CLR IRQ fix
    CMD_WRITE_REGISTER          = 0x00
    CMD_WRITE_REGISTER_OR_MASK  = 0x01
    CMD_WRITE_REGISTER_AND_MASK = 0x02
    CMD_READ_REGISTER           = 0x04
    CMD_SEND_DATA               = 0x09
    CMD_READ_DATA               = 0x0A
    CMD_LOAD_RF_CONFIG          = 0x11
    CMD_RF_ON                   = 0x16
    CMD_RF_OFF                  = 0x17

    REG_SYSTEM_CONFIG          = 0x00
    REG_IRQ_ENABLE             = 0x01
    REG_IRQ_STATUS             = 0x02
    REG_IRQ_CLEAR              = 0x03
    REG_RX_STATUS              = 0x13
    REG_CRC_RX_CONFIG          = 0x12
    REG_CRC_TX_CONFIG          = 0x1B
    REG_TIMER1_RELOAD          = 0x0C
    REG_TIMER1_CONFIG          = 0x0F
    REG_RF_STATUS              = 0x1D
    REG_SYSTEM_STATUS          = 0x24

    ISO15693_REQ_FLAG_DATARATE    = 0x02
    ISO15693_REQ_FLAG_INVENTORY   = 0x04
    ISO15693_REQ_FLAG_ADDRESS     = 0x20
    ISO15693_REQ_FLAG_OPTION      = 0x40

    ISO15693_CMD_INVENTORY        = 0x01
    ISO15693_CMD_READ_SINGLE      = 0x20
    ISO15693_CMD_WRITE_SINGLE     = 0x21
    ISO15693_CMD_READ_MULTIPLE    = 0x23
    ISO15693_CMD_GET_SYSTEM_INFO  = 0x2B

    OK      = 0
    ERR     = 1
    NOTAG   = 2
    TIMEOUT = 3

    def __init__(self, mosi=35, miso=37, sck=36, nss=10, busy=38, rst=39):
        self.nss  = Pin(nss,  Pin.OUT, value=1)
        self.busy = Pin(busy, Pin.IN)
        self.rst  = Pin(rst,  Pin.OUT, value=1)
        self.spi  = SPI(1, baudrate=2_000_000, polarity=0, phase=0,
                        sck=Pin(sck), mosi=Pin(mosi), miso=Pin(miso))
        self._reset()
        self._init_rf_iso15693()
        print("[PN5180] v{} Initialisiert – ISO 15693 bereit".format(self.VERSION))

    # ----------------------------------------------------------
    # BUSY Handling
    # ----------------------------------------------------------

    def _wait_busy_low(self, timeout_ms=500):
        end = utime.ticks_add(utime.ticks_ms(), timeout_ms)
        while self.busy.value():
            if utime.ticks_diff(end, utime.ticks_ms()) <= 0:
                return False
            utime.sleep_us(20)
        return True

    def _wait_busy_cycle(self):
        end = utime.ticks_add(utime.ticks_ms(), 5)
        while not self.busy.value():
            if utime.ticks_diff(end, utime.ticks_ms()) <= 0:
                break
            utime.sleep_us(10)
        self._wait_busy_low(300)

    # ----------------------------------------------------------
    # SPI
    # ----------------------------------------------------------

    def _spi_send(self, data):
        self._wait_busy_low()
        self.nss.value(0); utime.sleep_us(2)
        self.spi.write(bytearray(data))
        utime.sleep_us(2); self.nss.value(1); utime.sleep_us(5)
        self._wait_busy_cycle()

    def _spi_read(self, cmd_bytes, recv_len):
        self._wait_busy_low()
        self.nss.value(0); utime.sleep_us(2)
        self.spi.write(bytearray(cmd_bytes))
        utime.sleep_us(2); self.nss.value(1); utime.sleep_us(5)
        self._wait_busy_cycle()
        self._wait_busy_low()
        self.nss.value(0); utime.sleep_us(2)
        buf = bytearray(recv_len)
        self.spi.readinto(buf)
        utime.sleep_us(2); self.nss.value(1)
        return buf

    # ----------------------------------------------------------
    # Register
    # ----------------------------------------------------------

    def _write_reg(self, reg, value):
        self._spi_send([self.CMD_WRITE_REGISTER, reg,
                        value&0xFF, (value>>8)&0xFF,
                        (value>>16)&0xFF, (value>>24)&0xFF])

    def _write_reg_or(self, reg, mask):
        self._spi_send([self.CMD_WRITE_REGISTER_OR_MASK, reg,
                        mask&0xFF, (mask>>8)&0xFF,
                        (mask>>16)&0xFF, (mask>>24)&0xFF])

    def _write_reg_and(self, reg, mask):
        self._spi_send([self.CMD_WRITE_REGISTER_AND_MASK, reg,
                        mask&0xFF, (mask>>8)&0xFF,
                        (mask>>16)&0xFF, (mask>>24)&0xFF])

    def _read_reg(self, reg):
        buf = self._spi_read([self.CMD_READ_REGISTER, reg], 4)
        return buf[0]|(buf[1]<<8)|(buf[2]<<16)|(buf[3]<<24)

    def _clear_irq(self):
        self._write_reg(self.REG_IRQ_CLEAR, 0xFFFFFFFF)

    def _idle(self):
        self._write_reg_and(self.REG_SYSTEM_CONFIG, 0xFFFFFFF8)

    # ----------------------------------------------------------
    # Init
    # ----------------------------------------------------------

    def _reset(self):
        self.rst.value(0); utime.sleep_ms(10)
        self.rst.value(1); utime.sleep_ms(100)
        self._wait_busy_low(500)
        self._write_reg(self.REG_SYSTEM_CONFIG, 0x00)  # IDLE, beendet LPCD
        self._clear_irq()
        print("[PN5180] Reset OK")

    def _init_rf_iso15693(self):
        self._spi_send([self.CMD_LOAD_RF_CONFIG, 0x0D, 0x8D])
        utime.sleep_ms(10)
        # FIX: CRC und Timer manuell setzen
        # (LOAD_RF_CONFIG setzt diese Register auf diesem Chip nicht)
        self._write_reg(self.REG_CRC_TX_CONFIG,  0x00000012)  # CRC16 ISO15693
        self._write_reg(self.REG_TIMER1_RELOAD,  0x000007D0)  # ~12ms Fenster
        self._write_reg(self.REG_TIMER1_CONFIG,  0x00000058)  # aktiv nach TX
        # FIX: RF_ON braucht Parameter-Byte 0x00!
        # Ohne dieses Byte ignoriert der Chip den Befehl komplett.
        self._spi_send([self.CMD_RF_ON, 0x00])
        utime.sleep_ms(20)

    # ----------------------------------------------------------
    # ISO 15693
    # ----------------------------------------------------------

    def _send_iso15693(self, flags, command, data=None):
        payload = [flags, command]
        if data:
            payload += list(data)

        self._idle()
        self._clear_irq()
        self._write_reg_or(self.REG_SYSTEM_CONFIG, 0x03)  # TRANSCEIVE
        self._spi_send([self.CMD_SEND_DATA, 0x00] + payload)

        # Nach TX_DONE NICHT abbrechen – Tag braucht bis zu 20ms
        # Warte bis RX_DONE oder Timeout (150ms wie im getesteten REPL-Code)
        end = utime.ticks_add(utime.ticks_ms(), 150)
        while utime.ticks_diff(end, utime.ticks_ms()) > 0:
            irq = self._read_reg(self.REG_IRQ_STATUS)
            if irq & 0x01:   # RX_DONE
                break
            utime.sleep_ms(1)
        else:
            self._idle()
            return self.NOTAG, None

        rx_status = self._read_reg(self.REG_RX_STATUS)
        rx_len = rx_status & 0x1FF
        if rx_len == 0:
            self._idle()
            return self.NOTAG, None

        buf = self._spi_read([self.CMD_READ_DATA, 0x00], rx_len)
        self._idle()

        if buf[0] & 0x01:
            return self.ERR, None
        return self.OK, list(buf[1:])

    # ----------------------------------------------------------
    # Public API
    # ----------------------------------------------------------

    def inventory(self):
        # EXAKTER REPL-CODE der funktioniert – nur self. statt globale Variablen
        import utime as _t
        def _wbl():
            end = _t.ticks_add(_t.ticks_ms(), 500)
            while self.busy.value():
                if _t.ticks_diff(end, _t.ticks_ms()) <= 0: return
                _t.sleep_us(20)
        def _wbc():
            end = _t.ticks_add(_t.ticks_ms(), 5)
            while not self.busy.value():
                if _t.ticks_diff(end, _t.ticks_ms()) <= 0: break
                _t.sleep_us(10)
            _wbl()
        def _send(d):
            _wbl(); self.nss.value(0); _t.sleep_us(2)
            self.spi.write(bytearray(d)); _t.sleep_us(2)
            self.nss.value(1); _t.sleep_us(5); _wbc()
        def _rreg(r):
            _wbl(); self.nss.value(0); _t.sleep_us(2)
            self.spi.write(bytearray([0x04,r])); _t.sleep_us(2)
            self.nss.value(1); _t.sleep_us(5); _wbc()
            _wbl(); self.nss.value(0); _t.sleep_us(2)
            b = bytearray(4); self.spi.readinto(b)
            _t.sleep_us(2); self.nss.value(1)
            return b[0]|(b[1]<<8)|(b[2]<<16)|(b[3]<<24)
        def _andreg(r,m): _send([0x02,r,m&0xFF,(m>>8)&0xFF,(m>>16)&0xFF,(m>>24)&0xFF])
        def _orreg(r,m):  _send([0x01,r,m&0xFF,(m>>8)&0xFF,(m>>16)&0xFF,(m>>24)&0xFF])
        def _rdata(n):
            _wbl(); self.nss.value(0); _t.sleep_us(2)
            self.spi.write(bytearray([0x0A,0x00])); _t.sleep_us(2)
            self.nss.value(1); _t.sleep_us(5); _wbc()
            _wbl(); self.nss.value(0); _t.sleep_us(2)
            b = bytearray(n); self.spi.readinto(b)
            _t.sleep_us(2); self.nss.value(1)
            return b

        _andreg(0x00, 0xFFFFFFF8)   # IDLE
        _send([0x00,0x03,0xFF,0xFF,0xFF,0xFF])  # WRITE_REGISTER IRQ_CLEAR
        _orreg(0x00, 0x03)           # TRANSCEIVE
        _send([0x09, 0x00, 0x26, 0x01, 0x00])  # SEND_DATA Inventory High-DR 1-Slot

        end = _t.ticks_add(_t.ticks_ms(), 150)
        while _t.ticks_diff(end, _t.ticks_ms()) > 0:
            irq = _rreg(0x02)
            if irq & 0x01:   # RX_DONE
                rx_len = _rreg(0x13) & 0x1FF
                _andreg(0x00, 0xFFFFFFF8)
                if rx_len >= 10:
                    data = _rdata(rx_len)
                    # Rohdaten: [flags, DSFID, UID0..7] = 10 Bytes
                    # UID = data[2:10] (8 Bytes, LSB first)
                    return self.OK, list(data[2:10])
                return self.NOTAG, None
            _t.sleep_ms(1)
        _andreg(0x00, 0xFFFFFFF8)
        return self.NOTAG, None

    def _iso_cmd(self, payload, timeout_ms=150, expect_rx=True):
        """Direkter ISO15693 Befehl – exakt wie getesteter REPL-Code."""
        import utime as _t
        def _wbl():
            end = _t.ticks_add(_t.ticks_ms(), 500)
            while self.busy.value():
                if _t.ticks_diff(end, _t.ticks_ms()) <= 0: return
                _t.sleep_us(20)
        def _wbc():
            end = _t.ticks_add(_t.ticks_ms(), 5)
            while not self.busy.value():
                if _t.ticks_diff(end, _t.ticks_ms()) <= 0: break
                _t.sleep_us(10)
            _wbl()
        def _send(d):
            _wbl(); self.nss.value(0); _t.sleep_us(2)
            self.spi.write(bytearray(d)); _t.sleep_us(2)
            self.nss.value(1); _t.sleep_us(5); _wbc()
        def _rreg(r):
            _wbl(); self.nss.value(0); _t.sleep_us(2)
            self.spi.write(bytearray([0x04,r])); _t.sleep_us(2)
            self.nss.value(1); _t.sleep_us(5); _wbc()
            _wbl(); self.nss.value(0); _t.sleep_us(2)
            b = bytearray(4); self.spi.readinto(b)
            _t.sleep_us(2); self.nss.value(1)
            return b[0]|(b[1]<<8)|(b[2]<<16)|(b[3]<<24)
        def _andreg(r,m): _send([0x02,r,m&0xFF,(m>>8)&0xFF,(m>>16)&0xFF,(m>>24)&0xFF])
        def _orreg(r,m):  _send([0x01,r,m&0xFF,(m>>8)&0xFF,(m>>16)&0xFF,(m>>24)&0xFF])
        def _rdata(n):
            _wbl(); self.nss.value(0); _t.sleep_us(2)
            self.spi.write(bytearray([0x0A,0x00])); _t.sleep_us(2)
            self.nss.value(1); _t.sleep_us(5); _wbc()
            _wbl(); self.nss.value(0); _t.sleep_us(2)
            b = bytearray(n); self.spi.readinto(b)
            _t.sleep_us(2); self.nss.value(1)
            return b

        _andreg(0x00, 0xFFFFFFF8)
        _send([0x00,0x03,0xFF,0xFF,0xFF,0xFF])  # WRITE_REGISTER IRQ_CLEAR
        _orreg(0x00, 0x03)
        _send([0x09, 0x00] + payload)

        if not expect_rx:
            # Warte auf TX_DONE + Option-Bit Response
            end = _t.ticks_add(_t.ticks_ms(), 25)
            while _t.ticks_diff(end, _t.ticks_ms()) > 0:
                irq = _rreg(0x02)
                if irq & 0x01:  # RX (Option-Bit Bestaetigung)
                    rx_len = _rreg(0x13) & 0x1FF
                    _andreg(0x00, 0xFFFFFFF8)
                    return self.OK, None
                if irq & 0x04:  # IDLE = fertig ohne RX
                    _andreg(0x00, 0xFFFFFFF8)
                    return self.OK, None
                _t.sleep_ms(1)
            _andreg(0x00, 0xFFFFFFF8)
            return self.OK, None   # Write gilt als OK wenn kein Fehler

        end = _t.ticks_add(_t.ticks_ms(), timeout_ms)
        while _t.ticks_diff(end, _t.ticks_ms()) > 0:
            irq = _rreg(0x02)
            if irq & 0x01:
                rx_len = _rreg(0x13) & 0x1FF
                _andreg(0x00, 0xFFFFFFF8)
                if rx_len > 1:
                    data = _rdata(rx_len)
                    if data[0] & 0x01:  # Error flag
                        return self.ERR, None
                    return self.OK, list(data[1:])
                return self.NOTAG, None
            _t.sleep_ms(1)
        _andreg(0x00, 0xFFFFFFF8)
        return self.NOTAG, None

    def read_block(self, uid, block_num):
        flags = self.ISO15693_REQ_FLAG_DATARATE | self.ISO15693_REQ_FLAG_ADDRESS
        status, data = self._iso_cmd(
            [flags, self.ISO15693_CMD_READ_SINGLE] + list(uid) + [block_num])
        if status == self.OK and data and len(data) >= 4:
            return self.OK, data[:4]
        return status, None

    def write_block(self, uid, block_num, data4):
        flags = (self.ISO15693_REQ_FLAG_DATARATE |
                 self.ISO15693_REQ_FLAG_ADDRESS |
                 self.ISO15693_REQ_FLAG_OPTION)
        status, _ = self._iso_cmd(
            [flags, self.ISO15693_CMD_WRITE_SINGLE] + list(uid) + [block_num] + list(data4[:4]),
            timeout_ms=25, expect_rx=False)
        return status == self.OK

    def read_blocks(self, uid, start_block, count):
        flags = self.ISO15693_REQ_FLAG_DATARATE | self.ISO15693_REQ_FLAG_ADDRESS
        status, data = self._iso_cmd(
            [flags, self.ISO15693_CMD_READ_MULTIPLE] + list(uid) + [start_block, count - 1],
            timeout_ms=300)
        if status == self.OK and data:
            return self.OK, data
        return status, None

    def get_system_info(self, uid):
        flags = self.ISO15693_REQ_FLAG_DATARATE | self.ISO15693_REQ_FLAG_ADDRESS
        return self._iso_cmd(
            [flags, self.ISO15693_CMD_GET_SYSTEM_INFO] + list(uid))

    def is_present(self):
        status, _ = self.inventory()
        return status == self.OK

    def rf_off(self):
        self._spi_send([self.CMD_RF_OFF, 0x00])

    def rf_on(self):
        self._spi_send([self.CMD_RF_ON, 0x00])
        utime.sleep_ms(20)
