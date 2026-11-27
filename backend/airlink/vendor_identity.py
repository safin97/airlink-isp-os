"""Conservative device identity classification; unknown devices stay generic."""
import re

VENDOR_LABELS = {'generic':'Unknown / Generic', 'mikrotik':'MikroTik', 'mikrotik_switch':'MikroTik switch',
    'ubiquiti':'Ubiquiti', 'ubiquiti_m5':'Ubiquiti airMAX M5',
    'ubiquiti_ac':'Ubiquiti airMAX AC', 'mimosa':'Mimosa',
    'tenda':'Tenda', 'tplink':'TP-Link', 'ruijie':'Ruijie / Reyee', 'hikvision':'Hikvision'}

# Manufacturer PENs from https://www.iana.org/assignments/enterprise-numbers/.
# These establish the brand, not whether a device is a router, switch or camera.
ENTERPRISES = {14988: 'mikrotik', 41112: 'ubiquiti', 10002: 'ubiquiti', 43356: 'mimosa',
               59646: 'tenda', 11863: 'tplink', 65855: 'tplink', 4881: 'ruijie', 39165: 'hikvision'}
BRAND_ONLY_VENDORS = frozenset({'tenda', 'tplink', 'ruijie', 'hikvision'})


def identify_vendor(object_id='', description='', family=None):
    oid = str(object_id).strip().lstrip('.')
    text = str(description).lower()[:2048]
    def enterprise(number):
        root = '1.3.6.1.4.1.' + str(number)
        return oid == root or oid.startswith(root + '.')
    confirmed = next((brand for number, brand in ENTERPRISES.items() if enterprise(number)), None)
    if confirmed:
        family = confirmed
    elif family is None:
        if re.search(r'\b(mikrotik|routeros)\b', text): family = 'mikrotik'
        elif re.search(r'\b(ubiquiti|ubnt|airos|airmax)\b', text): family = 'ubiquiti'
        elif re.search(r'\bmimosa\b', text): family = 'mimosa'
        elif re.search(r'(?<![a-z0-9])tenda(?![a-z0-9])', text): family = 'tenda'
        elif re.search(r'(?<![a-z0-9])(?:tp[-\s]?link|tplinkwifi|tplinklogin)(?![a-z0-9])', text): family = 'tplink'
        elif re.search(r'(?<![a-z0-9])(?:ruijie|reyee)(?![a-z0-9])', text): family = 'ruijie'
        # Reyee agents may use Net-SNMP's generic sysObjectID. Identify this
        # bridge only when its model is explicitly present in the description.
        elif re.search(r'(?<![a-z0-9])rg-est450g(?![a-z0-9])', text): family = 'ruijie'
        elif re.search(r'(?<![a-z0-9])hikvision(?![a-z0-9])', text): family = 'hikvision'
    if family == 'ubiquiti':
        if re.search(r'\b(?:[a-z]+-)?[25]ac(?:\b|[-\d])|\b(?:airmax|rocket|nanobeam|powerbeam|litebeam|nanostation)\s+ac\b', text):
            return 'ubiquiti_ac'
        if re.search(r'\b(?:m5|[a-z]+m5)(?:\b|[-\d])', text):
            return 'ubiquiti_m5'
    return family if family in VENDOR_LABELS else 'generic'


def merge_vendor(previous, detected):
    # A generic airOS response must not erase a confirmed M5/AC identity.
    if detected in (None, 'generic'):
        return previous or 'generic'
    if detected == 'ubiquiti' and previous in ('ubiquiti_m5', 'ubiquiti_ac'):
        return previous
    return detected
