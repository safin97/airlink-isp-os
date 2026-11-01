"""The checkpoint must precede mutation and rollback on every activation failure."""
import pytest
from network import configure as network


def test_checkpoint_created_before_network_change_and_rolled_back(monkeypatch,tmp_path):
    events=[]
    class Manager:
        def GetDeviceByIpIface(self,interface):return '/devices/1'
        def CheckpointCreate(self,devices,timeout,flags):
            events.append(('checkpoint',timeout,flags));return '/checkpoints/1'
        def CheckpointRollback(self,checkpoint):events.append(('rollback',checkpoint))
    monkeypatch.setattr(network,'nm',lambda:Manager())
    monkeypatch.setattr(network,'PENDING',tmp_path/'pending.json')
    original_exists = network.Path.exists
    monkeypatch.setattr(network.Path,'exists',lambda self: True if str(self) == '/sys/class/net/eth0' else original_exists(self))
    def run(args):
        events.append(('command',args))
        raise RuntimeError('Activation failed')
    monkeypatch.setattr(network,'run',run)
    with pytest.raises(RuntimeError):network.action('apply',{'interface':'eth0','method':'dhcp','hostname':'airlink'})
    assert events[0]==('checkpoint',120,2)
    assert events[-1]==('rollback','/checkpoints/1')
    command=events[1][1]
    assert command[command.index('connection.autoconnect')+1]=='no'


def test_expired_confirmation_cannot_keep_configuration(monkeypatch,tmp_path):
    pending=tmp_path/'pending.json'
    network.write(pending,{'checkpoint':'/checkpoints/1','deadline':1,'settings':{'hostname':'airlink'}})
    monkeypatch.setattr(network,'PENDING',pending)
    with pytest.raises(ValueError,match='expired'):
        network.action('confirm',{'checkpoint':'/checkpoints/1'})
    assert not pending.exists()
