
# VLAN Connectivity Diagnostic Report
## Source: VLAN 1 → Destination: VLAN 10

**Summary:** 1 passed, 3 failed, 1 warnings

## ❌ VLAN Existence
**Status:** FAIL
**Message:** Missing VLANs: [1]
**Recommendations:**
- Create missing VLANs: [1]
- Verify VLAN configuration in UniFi Network settings

## ❌ Gateway Configuration
**Status:** FAIL
**Message:** VLAN 10 has no gateway configured
**Recommendations:**
- Configure gateway IP for each VLAN
- Ensure subnet is properly defined
- Verify router/gateway device supports inter-VLAN routing

## ❌ Trunk Configuration
**Status:** FAIL
**Message:** VLAN 1 not found on any trunk ports; VLAN 10 not found on any trunk ports
**Recommendations:**
- Verify VLAN is tagged on trunk ports between switches
- Check switch port profiles include required VLANs
- Ensure trunk ports are properly configured on all switches in path

## ✅ Firewall Rules
**Status:** PASS
**Message:** No obvious blocking firewall rules found

## ⚠️ Port Configuration
**Status:** WARNING
**Message:** Inconsistent VLAN config for profile 'Default'
**Recommendations:**
- Review port profiles for consistency
- Ensure all ports with same profile have same VLAN configuration

## VLAN Configuration
- **VLAN 10** (CCTV): 192.168.10.254/24 → 
