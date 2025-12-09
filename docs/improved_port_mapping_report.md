# Unifi Port Mapping Report
Generated: 2025-04-21 15:15:53

## Network Topology

### Mermaid Diagram

```mermaid
graph TD
  UDMPROMAX["UniFi Dream Machine Pro Max (UDMPROMAX)"]
  placeholder_wan["WAN (Unknown)"]
  placeholder_core_switch["Core Switch (Switch)"]
  placeholder_office_switch["Office Switch (Switch)"]
  placeholder_living_room_ap["Living Room AP (Access Point)"]
  placeholder_bedroom_ap["Bedroom AP (Access Point)"]
  placeholder_kitchen_ap["Kitchen AP (Access Point)"]
  placeholder_garage_ap["Garage AP (Access Point)"]
  placeholder_nas_server["NAS Server (Server)"]
  UDMPROMAX -- "Port 1 (SFP+ 10G) → Internet" --> placeholder_wan
  UDMPROMAX -- "Port 2 (SFP+ 10G) → Uplink" --> placeholder_core_switch
  UDMPROMAX -- "Port 3 (RJ45 1G) → Uplink" --> placeholder_office_switch
  UDMPROMAX -- "Port 4 (RJ45 1G) → LAN1" --> placeholder_living_room_ap
  UDMPROMAX -- "Port 5 (RJ45 1G) → LAN1" --> placeholder_bedroom_ap
  UDMPROMAX -- "Port 6 (RJ45 1G) → LAN1" --> placeholder_kitchen_ap
  UDMPROMAX -- "Port 7 (RJ45 1G) → LAN1" --> placeholder_garage_ap
  UDMPROMAX -- "Port 8 (RJ45 1G) → eth0" --> placeholder_nas_server
```

### Network Diagram

![Network Diagram](network_diagram.png)

## Device Port Details

### UniFi Dream Machine Pro Max (UDMPROMAX)
IP:  | MAC:

| Port | Status | Name | Proposed Name | LLDP/CDP Info | Modified |
|------|--------|------|--------------|--------------|----------|
| 1 (SFP+) | ✅ Up  | Port 1 | Port 1 | WAN (Internet) | ❌ |
| 2 (SFP+) | ✅ Up  | Port 2 | Core Switch (Uplink) | Core Switch (Uplink) | ✅ |
| 3 (RJ45) | ✅ Up  | Port 3 | Office Switch (Uplink) | Office Switch (Uplink) | ✅ |
| 4 (RJ45) | ✅ Up  | Port 4 | Living Room AP (LAN1) | Living Room AP (LAN1) | ✅ |
| 5 (RJ45) | ✅ Up  | Port 5 | Bedroom AP (LAN1) | Bedroom AP (LAN1) | ✅ |
| 6 (RJ45) | ✅ Up  | Port 6 | Kitchen AP (LAN1) | Kitchen AP (LAN1) | ✅ |
| 7 (RJ45) | ✅ Up  | Port 7 | Garage AP (LAN1) | Garage AP (LAN1) | ✅ |
| 8 (RJ45) | ✅ Up  | Port 8 | NAS Server (eth0) | NAS Server (eth0) | ✅ |
| 9 (RJ45) | ✅ Up  | Port 9 | LAN 7 | None | ✅ |
| 10 (RJ45) | ✅ Up  | Port 10 | LAN 8 | None | ✅ |

### WAN (Unknown)
IP:  | MAC:

| Port | Status | Name | Proposed Name | LLDP/CDP Info | Modified |
|------|--------|------|--------------|--------------|----------|
| 1 (Unknown) | ✅ Up | Port 1 | Port 1 | None | ❌ |
| 2 (Unknown) | ✅ Up | Port 2 | Port 2 | None | ❌ |
| 3 (Unknown) | ✅ Up | Port 3 | Port 3 | None | ❌ |
| 4 (Unknown) | ✅ Up | Port 4 | Port 4 | None | ❌ |

### Core Switch (Switch)
IP:  | MAC:

| Port | Status | Name | Proposed Name | LLDP/CDP Info | Modified |
|------|--------|------|--------------|--------------|----------|
| 1 (Unknown) | ✅ Up  | Port 1 | LAN 1 | None | ✅ |
| 2 (Unknown) | ✅ Up  | Port 2 | LAN 2 | None | ✅ |
| 3 (Unknown) | ✅ Up  | Port 3 | LAN 3 | None | ✅ |
| 4 (Unknown) | ✅ Up  | Port 4 | LAN 4 | None | ✅ |

### Office Switch (Switch)
IP:  | MAC:

| Port | Status | Name | Proposed Name | LLDP/CDP Info | Modified |
|------|--------|------|--------------|--------------|----------|
| 1 (Unknown) | ✅ Up  | Port 1 | LAN 1 | None | ✅ |
| 2 (Unknown) | ✅ Up  | Port 2 | LAN 2 | None | ✅ |
| 3 (Unknown) | ✅ Up  | Port 3 | LAN 3 | None | ✅ |
| 4 (Unknown) | ✅ Up  | Port 4 | LAN 4 | None | ✅ |

### Living Room AP (Access Point)
IP:  | MAC:

| Port | Status | Name | Proposed Name | LLDP/CDP Info | Modified |
|------|--------|------|--------------|--------------|----------|
| 1 (Unknown) | ✅ Up | Port 1 | Port 1 | None | ❌ |
| 2 (Unknown) | ✅ Up | Port 2 | Port 2 | None | ❌ |
| 3 (Unknown) | ✅ Up | Port 3 | Port 3 | None | ❌ |
| 4 (Unknown) | ✅ Up | Port 4 | Port 4 | None | ❌ |

### Bedroom AP (Access Point)
IP:  | MAC:

| Port | Status | Name | Proposed Name | LLDP/CDP Info | Modified |
|------|--------|------|--------------|--------------|----------|
| 1 (Unknown) | ✅ Up | Port 1 | Port 1 | None | ❌ |
| 2 (Unknown) | ✅ Up | Port 2 | Port 2 | None | ❌ |
| 3 (Unknown) | ✅ Up | Port 3 | Port 3 | None | ❌ |
| 4 (Unknown) | ✅ Up | Port 4 | Port 4 | None | ❌ |

### Kitchen AP (Access Point)
IP:  | MAC:

| Port | Status | Name | Proposed Name | LLDP/CDP Info | Modified |
|------|--------|------|--------------|--------------|----------|
| 1 (Unknown) | ✅ Up | Port 1 | Port 1 | None | ❌ |
| 2 (Unknown) | ✅ Up | Port 2 | Port 2 | None | ❌ |
| 3 (Unknown) | ✅ Up | Port 3 | Port 3 | None | ❌ |
| 4 (Unknown) | ✅ Up | Port 4 | Port 4 | None | ❌ |

### Garage AP (Access Point)
IP:  | MAC:

| Port | Status | Name | Proposed Name | LLDP/CDP Info | Modified |
|------|--------|------|--------------|--------------|----------|
| 1 (Unknown) | ✅ Up | Port 1 | Port 1 | None | ❌ |
| 2 (Unknown) | ✅ Up | Port 2 | Port 2 | None | ❌ |
| 3 (Unknown) | ✅ Up | Port 3 | Port 3 | None | ❌ |
| 4 (Unknown) | ✅ Up | Port 4 | Port 4 | None | ❌ |

### NAS Server (Server)
IP:  | MAC:

| Port | Status | Name | Proposed Name | LLDP/CDP Info | Modified |
|------|--------|------|--------------|--------------|----------|
| 1 (Unknown) | ✅ Up | Port 1 | Port 1 | None | ❌ |
| 2 (Unknown) | ✅ Up | Port 2 | Port 2 | None | ❌ |
| 3 (Unknown) | ✅ Up | Port 3 | Port 3 | None | ❌ |
| 4 (Unknown) | ✅ Up | Port 4 | Port 4 | None | ❌ |

## Summary of Changes

Total port name changes identified: 7

### UniFi Dream Machine Pro Max

| Port | Current Name | Proposed Name |
|------|--------------|---------------|
| 2 | Port 2 | Core Switch (Uplink) |
| 3 | Port 3 | Office Switch (Uplink) |
| 4 | Port 4 | Living Room AP (LAN1) |
| 5 | Port 5 | Bedroom AP (LAN1) |
| 6 | Port 6 | Kitchen AP (LAN1) |
| 7 | Port 7 | Garage AP (LAN1) |
| 8 | Port 8 | NAS Server (eth0) |

### WAN

| Port | Current Name | Proposed Name |
|------|--------------|---------------|

### Core Switch

| Port | Current Name | Proposed Name |
|------|--------------|---------------|

### Office Switch

| Port | Current Name | Proposed Name |
|------|--------------|---------------|

### Living Room AP

| Port | Current Name | Proposed Name |
|------|--------------|---------------|

### Bedroom AP

| Port | Current Name | Proposed Name |
|------|--------------|---------------|

### Kitchen AP

| Port | Current Name | Proposed Name |
|------|--------------|---------------|

### Garage AP

| Port | Current Name | Proposed Name |
|------|--------------|---------------|

### NAS Server

| Port | Current Name | Proposed Name |
|------|--------------|---------------|
