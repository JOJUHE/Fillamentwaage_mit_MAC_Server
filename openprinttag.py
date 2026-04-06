# =========================================================
# OpenPrintTag – CBOR + NDEF Codec fuer MicroPython
# Version : 2.2.0 (angepasst: Prusa-kompatibel)
# Datum   : 2026-03-01
# Diese Datei ist ein Drop-In Ersatz: read_tag(), write_tag(), update_consumed()
# behalten die gleiche API wie vorher. Sie liest Prusa-Tags (mit CC) und
# eigene Tags, speichert unbekannte Felder in extra_fields und schreibt
# beim Schreiben das volle Feldset.
# =========================================================

VERSION = "2.2.1"
DATE    = "2026-03-01"
print("[OPT] openprinttag v{} ({})".format(VERSION, DATE))

# ---- Material-Typ Enum ----
MATERIAL_TYPES = {
    0:  "PLA", 1:  "PETG", 2:  "ABS",  3:  "ASA",
    4:  "TPU", 5:  "PA",   6:  "PC",   7:  "PLA-CF",
    8:  "PETG-CF", 9: "ABS-CF", 10: "PA-CF",
    11: "PVA", 12: "HIPS", 13: "Flex", 14: "Sonstiges",
}
MATERIAL_TYPE_IDS = {v: k for k, v in MATERIAL_TYPES.items()}
MATERIAL_CLASS_FFF = 0
MATERIAL_CLASS_SLA = 1

# =========================================================
# MINI CBOR ENCODER
# =========================================================
def _cbor_encode_uint(value):
    if value <= 0x17:   return bytes([value])
    elif value <= 0xFF: return bytes([0x18, value])
    elif value <= 0xFFFF: return bytes([0x19, (value>>8)&0xFF, value&0xFF])
    elif value <= 0xFFFFFFFF:
        return bytes([0x1A,(value>>24)&0xFF,(value>>16)&0xFF,(value>>8)&0xFF,value&0xFF])
    else:
        return bytes([0x1B,(value>>56)&0xFF,(value>>48)&0xFF,(value>>40)&0xFF,
                      (value>>32)&0xFF,(value>>24)&0xFF,(value>>16)&0xFF,(value>>8)&0xFF,value&0xFF])

def _cbor_encode_int(value):
    if value >= 0: return _cbor_encode_uint(value)
    neg = (-1 - value)
    enc = _cbor_encode_uint(neg)
    return bytes([enc[0] | 0x20]) + enc[1:]

def _cbor_encode_float(value):
    import ustruct
    return bytes([0xFA]) + ustruct.pack(">f", value)

def _cbor_encode_str(s):
    b = s.encode("utf-8")
    n = len(b)
    if n <= 0x17:   return bytes([0x60|n]) + b
    elif n <= 0xFF: return bytes([0x78, n]) + b
    else:           return bytes([0x79,(n>>8)&0xFF,n&0xFF]) + b

def _cbor_encode_map(d):
    n = len(d)
    header = bytes([0xA0|n]) if n<=0x17 else bytes([0xB8,n]) if n<=0xFF else bytes([0xB9,(n>>8)&0xFF,n&0xFF])
    body = b""
    for k, v in d.items():
        body += _cbor_encode_item(k)
        body += _cbor_encode_item(v)
    return header + body

def _cbor_encode_item(v):
    if isinstance(v, bool):  return bytes([0xF5 if v else 0xF4])
    elif isinstance(v, int):   return _cbor_encode_int(v)
    elif isinstance(v, float): return _cbor_encode_float(v)
    elif isinstance(v, str):   return _cbor_encode_str(v)
    elif isinstance(v, dict):  return _cbor_encode_map(v)
    elif isinstance(v, (list,tuple)):
        n = len(v)
        h = bytes([0x80|n]) if n<=0x17 else bytes([0x98,n])
        return h + b"".join(_cbor_encode_item(i) for i in v)
    elif v is None: return bytes([0xF6])
    raise ValueError("CBOR: unbekannter Typ: "+str(type(v)))

def cbor_encode(d): return _cbor_encode_map(d)

# =========================================================
# MINI CBOR DECODER
# =========================================================
class _CborReader:
    def __init__(self, data):
        self.data = data; self.pos = 0

    def read(self, n):
        chunk = self.data[self.pos:self.pos+n]; self.pos += n; return chunk

    def read_byte(self):
        b = self.data[self.pos]; self.pos += 1; return b

    def decode(self):
        b = self.read_byte()
        major = (b>>5)&0x07; info = b&0x1F
        if major == 0: return self._read_uint(info)
        elif major == 1: return -1 - self._read_uint(info)
        elif major == 2:
            n = self._read_uint(info); return self.read(n)
        elif major == 3:
            n = self._read_uint(info); return self.read(n).decode("utf-8","ignore")
        elif major == 4:
            if info == 31:
                arr = []
                while True:
                    if self.data[self.pos] == 0xFF: self.pos+=1; break
                    arr.append(self.decode())
                return arr
            return [self.decode() for _ in range(self._read_uint(info))]
        elif major == 5:
            if info == 31:
                d = {}
                while True:
                    if self.data[self.pos] == 0xFF: self.pos+=1; break
                    k=self.decode(); d[k]=self.decode()
                return d
            n = self._read_uint(info)
            _d = {}
            for _ in range(n):
                _k = self.decode()
                _v = self.decode()
                _d[_k] = _v
            return _d
        elif major == 7:
            if info == 20: return False
            if info == 21: return True
            if info == 22: return None
            if info == 26:
                import ustruct; return ustruct.unpack(">f", self.read(4))[0]
            if info == 27:
                import ustruct; return ustruct.unpack(">d", self.read(8))[0]
        raise ValueError("CBOR: unbekanntes Byte 0x{:02X}".format(b))

    def _read_uint(self, info):
        if info <= 23: return info
        elif info == 24: return self.read_byte()
        elif info == 25: b=self.read(2); return (b[0]<<8)|b[1]
        elif info == 26: b=self.read(4); return (b[0]<<24)|(b[1]<<16)|(b[2]<<8)|b[3]
        elif info == 27:
            b=self.read(8); v=0
            for byte in b: v=(v<<8)|byte
            return v
        raise ValueError("CBOR uint info: "+str(info))

def cbor_decode(data): return _CborReader(bytes(data)).decode()

# =========================================================
# NDEF TLV Wrapper
# =========================================================
NDEF_MIME_TYPE = "application/vnd.openprinttag"

def ndef_wrap(payload_bytes):
    mime = NDEF_MIME_TYPE.encode()
    flags = 0x80|0x40|0x10|0x02  # MB|ME|SR|MIME
    record = bytes([flags, len(mime), len(payload_bytes)]) + mime + payload_bytes
    rec_len = len(record)
    if rec_len <= 0xFE:
        return bytes([0x03, rec_len]) + record + bytes([0xFE])
    else:
        return (bytes([0x03,0xFF,(rec_len>>8)&0xFF,rec_len&0xFF])
                + record + bytes([0xFE]))

def ndef_unwrap(tlv_bytes):
    """Parse all NDEF records inside the TLV stream and return a list of
    (mime, payload) tuples.  Debug output shows each TLV and record encountered.
    """
    data = bytes(tlv_bytes); pos = 0
    print("[OPT] ndef_unwrap len=", len(data))
    records = []
    while pos < len(data):
        t = data[pos]
        print("[OPT] TLV tag=0x{:02X} at pos {}".format(t, pos))
        pos += 1
        if t == 0x00:
            continue
        if t == 0xFE:
            print("[OPT] ndef_unwrap reached terminator")
            break
        if t == 0x03:
            # TLV contains an NDEF message which may itself hold several
            # records; we must iterate inside `rec`.
            if data[pos] == 0xFF:
                pos += 1
                length = (data[pos]<<8)|data[pos+1]; pos += 2
            else:
                length = data[pos]; pos += 1
            rec = data[pos:pos+length]
            print("[OPT] ndef record raw len=", len(rec), "expected=", length)
            pos += length
            # parse possible multiple NDEF records inside rec
            rp = 0
            while rp < len(rec):
                flags = rec[rp]; rp += 1
                type_len = rec[rp]; rp += 1
                # ID length not used here because we never add an ID
                id_len = 0
                if flags & 0x08:
                    id_len = rec[rp]; rp += 1
                if flags & 0x10:  # Short Record
                    payload_len = rec[rp]; rp += 1
                else:
                    payload_len = (rec[rp]<<24)|(rec[rp+1]<<16)|(rec[rp+2]<<8)|rec[rp+3]
                    rp += 4
                mime = rec[rp:rp+type_len].decode("utf-8","ignore")
                rp += type_len
                # skip ID if present
                if id_len:
                    rp += id_len
                payload = rec[rp:rp+payload_len]
                rp += payload_len
                print("[OPT] subrecord mime=", mime, "payload_len=", len(payload))
                print("[OPT] subrecord payload hex:", payload[:32].hex())
                records.append((mime, bytes(payload)))
                # if ME bit set we could break, but we'll just loop until rec end
            continue
        # skip other TLV types
        if pos < len(data) and data[pos] == 0xFF:
            pos += 1; length = (data[pos]<<8)|data[pos+1]; pos += 2
        else:
            length = data[pos]; pos += 1
        print("[OPT] skipping TLV type=0x{:02X} length={}".format(t, length))
        pos += length
    if not records:
        print("[OPT] ndef_unwrap no record found")
        print("[OPT] ndef_unwrap raw:", data[:32])
    return records

# =========================================================
# Pack / Unpack (UNIVERSAL: Prusa + eigene Tags)
# =========================================================
def pack(tag_dict):
    # Feld-Name -> CBOR-Key
    FIELD_IDS = {
        "version": 1,
        "brand": 2,
        "material_class": 3,
        "material_id": 4,
        "color": 5,
        "color_name": 6,
        "weight": 7,
        "diameter": 8,
        "nozzle_min": 9,
        "nozzle_max": 10,
        "bed_min": 11,
        "bed_max": 12,
        "length": 13,
        "manufacturer_url": 14,
        "consumed_weight": 20,
        "consumed_length": 21,
        # Prusa-spezifisch
        "manufacturer_name": 0x0B,
        "temp_extruder": 0x0E,
        "temp_bed": 0x10,
        "temp_bed_max": 0x11,
        "temp_extruder_max": 0x12,
        "prusa_internal_id": 0x61,
        "prusa_checksum": 0x9F,
    }

    cbor_map = {}

    # Material-ID aus Name ableiten, falls Material-Name vorhanden
    if "material" in tag_dict and tag_dict["material"] is not None:
        tag_dict["material_id"] = MATERIAL_TYPE_IDS.get(tag_dict["material"], 14)

    # Alle bekannten Felder einfügen
    for name, fid in FIELD_IDS.items():
        if name in tag_dict and tag_dict[name] is not None:
            cbor_map[fid] = tag_dict[name]

    # Extra-Felder wieder einfügen (unbekannte Keys erhalten)
    if "extra_fields" in tag_dict and isinstance(tag_dict["extra_fields"], dict):
        for k, v in tag_dict["extra_fields"].items():
            cbor_map[k] = v

    return ndef_wrap(cbor_encode(cbor_map))

def unpack(raw_bytes):
    print("[OPT] unpack called, raw_bytes len=", len(raw_bytes))
    records = ndef_unwrap(raw_bytes)
    print("[OPT] unpack saw {} record(s)".format(len(records)))
    url = None
    urls = []
    cbor_data = None
    for mime, payload in records:
        if mime == 'U':
            if payload and len(payload) > 1:
                prefix_byte = payload[0]
                PREFIXES = {
                    0x00: '', 0x01: 'http://www.', 0x02: 'https://www.',
                    0x03: 'http://', 0x04: 'https://',
                }
                body = payload[1:].decode('utf-8', 'ignore')
                found = PREFIXES.get(prefix_byte, '') + body
                print("[OPT] URL record detected:", found)
                urls.append(found)
                if url is None:
                    url = found          # remember first URL
        elif mime == NDEF_MIME_TYPE:
            # parse CBOR payload
            cbor_map = cbor_decode(payload)
            if isinstance(cbor_map, dict):
                print("[OPT] CBOR map:", cbor_map)
                cbor_data = cbor_map
            else:
                print("[OPT] CBOR ist kein Dict:", type(cbor_map), "value=", cbor_map)
                print("[OPT] payload hex:", payload.hex())
    # choose what to return
    if cbor_data is not None:
        # merge URL if we also saw one
        if url:
            cbor_data['url'] = url
        # convert numeric keys to readable field names
        # this mirrors the old mapping code that was unreachable
        KNOWN = {
            1:  "version",
            2:  "brand",
            3:  "material_class",
            4:  "material_id",
            5:  "color",
            6:  "color_name",
            7:  "weight",
            8:  "diameter",
            9:  "nozzle_min",
            10: "nozzle_max",
            11: "bed_min",
            12: "bed_max",
            13: "length",
            14: "manufacturer_url",
            20: "consumed_weight",
            21: "consumed_length",
            # Prusa-specific fields
            0x0B: "manufacturer_name",
            0x0E: "temp_extruder",
            0x10: "temp_bed",
            0x11: "temp_bed_max",
            0x12: "temp_extruder_max",
            0x61: "prusa_internal_id",
            0x9F: "prusa_checksum",
        }
        result = {}
        extra = {}
        for key, value in cbor_data.items():
            if key in KNOWN:
                result[KNOWN[key]] = value
            else:
                extra[key] = value
        # fill defaults for missing fields
        defaults = {
            "version": 1,
            "brand": "",
            "material_class": 0,
            "material_id": 14,
            "color": "",
            "color_name": "",
            "weight": 0,
            "diameter": 1.75,
            "nozzle_min": 200,
            "nozzle_max": 220,
            "bed_min": 50,
            "bed_max": 60,
            "length": 0,
            "manufacturer_url": "",
            "consumed_weight": 0,
            "consumed_length": 0.0,
        }
        for k, v in defaults.items():
            result.setdefault(k, v)
        # material name from id
        mat_id = result.get("material_id", 14)
        result["material"] = MATERIAL_TYPES.get(mat_id, "Sonstiges")
        # computed helpers
        result["extra_fields"] = extra
        result["remaining_weight"] = max(0, result.get("weight", 0) - result.get("consumed_weight", 0))
        return result
    if url is not None:
        return {'url': url}
    print("[OPT] unpack found no usable records")
    return None

    # Mapping CBOR-Key -> Feldname (OPT + Prusa)
    KNOWN = {
        1:  "version",
        2:  "brand",
        3:  "material_class",
        4:  "material_id",
        5:  "color",
        6:  "color_name",
        7:  "weight",
        8:  "diameter",
        9:  "nozzle_min",
        10: "nozzle_max",
        11: "bed_min",
        12: "bed_max",
        13: "length",
        14: "manufacturer_url",
        20: "consumed_weight",
        21: "consumed_length",
        # Prusa-spezifische Felder
        0x0B: "manufacturer_name",
        0x0E: "temp_extruder",
        0x10: "temp_bed",
        0x11: "temp_bed_max",
        0x12: "temp_extruder_max",
        0x61: "prusa_internal_id",
        0x9F: "prusa_checksum",
    }

    result = {}
    extra = {}

    # Übernehme alle Felder; unbekannte in extra speichern
    for key, value in cbor_map.items():
        if key in KNOWN:
            result[KNOWN[key]] = value
        else:
            extra[key] = value

    # Defaults ergänzen (sichere Werte, falls Feld fehlt)
    defaults = {
        "version": 1,
        "brand": "",
        "material_class": 0,
        "material_id": 14,
        "color": "",
        "color_name": "",
        "weight": 0,
        "diameter": 1.75,
        "nozzle_min": 200,
        "nozzle_max": 220,
        "bed_min": 50,
        "bed_max": 60,
        "length": 0,
        "manufacturer_url": "",
        "consumed_weight": 0,
        "consumed_length": 0.0,
    }
    for k, v in defaults.items():
        result.setdefault(k, v)

    # Material-Name ergänzen
    mat_id = result.get("material_id", 14)
    result["material"] = MATERIAL_TYPES.get(mat_id, "Sonstiges")

    # Unbekannte Felder erhalten
    result["extra_fields"] = extra

    # Berechnetes Feld
    result["remaining_weight"] = max(0, result["weight"] - result["consumed_weight"])

    return result

# =========================================================
# Tag Lesen / Schreiben (read_tag angepasst: CC-Skip)
# =========================================================
# previous firmware used 28 blocks (112 Bytes) which is too small for some
# tags; the TLV header can specify a longer NDEF message (e.g. 0x012F = 303
# bytes) so we must read more. 80 blocks = 320 Bytes should be sufficient for
# any realistic OpenPrintTag, but a fully dynamic approach would read the
# header first then the required amount.
BLOCKS_TO_READ = 80   # 320 Bytes – vorsichtig mehr Puffer

def read_tag(reader):
    status, uid = reader.inventory()
    if status != reader.OK or uid is None:
        return None, None

    print("[OPT] Tag gefunden, UID:", " ".join("{:02X}".format(b) for b in uid))

    raw = []
    for block in range(BLOCKS_TO_READ):
        st, data = reader.read_block(uid, block)
        if st != reader.OK or data is None:
            print("[OPT] Lesefehler bei Block", block, "nach", len(raw), "Bytes")
            break
        raw.extend(data)

    print("[OPT] Gelesen:", len(raw), "Bytes –",
          " ".join("{:02X}".format(b) for b in raw[:16]), "...")
    # dump entire raw for investigation (limited to first 64 bytes to avoid spam)
    print("[OPT] raw hex (first 64):", bytes(raw[:64]).hex())

    if len(raw) < 8:
        return uid, None

    # Wenn Tag mit Capability Container (CC) beginnt (E1 40), CC (4 Bytes) überspringen
    if len(raw) >= 4 and raw[0] == 0xE1 and raw[1] == 0x40:
        print("[OPT] CC detected – skipping 4 bytes; pre-skip bytes=", bytes(raw[:8]).hex())
        raw = raw[4:]
        print("[OPT] after skip raw hex (first 64):", bytes(raw[:64]).hex())

    return uid, unpack(raw)

def write_tag(reader, tag_dict):
    status, uid = reader.inventory()
    if status != reader.OK or uid is None:
        print("[OPT] Kein Tag zum Schreiben gefunden")
        return False

    payload = pack(tag_dict)
    if len(payload) % 4 != 0:
        payload += bytes(4 - (len(payload) % 4))

    blocks = len(payload) // 4
    print("[OPT] Schreibe {} Bytes ({} Bloecke)...".format(len(payload), blocks))

    for i in range(blocks):
        ok = reader.write_block(uid, i, payload[i*4:(i+1)*4])
        if not ok:
            print("[OPT] Schreibfehler bei Block", i)
            return False

    print("[OPT] Erfolgreich geschrieben!")
    return True

def update_consumed(reader, consumed_weight_g, consumed_length_m=None):
    uid, tag = read_tag(reader)
    if tag is None:
        return False
    tag["consumed_weight"] = int(consumed_weight_g)
    if consumed_length_m is not None:
        tag["consumed_length"] = float(consumed_length_m)
    return write_tag(reader, tag)
