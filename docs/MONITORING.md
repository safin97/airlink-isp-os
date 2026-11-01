# Monitoring support

SNMPv3 uses `authPriv`, SHA-256 authentication and AES-128 privacy. Enable this exact combination on each managed device and allow UDP 161 from the AirLink server. ICMP echo is checked independently; a device is online when either ICMP or SNMP responds. Persistent failures cross the configured threshold before producing offline state. The availability report specifically measures observed ICMP samples, so an ICMP-blocking device may have SNMP online status and 0% ICMP availability.

The collector reads standards-defined OIDs only:

| Metric | MIB / OID |
|---|---|
| Uptime | SNMPv2-MIB sysUpTime.0, `1.3.6.1.2.1.1.3.0` |
| Interface names | IF-MIB ifName, `1.3.6.1.2.1.31.1.1.1.1` |
| Link operational state | IF-MIB ifOperStatus, `1.3.6.1.2.1.2.2.1.8` |
| Speed in Mbit/s | IF-MIB ifHighSpeed, `1.3.6.1.2.1.31.1.1.1.15` |
| 64-bit RX / TX counters | IF-MIB ifHCInOctets / ifHCOutOctets, `.31.1.1.1.6` / `.31.1.1.1.10` under `1.3.6.1.2.1` |
| Counter discontinuity | IF-MIB ifCounterDiscontinuityTime, `1.3.6.1.2.1.31.1.1.1.19` |
| CPU load | HOST-RESOURCES-MIB hrProcessorLoad, `1.3.6.1.2.1.25.3.3.1.2` |
| RAM | HOST-RESOURCES-MIB hrStorageType/AllocationUnits/Size/Used, entries explicitly typed hrStorageRam |

Sources: [RFC 3418](https://www.rfc-editor.org/rfc/rfc3418), [RFC 2863](https://www.rfc-editor.org/rfc/rfc2863), [RFC 2790](https://www.rfc-editor.org/rfc/rfc2790).

MikroTik, Ubiquiti, Mimosa and generic devices can be inventoried and polled for these standards **when their firmware exposes them**. Vendor-specific signal strength, radio frequency and wireless client counters are not claimed. Configured sector frequency is inventory metadata, not measured RF telemetry. No vendor OID is guessed. Add a vendor adapter only after reviewing its official MIB and testing against the relevant hardware/firmware.

Traffic rates require two valid samples with a monotonic 64-bit counter, unchanged discontinuity marker and no uptime regression. Missing, reset or wrapped counters produce unavailable values. The chart sums device interfaces and may include traffic seen on both a bridge and member ports; it is not billing-grade aggregate throughput. Table walks are bounded to 256 entries per OID family and 45 seconds overall. Large devices need a reviewed capacity/configuration change.
