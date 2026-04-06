# =========================================================
# esp_minimal.py – ESP32-S3 Filament-Waage (Hardware-API)
#
# Der ESP liefert nur noch Messdaten via JSON.
# Der Mac-Server übernimmt: Web-UI, Log, Chart.
#
# Pinbelegung:
#   HX711:  DOUT=4, SCK=5
#   PN5180: MOSI=35, MISO=37, SCK=36, NSS=10, BUSY=38, RST=39
#   Buzzer: GPIO 2
#   DFPlayer: UART1 TX=17, RX=16
#
# API-Endpunkte:
#   GET /weight          → {weight, filament, nfc_event}
#   GET /status          → {uptime, fw, cal_ok, cal_factor, spool, alarm, auto_thr, tag}
#   GET /action?a=...    → JSON-Antwort je nach Aktion
#   GET /icon_waage9.png → PNG-Icon
#
# WLAN-Zugangsdaten in config.json auf dem ESP speichern:
#   {"ssid": "MeinWLAN", "password": "MeinPasswort"}
# =========================================================

import network, utime, socket, gc, json
from machine import Pin, UART, PWM, WDT
import neopixel

FW_VERSION = "01.01R000 from 01.03.2026"
print("[FW] Version:", FW_VERSION)

wdt = WDT(timeout=220000)
start_ticks = utime.ticks_ms()
np = neopixel.NeoPixel(Pin(48), 1)
np[0] = (5, 0, 0)   # Rot = Hochlauf
np.write()

cached_weight = None

# ===== MEDIAN-FILTER =====
_weight_buf = []
_MEDIAN_N   = 5

def _median_push(val):
    _weight_buf.append(val)
    if len(_weight_buf) > _MEDIAN_N:
        _weight_buf.pop(0)
    if len(_weight_buf) < 3:
        return val
    s = sorted(_weight_buf)
    return s[len(s) // 2]

TIMEZONE_OFFSET = 3600  # UTC+1 (Winter); Sommer: 7200

# ===== AUTO NFC UPDATE =====
auto_update_threshold_g = 5
auto_update_max_jump_g  = 15
last_written_consumed   = None
nfc_write_event         = False

# ===== WLAN – Zugangsdaten aus config.json =====
try:
    with open("config.json") as f:
        _cfg = json.load(f)
    SSID     = _cfg.get("ssid", "")
    PASSWORD = _cfg.get("password", "")
    print("[CFG] WLAN-Config geladen:", SSID)
except Exception as e:
    print("[CFG] config.json fehlt:", e)
    SSID     = "DEIN_WLAN"
    PASSWORD = "DEIN_PASSWORT"

def sync_time():
    try:
        import ntptime
        ntptime.settime()
        print("[NTP] Zeit synchronisiert")
    except Exception as e:
        print("[NTP] Fehler:", e)

def wifi_connect():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect(SSID, PASSWORD)
    print("[WIFI] Verbinde mit", SSID, "...")
    for _ in range(50):
        if wlan.isconnected():
            break
        utime.sleep_ms(200)
    if not wlan.isconnected():
        print("[WIFI] Verbindung fehlgeschlagen")
        return None
    ip = wlan.ifconfig()[0]
    print("[WIFI] IP:", ip)
    np[0] = (0, 5, 0)    # Grün = verbunden
    np.write()
    return wlan

wlan = wifi_connect()
if wlan:
    sync_time()
    t = utime.localtime(utime.time() + TIMEZONE_OFFSET)
    print("Zeit: {:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}".format(
        t[0], t[1], t[2], t[3], t[4], t[5]))

# ===== HX711 =====
from hx711 import HX711
scale = HX711(dout=4, sck=5)
utime.sleep_ms(500)
scale.tare(10)

CAL_FILE = "scale_cal.json"

def load_calibration():
    try:
        with open(CAL_FILE, "r") as f:
            cal = json.load(f)
            scale.set_scale(cal.get("scale_factor", 1.0))
            scale.set_offset(cal.get("offset", 0))
            print("[CAL] Kalibrierung geladen, Faktor:", cal.get("scale_factor"))
    except:
        print("[CAL] Keine Kalibrierung – bitte kalibrieren!")

def save_calibration():
    try:
        with open(CAL_FILE, "w") as f:
            json.dump({"scale_factor": scale.get_scale(), "offset": scale.OFFSET}, f)
        print("[CAL] Gespeichert")
    except Exception as e:
        print("[CAL] Speicherfehler:", e)

load_calibration()

# ===== PN5180 / OpenPrintTag =====
from pn5180 import PN5180
from openprinttag import read_tag, write_tag, update_consumed, MATERIAL_TYPE_IDS

nfc = PN5180(mosi=35, miso=37, sck=36, nss=10, busy=38, rst=39)
current_tag_data = None

# ===== DFPLAYER =====
uart_dfp = UART(1, baudrate=9600, tx=17, rx=16, timeout=200)
utime.sleep_ms(300)

def dfp_cmd(cmd, param=0):
    try:
        pkt = bytearray([0x7E, 0xFF, 0x06, cmd, 0x00,
                         (param >> 8) & 0xFF, param & 0xFF, 0xEF])
        uart_dfp.write(pkt)
    except Exception as e:
        print("[DFP]", e)

def dfp_set_vol(v): dfp_cmd(0x06, max(0, min(30, v)))
def dfp_play(n):    dfp_cmd(0x03, n)
dfp_set_vol(20)

# ===== BUZZER =====
_buz = Pin(2, Pin.OUT, value=0)

def buzz(freq=1000, ms=200, n=1):
    for _ in range(n):
        p = PWM(_buz, freq=freq, duty=128)
        utime.sleep_ms(ms)
        p.deinit()
        _buz.value(0)
        utime.sleep_ms(80)

def alarm_sound(): buzz(880, 300, 3); dfp_play(1)
def ok_sound():    buzz(1200, 80, 2)

# ===== EINSTELLUNGEN =====
SETTINGS_FILE = "settings.json"

def load_settings():
    try:
        with open(SETTINGS_FILE) as f: return json.load(f)
    except: return {}

def save_settings():
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump({"spool_weight_g": spool_weight_g,
                       "alarm_threshold": alarm_threshold}, f)
    except Exception as e:
        print("[SETTINGS]", e)

_s             = load_settings()
spool_weight_g  = float(_s.get("spool_weight_g",  0.0))
alarm_threshold = float(_s.get("alarm_threshold", 50.0))

def get_uptime():
    sec = utime.ticks_diff(utime.ticks_ms(), start_ticks) // 1000
    return "{:02d}d {:02d}:{:02d}:{:02d}".format(
        sec // 86400, (sec % 86400) // 3600, (sec % 3600) // 60, sec % 60)

# ===== AUTO NFC GEWICHTS-UPDATE =====
def auto_update_nfc_weight():
    global current_tag_data, last_written_consumed, nfc_write_event

    if current_tag_data is None or scale.get_scale() == 1.0 or spool_weight_g <= 0:
        return

    w = scale.get_grams(3)
    if w is None:
        return

    full_w   = current_tag_data.get("weight", 1000)
    consumed = int(max(0, full_w - max(0, w - spool_weight_g)))

    if last_written_consumed is None:
        last_written_consumed = consumed
        return

    delta = consumed - last_written_consumed

    if delta <= 0:
        return
    if delta < auto_update_threshold_g:
        return
    if delta > auto_update_max_jump_g:
        print("[AUTO NFC] Sprung ignoriert:", delta, "g")
        return

    ok = update_consumed(nfc, consumed)
    nfc_write_event = True
    if ok:
        current_tag_data["consumed_weight"] = consumed
        current_tag_data["remaining_weight"] = max(0, full_w - consumed)
        last_written_consumed = consumed
        print("[AUTO NFC] Automatisch geschrieben:", consumed, "g")
    else:
        print("[AUTO NFC] Schreiben fehlgeschlagen")

# ===== HTTP HELPERS =====
def read_request(c):
    req = b""
    c.settimeout(0.3)
    try:
        while True:
            chunk = c.recv(512)
            if not chunk: break
            req += chunk
            if b"\r\n\r\n" in req: break
    except: pass
    return req.decode("utf-8", "ignore")

def get_param(req, name):
    try:
        val = req.split(name + "=")[1].split("&")[0].split(" ")[0]
        return val.replace("%20"," ").replace("+"," ").replace("%23","#").replace("%2F","/")
    except: return None

def json_resp(c, data):
    body = json.dumps(data)
    # CORS-Header: erlaubt Zugriff vom Mac-Server
    c.sendall("HTTP/1.1 200 OK\r\n"
              "Content-Type: application/json\r\n"
              "Access-Control-Allow-Origin: *\r\n"
              "Connection: close\r\n\r\n" + body)

# ===== ENDPUNKTE =====

def handle_weight(c):
    global nfc_write_event
    w        = cached_weight
    filament = max(0, w - spool_weight_g) if w is not None and spool_weight_g > 0 else None
    evt      = nfc_write_event
    nfc_write_event = False
    json_resp(c, {
        "weight":    round(w, 1) if w is not None else None,
        "filament":  round(filament, 1) if filament is not None else None,
        "nfc_event": evt
    })

def handle_status(c):
    cal_ok = abs(scale.get_scale() - 1.0) > 0.01
    json_resp(c, {
        "uptime":     get_uptime(),
        "fw":         FW_VERSION,
        "cal_ok":     cal_ok,
        "cal_factor": round(scale.get_scale(), 4),
        "spool":      spool_weight_g,
        "alarm":      alarm_threshold,
        "auto_thr":   auto_update_threshold_g,
        "tag":        current_tag_data
    })

def handle_action(c, req):
    global spool_weight_g, alarm_threshold, current_tag_data
    global last_written_consumed, auto_update_threshold_g, nfc_write_event

    a = get_param(req, "a")
    if not a:
        json_resp(c, {"ok": False, "msg": "Unbekannte Aktion"}); return

    if a == "tare":
        scale.tare(15)
        save_calibration()
        json_resp(c, {"ok": True, "msg": "Tara gesetzt!"})

    elif a == "calibrate":
        g = get_param(req, "g")
        try:
            f = scale.calibrate(float(g))
            if f:
                save_calibration()
                json_resp(c, {"ok": True, "msg": "Kalibriert! Faktor: {:.2f}".format(f)})
            else:
                json_resp(c, {"ok": False, "msg": "Kalibrierung fehlgeschlagen"})
        except Exception as e:
            json_resp(c, {"ok": False, "msg": str(e)})

    elif a == "spool":
        try:
            spool_weight_g = float(get_param(req, "g"))
            save_settings()
            json_resp(c, {"ok": True, "msg": "Spulengewicht: {:.0f}g gespeichert".format(spool_weight_g)})
        except:
            json_resp(c, {"ok": False, "msg": "Ungueltig"})

    elif a == "measure_spool":
        w = scale.get_grams(15)
        if w is None:
            json_resp(c, {"ok": False, "msg": "Waage nicht kalibriert!"}); return
        if not (0 < w < 1000):
            json_resp(c, {"ok": False, "msg": "Wert ausserhalb Bereich: {:.1f}g".format(w)}); return
        spool_weight_g = w
        save_settings()
        json_resp(c, {"ok": True, "msg": "Gemessen: {:.1f}g".format(w), "g": w})

    elif a == "alarm":
        try:
            alarm_threshold = float(get_param(req, "g"))
            save_settings()
            json_resp(c, {"ok": True, "msg": "Alarm bei {}g".format(alarm_threshold)})
        except:
            json_resp(c, {"ok": False, "msg": "Ungueltig"})

    elif a == "get_weight_raw":
        # Wird vom Mac-Server beim Log-Eintrag abgefragt
        w = scale.get_grams(10)
        filament = max(0, w - spool_weight_g) if w is not None and spool_weight_g > 0 else None
        mat   = current_tag_data.get("material","") if current_tag_data else ""
        brand = current_tag_data.get("brand","")   if current_tag_data else ""
        json_resp(c, {
            "ok": w is not None,
            "weight":   round(w, 1) if w is not None else None,
            "filament": round(filament, 1) if filament is not None else None,
            "material": mat,
            "brand":    brand
        })

    elif a == "nfc_read":
        uid, data = read_tag(nfc)
        if data is None:
            json_resp(c, {"ok": False, "msg": "Kein OpenPrintTag gefunden - ICODE SLIX/SLIX2 auflegen!"}); return
        current_tag_data      = data
        last_written_consumed = None
        json_resp(c, {"ok": True, "msg": "Tag gelesen: {} {}".format(
            data.get("brand",""), data.get("material","")), "tag": data})

    elif a == "nfc_write":
        w  = scale.get_grams(10) or 0
        sp = float(get_param(req, "sp") or "0")
        fw = float(get_param(req, "fw") or "1000")
        consumed = max(0, fw - max(0, w - sp))
        tag_dict = {
            "brand":           get_param(req, "brand") or "",
            "material":        get_param(req, "mat")   or "PLA",
            "color":           get_param(req, "col")   or "#ffffff",
            "color_name":      get_param(req, "col_name") or "",
            "nozzle_min":      int(get_param(req, "nm")  or 200),
            "nozzle_max":      int(get_param(req, "nx")  or 220),
            "bed_min":         int(get_param(req, "bm")  or 50),
            "bed_max":         int(get_param(req, "bx")  or 60),
            "diameter":        float(get_param(req, "dia") or 1.75),
            "weight":          int(fw),
            "consumed_weight": int(consumed),
            "length":          int(fw / 2.5),
        }
        ok = write_tag(nfc, tag_dict)
        if ok:
            _, current_tag_data = read_tag(nfc)
            ok_sound()
            json_resp(c, {"ok": True, "msg": "OpenPrintTag geschrieben! {} {}".format(
                tag_dict["brand"], tag_dict["material"])})
        else:
            json_resp(c, {"ok": False, "msg": "Schreiben fehlgeschlagen - Tag neu auflegen!"})

    elif a == "nfc_update":
        w = scale.get_grams(10)
        if w is None:
            json_resp(c, {"ok": False, "msg": "Waage nicht kalibriert!"}); return
        if current_tag_data is None:
            json_resp(c, {"ok": False, "msg": "Erst Tag lesen!"}); return
        full_w   = current_tag_data.get("weight", 1000)
        consumed = max(0, full_w - max(0, w - spool_weight_g))
        ok = update_consumed(nfc, consumed)
        nfc_write_event = True
        if ok:
            current_tag_data["consumed_weight"] = int(consumed)
            current_tag_data["remaining_weight"] = max(0, full_w - int(consumed))
            json_resp(c, {"ok": True, "msg": "Verbrauch aktualisiert: {:.0f}g verbraucht".format(consumed)})
        else:
            json_resp(c, {"ok": False, "msg": "Update fehlgeschlagen"})

    elif a == "set_auto_thr":
        try:
            auto_update_threshold_g = int(get_param(req, "v"))
            json_resp(c, {"ok": True, "msg": "Auto-Schwellwert: {}g".format(auto_update_threshold_g)})
        except:
            json_resp(c, {"ok": False, "msg": "Ungueltig"})

    else:
        json_resp(c, {"ok": False, "msg": "Unbekannt: " + a})

# ===== SOCKET SERVER =====
srv = socket.socket()
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("", 80))
srv.listen(2)
srv.settimeout(3)
if wlan:
    print("[SERVER] ESP läuft unter http://{}".format(wlan.ifconfig()[0]))
    print("[SERVER] Mac-Server trägt diese IP in config.json ein")

# ===== MAIN LOOP =====
last_alarm_check = utime.ticks_ms()
try:
    while True:
        wdt.feed()

        # Gewicht messen und in Median-Puffer schieben
        new_weight = scale.get_grams(3)
        if new_weight is not None:
            cached_weight = _median_push(new_weight)

        # Alarm alle 10s prüfen
        if utime.ticks_diff(utime.ticks_ms(), last_alarm_check) > 10000:
            last_alarm_check = utime.ticks_ms()
            if scale.get_scale() != 1.0 and spool_weight_g > 0:
                if cached_weight is not None and 0 < (cached_weight - spool_weight_g) < alarm_threshold:
                    print("[ALARM] Filament niedrig!")
                    alarm_sound()

        # WLAN-Reconnect
        if wlan and not wlan.isconnected():
            wlan = wifi_connect()
            if not wlan:
                utime.sleep(2); continue

        # HTTP-Request verarbeiten
        c = None
        try:
            c, addr = srv.accept()
            req = read_request(c)
            if not req.strip():
                pass
            elif "GET /weight" in req:
                handle_weight(c)
            elif "GET /action" in req:
                handle_action(c, req)
            elif "GET /status" in req:
                handle_status(c)
            elif "GET /icon_waage9.png" in req:
                try:
                    with open("icon_waage9.png", "rb") as f:
                        img = f.read()
                    c.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: image/png\r\n"
                              b"Access-Control-Allow-Origin: *\r\n"
                              b"Connection: close\r\n\r\n")
                    c.sendall(img)
                except:
                    c.sendall(b"HTTP/1.1 404 Not Found\r\n\r\n")
        except:
            pass
        finally:
            if c:
                try: c.close()
                except: pass

        gc.collect()
        auto_update_nfc_weight()
        utime.sleep_ms(100)

except KeyboardInterrupt:
    print("[SYSTEM] Manuell beendet")
except Exception as e:
    print("[SYSTEM] Fehler:", e)
finally:
    np[0] = (5, 0, 0)
    np.write()
