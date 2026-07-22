# Research and decisions

Research checked 2026-07-22. The selected design is deliberately modular and lightweight.

## Selected stack

- Wireshark's `dumpcap` writes PCAPNG and natively supports bounded time/size/file-count ring buffers: [official manual](https://www.wireshark.org/docs/man-pages/dumpcap.html).
- ntopng provides a live browser view of monitored interfaces, hosts, flows, traffic statistics, and alerts without an OpenSearch/Elastic backend: [official documentation](https://www.ntop.org/guides/ntopng/).
- Zeek provides compact connection and protocol logs. Official LTS containers and binary packages are maintained by the Zeek project: [installation](https://docs.zeek.org/en/lts/install.html).
- Suricata is an optional signature IDS layer, not a requirement for packet capture or network-health analysis: [official documentation](https://docs.suricata.io/).

## Why not Malcolm or Security Onion by default

Both are capable integrated platforms, but their search/indexing/container components are heavier than this request needs. Malcolm's documented minimum is 8 cores and 24 GB RAM; Security Onion standalone lists 4 cores and 24 GB RAM as a minimum. They remain future migration options if centralized retention, analyst cases, rich OT dashboards, multi-sensor management, and full NDR/SIEM workflows become requirements.

- [Malcolm system requirements](https://cisagov.github.io/Malcolm/docs/system-requirements.html)
- [Security Onion hardware requirements](https://docs.securityonion.net/en/2.4/hardware.html)

## OT reachability semantics

The OPC Foundation identifies `opc.tcp://<host>:4840/UADiscovery` as a well-known discovery address, while servers may use other configured endpoints. `FindServers` and `GetEndpoints` still create application traffic, so this project defaults to TCP reachability and requires separate approval for discovery calls: [well-known addresses](https://reference.opcfoundation.org/specs/OPC-10000-6/7.6), [discovery security](https://reference.opcfoundation.org/Core/Part2/v105/docs/7.2).

S7comm commonly uses TCP/102, but an open port neither proves a Siemens device nor proves PLC health. Prefer passive identification from captured S7/PROFINET traffic; use vendor-aware active queries only in a documented test profile approved by the controls owner.
