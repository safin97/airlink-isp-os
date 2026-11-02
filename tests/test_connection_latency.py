import subprocess
from types import SimpleNamespace as S
from airlink import connection_latency as latency
from airlink import system_stats as host


def test_ping_uses_bounded_fixed_argument_probe_and_parses_actual_reply(monkeypatch):
    calls = []
    def run(args, **kwargs):
        calls.append((args,kwargs))
        return S(returncode=0, stdout='64 bytes from 8.8.8.8: icmp_seq=1 ttl=115 time=12.345 ms\n')
    monkeypatch.setattr(latency.subprocess,'run',run)
    result=latency.measure('8.8.8.8')
    assert result['status']=='ready' and result['rtt_ms']==12.345
    assert calls[0][0][-1]=='8.8.8.8' and calls[0][1]['timeout']==3
    assert 'shell' not in calls[0][1]
    monkeypatch.setattr(latency.subprocess,'run',lambda *a,**kw:S(returncode=0,stdout='time<1 ms'))
    assert latency.measure('1.1.1.1')['less_than'] is True


def test_failed_probes_and_stale_cache_are_not_zero_latency(monkeypatch):
    monkeypatch.setattr(latency.subprocess,'run',lambda *a,**kw:S(returncode=1,stdout='Request timeout'))
    assert latency.measure('1.1.1.1')['rtt_ms'] is None
    def timeout(*a,**kw): raise subprocess.TimeoutExpired('ping',3)
    monkeypatch.setattr(latency.subprocess,'run',timeout)
    assert latency.measure('8.8.8.8')['status']=='no_reply'
    sampler=latency.ConnectionLatency()
    sampler.sampled_at=10
    sampler.results={'gaming':{'status':'ready','rtt_ms':10}}
    monkeypatch.setattr(latency.time,'monotonic',lambda:30)
    assert sampler.read()['gaming']['status']=='stale'
    assert sampler.read()['gaming']['rtt_ms'] is None


def test_macos_ethernet_excludes_wifi_and_bridge(monkeypatch):
    monkeypatch.setattr(host.sys,'platform','darwin')
    monkeypatch.setattr(host.subprocess,'run',lambda *a,**kw:S(stdout='''Hardware Port: Wi-Fi
Device: en0

Hardware Port: USB Ethernet
Device: en5

Hardware Port: Thunderbolt Bridge
Device: bridge0
'''))
    assert host.ethernet_ports(['en0','en5','bridge0'])=={'en5'}
