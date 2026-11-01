import base64
import copy
from datetime import datetime,timezone,timedelta
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from cryptography.exceptions import InvalidSignature
from installer.disks import parse_disks,authorize
from installer.install import partition_path
from network.configure import validate
from updates.update import canonical,verify_manifest
from monitoring.snmp import counter_rate


def inventory(**kwargs):
    node={'path':'/dev/sda','type':'disk','size':64*1024**3,'model':'Test Disk','serial':'SERIAL1','tran':'sata','rota':False,'ro':False,'mountpoints':[None],'maj:min':'8:0','children':[]}
    node.update(kwargs)
    return {'blockdevices':[node]}


def test_disk_requires_exact_confirmation():
    disks=parse_disks(inventory())
    d=disks[0]
    for text,ack in [('erase',True),('ERASE',False),('',True)]:
        with pytest.raises(ValueError):authorize(disks,d.path,d.identity,text,ack)
    assert authorize(disks,d.path,d.identity,'ERASE',True)==d


def test_changed_disk_identity_rejected():
    old=parse_disks(inventory())[0]
    new=parse_disks(inventory(serial='DIFFERENT'))
    with pytest.raises(ValueError):authorize(new,old.path,old.identity,'ERASE',True)


@pytest.mark.parametrize('mount',['/run/live/medium','/','/home','/media/backup'])
def test_mounted_installer_and_other_disks_protected(mount):
    data=inventory(children=[{'path':'/dev/sda1','type':'part','mountpoints':[mount]}])
    d=parse_disks(data)[0]
    with pytest.raises(ValueError):authorize([d],d.path,d.identity,'ERASE',True)


@pytest.mark.parametrize('changes',[{'ro':True},{'size':1024},{'path':'/dev/mapper/target'},{'children':[{'path':'/dev/dm-0','type':'crypt','mountpoints':[]}]}])
def test_unsafe_disks_rejected(changes):
    assert parse_disks(inventory(**changes))[0].blocked


def test_swap_and_holders_protected():
    assert parse_disks(inventory(),swaps=['/dev/sda'])[0].blocked
    assert parse_disks(inventory(),held=['/dev/sda'])[0].blocked


def test_partition_names():
    assert partition_path('/dev/sda',1)=='/dev/sda1'
    assert partition_path('/dev/nvme0n1',2)=='/dev/nvme0n1p2'


def static(**kwargs):
    data={'interface':'enp1s0','method':'static','address':'192.168.20.2','prefix':24,'gateway':'192.168.20.1','dns':['1.1.1.1'],'hostname':'airlink'}
    data.update(kwargs)
    return data


@pytest.mark.parametrize('changes',[{'gateway':'192.168.21.1'},{'gateway':'192.168.20.2'},{'address':'192.168.20.0'},{'address':'192.168.20.255'},{'prefix':33},{'hostname':'bad;reboot'},{'interface':'eth0;reboot'},{'dns':['bad']},{'method':'shell'}])
def test_network_rejects_bad_settings(changes):
    with pytest.raises(ValueError):validate(static(**changes))


def test_network_valid_dhcp_and_static():
    assert validate(static())['gateway']=='192.168.20.1'
    assert validate({'interface':'enp1s0','method':'dhcp','hostname':'airlink'})['method']=='dhcp'


def signed():
    key=Ed25519PrivateKey.generate()
    public=key.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)
    meta={'version':'0.2.0','sequence':1,'sha256':'a'*64,'size':100,'url':'https://updates.example.test/airlink.deb','expires':(datetime.now(timezone.utc)+timedelta(days=1)).isoformat(),'release_notes':'Test','reboot_required':False}
    return key,public,meta


def test_update_signature_and_tampering():
    key,public,meta=signed()
    envelope={'manifest':meta,'signature':base64.b64encode(key.sign(canonical(meta))).decode()}
    assert verify_manifest(envelope,public)['version']=='0.2.0'
    meta['size']=101
    with pytest.raises(InvalidSignature):verify_manifest(envelope,public)


@pytest.mark.parametrize('change',[{'sequence':0},{'url':'http://example.test/pkg'},{'size':-1},{'sha256':'bad'},{'expires':'2020-01-01T00:00:00Z'}])
def test_even_signed_unsafe_updates_rejected(change):
    key,public,meta=signed();meta.update(change)
    envelope={'manifest':meta,'signature':base64.b64encode(key.sign(canonical(meta))).decode()}
    with pytest.raises(ValueError):verify_manifest(envelope,public)


def test_counter_rates_skip_reboots_wrap_and_gaps():
    assert counter_rate(100,200,10)==80
    assert counter_rate(200,100,10) is None
    assert counter_rate(100,200,10,rebooted=True) is None
    assert counter_rate(100,200,10,discontinuity_changed=True) is None
    assert counter_rate(None,200,10) is None
    assert counter_rate(100,200,0) is None
