"""Conservative device identity classification; unknown devices stay generic."""
import re

VENDOR_LABELS = {'generic':'Unknown / Generic', 'mikrotik':'MikroTik', 'mikrotik_switch':'MikroTik switch',
    'ubiquiti':'Ubiquiti', 'ubiquiti_m5':'Ubiquiti airMAX M5',
    'ubiquiti_ac':'Ubiquiti airMAX AC', 'mimosa':'Mimosa'}


def identify_vendor(object_id='', description='', family=None):
    oid = str(object_id).strip().lstrip('.')
    text = str(description).lower()[:2048]
    def enterprise(number):
        root = '1.3.6.1.4.1.' + str(number)
        return oid == root or oid.startswith(root + '.')
    if enterprise(14988):
        family = 'mikrotik'
    elif enterprise(41112) or enterprise(10002):
        family = 'ubiquiti'
    elif enterprise(43356):
        family = 'mimosa'
    elif family is None:
        if re.search(r'\b(mikrotik|routeros)\b', text): family = 'mikrotik'
        elif re.search(r'\b(ubiquiti|ubnt|airos|airmax)\b', text): family = 'ubiquiti'
        elif re.search(r'\bmimosa\b', text): family = 'mimosa'
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
