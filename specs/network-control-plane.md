---
title: "Control Plane"
source: "https://192.168.125.254/unifi-api/network"
author:
published:
created: 2026-01-13
description:
tags:
  - "clippings"
---
Dream Machine Pro UniFi Network API

Network Statistics

UniFi Device List

Client Device List

Settings (Coming Soon)

SiteA

CloudKey+ UniFi Network API

Network Statistics

UniFi Device List

Client Device List

Settings (Coming Soon)

SiteB

Official UniFi Hosting UniFi Network API

Network Statistics

UniFi Device List

Client Device List

Settings (Coming Soon)

SiteC

Network Statistics

UniFi Device List

Client Device List

Settings (Coming Soon)

SiteD

Site Manager API

Site List

Online Status

Internet Health Metrics

Client Device Counts

Updates Available

## UniFi Network API (10.1.68)

## Getting Started

Provides an overview of the UniFi Network API, including authentication using API keys and request format. Start here to understand how to connect and make your first request.

### Introduction

Each UniFi Application has its own API endpoints running locally on each site, offering detailed analytics and control related to that specific application. For a single endpoint with high-level insights across all your UniFi sites, refer to the [UniFi Site Manager API](https://developer.ui.com/).

### Authentication and Request Format

An API Key is a unique identifier used to authenticate API requests. To generate API Keys and view an example of the API Request Format, visit the Integrations section of your UniFi application.

## Filtering

Explains how to use the filter query parameter for advanced querying across list endpoints, including supported property types, syntax, and operators.

Some `GET` and `DELETE` endpoints support filtering using the `filter` query parameter. Each endpoint supporting filtering will have a detailed list of filterable properties, their types, and allowed functions.

### Filtering Syntax

Filtering follows a structured, URL-safe syntax with three types of expressions.

#### 1\. Property Expressions

Apply functions to an individual property using the form `<property>.<function>(<arguments>)`, where argument values are separated by commas.

Examples:

- `id.eq(123)` checks if `id` is equal to `123`;
- `name.isNotNull()` checks if `name` is not null;
- `createdAt.in(2025-01-01, 2025-01-05)` checks if `createdAt` is either `2025-01-01` or `2025-01-05`.

#### 2\. Compound Expressions

Combine two or more expressions with logical operators using the form `<logical-operator>(<expressions>)`, where expressions are separated by commas.

Examples:

- `and(name.isNull(), createdAt.gt(2025-01-01))` checks if `name` is null **and** `createdAt` is greater than `2025-01-01`;
- `or(name.isNull(), expired.isNull(), expiresAt.isNull())` check is **any** of `name`, `expired`, or `expiresAt` is null.

#### 3\. Negation Expressions

Negate any other expressions using the the form `not(<expression>)`.

Example:

- `not(name.like('guest*'))` matches all values except those that start with `guest`.

### Filterable Property Types

The table below lists all supported property types.

| Type | Examples | Syntax |
| --- | --- | --- |
| `STRING` | `'Hello, ''World''!'` | Must be wrapped in single quotes. To escape a single quote, use another single quote. |
| `INTEGER` | `123` | Must start with a digit. |
| `DECIMAL` | `123`, `123.321` | Must start with a digit. Can include a decimal point (.). |
| `TIMESTAMP` | `2025-01-29`, `2025-01-29T12:39:11Z` | Must follow ISO 8601 format (date or date-time). |
| `BOOLEAN` | `true`, `false` | Can be `true` or `false`. |
| `UUID` | `550e8400-e29b-41d4-a716-446655440000` | Must be a valid UUID format (8-4-4-4-12). |
| `SET(STRING\|INTEGER\|DECIMAL\|TIMESTAMP\|UUID)` | `[1, 2, 3, 4, 5]` | A set of (unique) values. |

### Filtering Functions

The table below lists available filtering functions, their arguments, and applicable property types:

| Function | Arguments | Semantics | Supported property types |
| --- | --- | --- | --- |
| `isNull` | 0 | is null | all types |
| `isNotNull` | 0 | is not null | all types |
| `eq` | 1 | equals | `STRING`, `INTEGER`, `DECIMAL`, `TIMESTAMP`, `BOOLEAN`, `UUID` |
| `ne` | 1 | not equals | `STRING`, `INTEGER`, `DECIMAL`, `TIMESTAMP`, `BOOLEAN`, `UUID` |
| `gt` | 1 | greater than | `STRING`, `INTEGER`, `DECIMAL`, `TIMESTAMP`, `UUID` |
| `ge` | 1 | greater than or equals | `STRING`, `INTEGER`, `DECIMAL`, `TIMESTAMP`, `UUID` |
| `lt` | 1 | less than | `STRING`, `INTEGER`, `DECIMAL`, `TIMESTAMP`, `UUID` |
| `le` | 1 | less than or equals | `STRING`, `INTEGER`, `DECIMAL`, `TIMESTAMP`, `UUID` |
| `like` | 1 | matches pattern | `STRING` |
| `in` | 1 or more | one of | `STRING`, `INTEGER`, `DECIMAL`, `TIMESTAMP`, `UUID` |
| `notIn` | 1 or more | not one of | `STRING`, `INTEGER`, `DECIMAL`, `TIMESTAMP`, `UUID` |
| `isEmpty` | 0 | is empty | `SET` |
| `contains` | 1 | contains | `SET` |
| `containsAny` | 1 or more | contains any of | `SET` |
| `containsAll` | 1 or more | contains all of | `SET` |
| `containsExactly` | 1 or more | contains exactly | `SET` |

#### Pattern Matching (like Function)

The `like` function allows matching string properties using simple patterns:

- `.` matches any **single** character. Example: `type.like('type.')` matches `type1`, but not `type100`;
- `*` matches **any number** of characters. Example: `name.like('guest*')` matches `guest1` and `guest100`;
- `\` is used to escape `.` and `*`.

## Application Info

Returns general details about the UniFi Network application, including version and runtime metadata. Useful for integration validation.

## Sites

Endpoints for listing and managing UniFi sites within a local Network application. Site ID is required for most other API requests.

## List Local Sites

Retrieve a paginated list of local sites managed by this Network application. Site ID is required for other UniFi Network API calls.

Filterable properties (click to expand)

| Name | Type | Allowed functions |
| --- | --- | --- |
| `id` | `UUID` | `eq` `ne` `in` `notIn` |
| `internalReference` | `STRING` | `eq` `ne` `in` `notIn` |
| `name` | `STRING` | `eq` `ne` `in` `notIn` |

##### query Parameters

| offset | integer <int32> \>= 0  Default:0 |
| --- | --- |
| limit | integer <int32> \[ 0.. 200 \]  Default:25 |
| filter | string |

### Response samples

- 200

## UniFi Devices

Endpoints to list, inspect, and interact with UniFi devices, including adopted and pending devices. Provides device stats, port control, and actions.

## List Adopted Devices

Retrieve a paginated list of all adopted devices on a site, including basic device information.

Filterable properties (click to expand)

| Name | Type | Allowed functions |
| --- | --- | --- |
| `id` | `UUID` | `eq` `ne` `in` `notIn` |
| `macAddress` | `STRING` | `eq` `ne` `in` `notIn` |
| `ipAddress` | `STRING` | `eq` `ne` `in` `notIn` |
| `name` | `STRING` | `eq` `ne` `in` `notIn` `like` |
| `model` | `STRING` | `eq` `ne` `in` `notIn` |
| `state` | `STRING` | `eq` `ne` `in` `notIn` |
| `supported` | `BOOLEAN` | `eq` `ne` |
| `firmwareVersion` | `STRING` | `isNull` `isNotNull` `eq` `ne` `gt` `ge` `lt` `le` `like` `in` `notIn` |
| `firmwareUpdatable` | `BOOLEAN` | `eq` `ne` |
| `features` | `SET(STRING)` | `isEmpty` `contains` `containsAny` `containsAll` `containsExactly` |
| `interfaces` | `SET(STRING)` | `isEmpty` `contains` `containsAny` `containsAll` `containsExactly` |

##### path Parameters

| siteId  required | string <uuid> |
| --- | --- |

##### query Parameters

| offset | integer <int32> \>= 0  Default:0 |
| --- | --- |
| limit | integer <int32> \[ 0.. 200 \]  Default:25 |
| filter | string |

### Response samples

- 200

## Execute Port Action

Perform an action on a specific device port. The request body must include the action name and any applicable input arguments.

##### path Parameters

| portIdx  required | integer <int32> |
| --- | --- |
| siteId  required | string <uuid> |
| deviceId  required | string <uuid> |

##### Request Body schema: application/jsonrequired

| action  required | string |
| --- | --- |

### Request samples

- Payload

## Execute Adopted Device Action

Perform an action on an specific adopted device. The request body must include the action name and any applicable input arguments.

##### path Parameters

| siteId  required | string <uuid> |
| --- | --- |
| deviceId  required | string <uuid> |

##### Request Body schema: application/jsonrequired

| action  required | string |
| --- | --- |

### Request samples

- Payload

## Get Adopted Device Details

Retrieve detailed information about a specific adopted device, including firmware versioning, uplink state, details about device features and interfaces (ports, radios) and other key attributes.

##### path Parameters

| siteId  required | string <uuid> |
| --- | --- |
| deviceId  required | string <uuid> |

### Response samples

- 200

## Get Latest Adopted Device Statistics

Retrieve the latest real-time statistics of a specific adopted device, such as uptime, data transmission rates, CPU and memory utilization.

##### path Parameters

| siteId  required | string <uuid> |
| --- | --- |
| deviceId  required | string <uuid> |

### Response samples

- 200

## List Devices Pending Adoption

Retrieve a paginated list of devices pending adoption, including basic device information.

Filterable properties (click to expand)

| Name | Type | Allowed functions |
| --- | --- | --- |
| `macAddress` | `STRING` | `eq` `ne` `in` `notIn` |
| `ipAddress` | `STRING` | `eq` `ne` `in` `notIn` |
| `model` | `STRING` | `eq` `ne` `in` `notIn` |
| `state` | `STRING` | `eq` `ne` `in` `notIn` |
| `supported` | `BOOLEAN` | `eq` `ne` |
| `firmwareVersion` | `STRING` | `isNull` `isNotNull` `eq` `ne` `gt` `ge` `lt` `le` `like` `in` `notIn` |
| `firmwareUpdatable` | `BOOLEAN` | `eq` `ne` |
| `features` | `SET(STRING)` | `isEmpty` `contains` `containsAny` `containsAll` `containsExactly` |

##### query Parameters

| offset | integer <int32> \>= 0  Default:0 |
| --- | --- |
| limit | integer <int32> \[ 0.. 200 \]  Default:25 |
| filter | string |

### Response samples

- 200

## Clients

Endpoints for viewing and managing connected clients (wired, wireless, VPN, and guest). Supports actions such as authorizing or unauthorizing guest access.

## Execute Client Action

Perform an action on a specific connected client. The request body must include the action name and any applicable input arguments.

##### path Parameters

| clientId  required | string <uuid> |
| --- | --- |
| siteId  required | string <uuid> |

##### Request Body schema: application/jsonrequired

| action  required | string |
| --- | --- |
| timeLimitMinutes | integer <int64> \[ 1.. 1000000 \]  (Optional) how long (in minutes) the guest will be authorized to access the network. If not specified, the default limit is used from the site settings |
| dataUsageLimitMBytes | integer <int64> \[ 1.. 1048576 \]  (Optional) data usage limit in megabytes |
| rxRateLimitKbps | integer <int64> \[ 2.. 100000 \]  (Optional) download rate limit in kilobits per second |
| txRateLimitKbps | integer <int64> \[ 2.. 100000 \]  (Optional) upload rate limit in kilobits per second |

### Request samples

- Payload

### Response samples

- 200

## List Connected Clients

Retrieve a paginated list of all connected clients on a site, including physical devices (computers, smartphones) and active VPN connections.

Filterable properties (click to expand)

| Name | Type | Allowed functions |
| --- | --- | --- |
| `id` | `UUID` | `eq` `ne` `in` `notIn` |
| `type` | `STRING` | `eq` `ne` `in` `notIn` |
| `macAddress` | `STRING` | `isNull` `isNotNull` `eq` `ne` `in` `notIn` |
| `ipAddress` | `STRING` | `isNull` `isNotNull` `eq` `ne` `in` `notIn` |
| `connectedAt` | `TIMESTAMP` | `isNull` `isNotNull` `eq` `ne` `gt` `ge` `lt` `le` |
| `access.type` | `STRING` | `eq` `ne` `in` `notIn` |
| `access.authorized` | `BOOLEAN` | `isNull` `isNotNull` `eq` `ne` |

##### path Parameters

| siteId  required | string <uuid> |
| --- | --- |

##### query Parameters

| offset | integer <int32> \>= 0  Default:0 |
| --- | --- |
| limit | integer <int32> \[ 0.. 200 \]  Default:25 |
| filter | string |

### Response samples

- 200

## Get Connected Client Details

Retrieve detailed information about a specific connected client, including name, IP address, MAC address, connection type and access information.

##### path Parameters

| clientId  required | string <uuid> |
| --- | --- |
| siteId  required | string <uuid> |

### Response samples

- 200

## Networks

Endpoints for creating, updating, deleting, and inspecting network configurations including VLANs, DHCP, NAT, and IPv4/IPv6 settings.

## Update Network

Update an existing network on a site.

##### path Parameters

| networkId  required | string <uuid> |
| --- | --- |
| siteId  required | string <uuid> |

##### Request Body schema: application/jsonrequired

| management  required | string |
| --- | --- |
| name  required | string non-empty |
| enabled  required | boolean |
| vlanId  required | integer <int32> \[ 2.. 4000 \] |
|  | object (Network DHCP Guarding)  DHCP Guarding settings for this Network. If this field is omitted or null, the feature is disabled |

### Request samples

- Payload

### Response samples

- 200

## List Networks

Retrieve a paginated list of all Networks on a site.

Filterable properties (click to expand)

| Name | Type | Allowed functions |
| --- | --- | --- |
| `management` | `STRING` | `eq` `ne` `in` `notIn` |
| `id` | `UUID` | `eq` `ne` `in` `notIn` |
| `name` | `STRING` | `eq` `ne` `in` `notIn` `like` |
| `enabled` | `BOOLEAN` | `eq` `ne` |
| `vlanId` | `INTEGER` | `eq` `ne` `gt` `ge` `lt` `le` `in` `notIn` |
| `deviceId` | `UUID` | `eq` `ne` `in` `notIn` `isNull` `isNotNull` |
| `metadata.origin` | `STRING` | `eq` `ne` `in` `notIn` |

##### path Parameters

| siteId  required | string <uuid> |
| --- | --- |

##### query Parameters

| offset | integer <int32> \>= 0  Default:0 |
| --- | --- |
| limit | integer <int32> \[ 0.. 200 \]  Default:25 |
| filter | string |

### Response samples

- 200

## Create Network

Create a new network on a site.

##### path Parameters

| siteId  required | string <uuid> |
| --- | --- |

##### Request Body schema: application/jsonrequired

| management  required | string |
| --- | --- |
| name  required | string non-empty |
| enabled  required | boolean |
| vlanId  required | integer <int32> \[ 2.. 4000 \] |
|  | object (Network DHCP Guarding)  DHCP Guarding settings for this Network. If this field is omitted or null, the feature is disabled |

### Request samples

- Payload

### Response samples

- 201

## Update Wifi Broadcast

Update an existing Wifi Broadcast on the specified site.

##### path Parameters

| wifiBroadcastId  required | string <uuid> |
| --- | --- |
| siteId  required | string <uuid> |

##### Request Body schema: application/jsonrequired

| type  required | string |
| --- | --- |
| name  required | string |
|  | object (Wifi network reference) |
| enabled  required | boolean |
| required | object (Wifi security configuration detailObject) |
|  | object (Broadcasting device filter)  Defines the custom scope of devices that will broadcast this WiFi network. If null, the WiFi network will be broadcast by all Access Point capable devices. |
|  | object (mDNS filtering configuration) |
|  | object (Multicast filtering policy) |
| multicastToUnicastConversionEnabled  required | boolean |
| clientIsolationEnabled  required | boolean |
| hideName  required | boolean |
| uapsdEnabled  required | boolean  Indicates whether Unscheduled Automatic Power Save Delivery (U-APSD) is enabled |
|  | object (IntegrationWifiBasicDataRateConfigurationDto) |
|  | object (IntegrationWifiClientFilteringPolicyDto)  Client connection filtering policy. Allow/restrict access to the WiFi network based on client device MAC addresses. |
|  | object (Integration blackout schedule configuration) |
| broadcastingFrequenciesGHz  required | Array of numbers \[ 1.. 2147483647 \] items unique  ItemsEnum:2.4 5 6 |
|  | object (Wifi hotspot configuration) |
| mloEnabled | boolean |
| bandSteeringEnabled | boolean |
| arpProxyEnabled  required | boolean |
| bssTransitionEnabled  required | boolean |
| advertiseDeviceName  required | boolean  Indicates whether the device name is advertised in beacon frames. |
|  | object (IntegrationWifiDtimPeriodConfigurationDto) |

### Request samples

- Payload

### Response samples

- 200

## List Wifi Broadcasts

Retrieve a paginated list of all Wifi Broadcasts on a site.

Filterable properties (click to expand)

| Name | Type | Allowed functions |
| --- | --- | --- |
| `type` | `STRING` | `eq` `ne` `in` `notIn` |
| `id` | `UUID` | `eq` `ne` `in` `notIn` |
| `enabled` | `BOOLEAN` | `eq` `ne` |
| `name` | `STRING` | `eq` `ne` `in` `notIn` `like` |
| `broadcastingFrequenciesGHz` | `SET(DECIMAL)` | `contains` `containsAny` `containsAll` `containsExactly` |
| `metadata.origin` | `STRING` | `eq` `ne` `in` `notIn` |
| `network.type` | `STRING` | `eq` `ne` `in` `notIn` `isNull` `isNotNull` |
| `network.networkId` | `UUID` | `eq` `ne` `in` `notIn` |
| `securityConfiguration.type` | `STRING` | `eq` `ne` `in` `notIn` |
| `broadcastingDeviceFilter.type` | `STRING` | `eq` `ne` `in` `notIn` `isNull` `isNotNull` |
| `broadcastingDeviceFilter.deviceIds` | `SET(UUID)` | `contains` `containsAny` `containsAll` `containsExactly` |
| `broadcastingDeviceFilter.deviceTagIds` | `SET(UUID)` | `contains` `containsAny` `containsAll` `containsExactly` |
| `hotspotConfiguration.type` | `STRING` | `eq` `ne` `in` `notIn` |

##### path Parameters

| siteId  required | string <uuid> |
| --- | --- |

##### query Parameters

| offset | integer <int32> \>= 0  Default:0 |
| --- | --- |
| limit | integer <int32> \[ 0.. 200 \]  Default:25 |
| filter | string |

### Response samples

- 200

## Create Wifi Broadcast

Create a new Wifi Broadcast on the specified site.

##### path Parameters

| siteId  required | string <uuid> |
| --- | --- |

##### Request Body schema: application/jsonrequired

| type  required | string |
| --- | --- |
| name  required | string |
|  | object (Wifi network reference) |
| enabled  required | boolean |
| required | object (Wifi security configuration detailObject) |
|  | object (Broadcasting device filter)  Defines the custom scope of devices that will broadcast this WiFi network. If null, the WiFi network will be broadcast by all Access Point capable devices. |
|  | object (mDNS filtering configuration) |
|  | object (Multicast filtering policy) |
| multicastToUnicastConversionEnabled  required | boolean |
| clientIsolationEnabled  required | boolean |
| hideName  required | boolean |
| uapsdEnabled  required | boolean  Indicates whether Unscheduled Automatic Power Save Delivery (U-APSD) is enabled |
|  | object (IntegrationWifiBasicDataRateConfigurationDto) |
|  | object (IntegrationWifiClientFilteringPolicyDto)  Client connection filtering policy. Allow/restrict access to the WiFi network based on client device MAC addresses. |
|  | object (Integration blackout schedule configuration) |
| broadcastingFrequenciesGHz  required | Array of numbers \[ 1.. 2147483647 \] items unique  ItemsEnum:2.4 5 6 |
|  | object (Wifi hotspot configuration) |
| mloEnabled | boolean |
| bandSteeringEnabled | boolean |
| arpProxyEnabled  required | boolean |
| bssTransitionEnabled  required | boolean |
| advertiseDeviceName  required | boolean  Indicates whether the device name is advertised in beacon frames. |
|  | object (IntegrationWifiDtimPeriodConfigurationDto) |

### Request samples

- Payload

### Response samples

- 201

## Hotspot

Endpoints for managing guest access via Hotspot vouchers — create, list, or revoke vouchers and track their usage and expiration.

## List Vouchers

Retrieve a paginated list of Hotspot vouchers.

Filterable properties (click to expand)

| Name | Type | Allowed functions |
| --- | --- | --- |
| `id` | `UUID` | `eq` `ne` `in` `notIn` |
| `createdAt` | `TIMESTAMP` | `eq` `ne` `gt` `ge` `lt` `le` |
| `name` | `STRING` | `eq` `ne` `in` `notIn` `like` |
| `code` | `STRING` | `eq` `ne` `in` `notIn` |
| `authorizedGuestLimit` | `INTEGER` | `isNull` `isNotNull` `eq` `ne` `gt` `ge` `lt` `le` |
| `authorizedGuestCount` | `INTEGER` | `eq` `ne` `gt` `ge` `lt` `le` |
| `activatedAt` | `TIMESTAMP` | `eq` `ne` `gt` `ge` `lt` `le` |
| `expiresAt` | `TIMESTAMP` | `eq` `ne` `gt` `ge` `lt` `le` |
| `expired` | `BOOLEAN` | `eq` `ne` |
| `timeLimitMinutes` | `INTEGER` | `eq` `ne` `gt` `ge` `lt` `le` |
| `dataUsageLimitMBytes` | `INTEGER` | `isNull` `isNotNull` `eq` `ne` `gt` `ge` `lt` `le` |
| `rxRateLimitKbps` | `INTEGER` | `isNull` `isNotNull` `eq` `ne` `gt` `ge` `lt` `le` |
| `txRateLimitKbps` | `INTEGER` | `isNull` `isNotNull` `eq` `ne` `gt` `ge` `lt` `le` |

##### path Parameters

| siteId  required | string <uuid> |
| --- | --- |

##### query Parameters

| offset | integer <int32> \>= 0  Default:0 |
| --- | --- |
| limit | integer <int32> \[ 0.. 1000 \]  Default:100 |
| filter | string |

### Response samples

- 200

## Generate Vouchers

Create one or more Hotspot vouchers.

##### path Parameters

| siteId  required | string <uuid> |
| --- | --- |

##### Request Body schema: application/jsonrequired

| count | integer <int32> \[ 1.. 1000 \]  Default:1  Number of vouchers to generate |
| --- | --- |
| name  required | string non-empty  Voucher note, duplicated across all generated vouchers |
| authorizedGuestLimit | integer <int64> \>= 1  (Optional) limit for how many different guests can use the same voucher to authorize network access |
| timeLimitMinutes  required | integer <int64> \[ 1.. 1000000 \] |
| dataUsageLimitMBytes | integer <int64> \[ 1.. 1048576 \]  (Optional) data usage limit in megabytes |
| rxRateLimitKbps | integer <int64> \[ 2.. 100000 \]  (Optional) download rate limit in kilobits per second |
| txRateLimitKbps | integer <int64> \[ 2.. 100000 \]  (Optional) upload rate limit in kilobits per second |

### Request samples

- Payload

### Response samples

- 201

## Delete Vouchers

Remove Hotspot vouchers based on the specified filter criteria.

Filterable properties (click to expand)

| Name | Type | Allowed functions |
| --- | --- | --- |
| `id` | `UUID` | `eq` `ne` `in` `notIn` |
| `createdAt` | `TIMESTAMP` | `eq` `ne` `gt` `ge` `lt` `le` |
| `name` | `STRING` | `eq` `ne` `in` `notIn` `like` |
| `code` | `STRING` | `eq` `ne` `in` `notIn` |
| `authorizedGuestLimit` | `INTEGER` | `isNull` `isNotNull` `eq` `ne` `gt` `ge` `lt` `le` |
| `authorizedGuestCount` | `INTEGER` | `eq` `ne` `gt` `ge` `lt` `le` |
| `activatedAt` | `TIMESTAMP` | `eq` `ne` `gt` `ge` `lt` `le` |
| `expiresAt` | `TIMESTAMP` | `eq` `ne` `gt` `ge` `lt` `le` |
| `expired` | `BOOLEAN` | `eq` `ne` |
| `timeLimitMinutes` | `INTEGER` | `eq` `ne` `gt` `ge` `lt` `le` |
| `dataUsageLimitMBytes` | `INTEGER` | `isNull` `isNotNull` `eq` `ne` `gt` `ge` `lt` `le` |
| `rxRateLimitKbps` | `INTEGER` | `isNull` `isNotNull` `eq` `ne` `gt` `ge` `lt` `le` |
| `txRateLimitKbps` | `INTEGER` | `isNull` `isNotNull` `eq` `ne` `gt` `ge` `lt` `le` |

##### path Parameters

| siteId  required | string <uuid> |
| --- | --- |

##### query Parameters

| filter  required | string |
| --- | --- |

### Response samples

- 200

## Firewall

Endpoints for managing custom firewall zones and policies within a site. Define or update network segmentation and security boundaries.

## Update Firewall Zone

Update a firewall zone on a site.

##### path Parameters

| firewallZoneId  required | string <uuid> |
| --- | --- |
| siteId  required | string <uuid> |

##### Request Body schema: application/jsonrequired

| name  required | string  Name of a firewall zone |
| --- | --- |
| networkIds  required | Array of strings <uuid> \>= 0 items \[ items <uuid > \]  List of Network IDs |

### Request samples

- Payload

### Response samples

- 200

## Update Firewall Policy

Update an existing firewall policy on a site.

##### path Parameters

| firewallPolicyId  required | string <uuid> |
| --- | --- |
| siteId  required | string <uuid> |

##### Request Body schema: application/jsonrequired

| enabled  required | boolean |
| --- | --- |
| name  required | string non-empty |
| description | string |
| required | object (Firewall policy action)  Defines action for matched traffic. |
| required | object (Firewall policy source) |
| required | object (Firewall policy destination) |
| required | object (Firewall policy IP protocol scope)  Defines rules for matching by IP version and protocol. |
| connectionStateFilter |  |
| ipsecFilter | string  Enum:"MATCH\_ENCRYPTED" "MATCH\_NOT\_ENCRYPTED"  Match on traffic encrypted, or not encrypted by IPsec. If null, matches all traffic. |
| loggingEnabled  required | boolean  Generate syslog entries when traffic is matched. Such entries are sent to a remote syslog server. |
|  | object (Firewall schedule)  Defines date and time when the entity is active. If null, the entity is always active. |

### Request samples

- Payload

### Response samples

- 200

## Reorder User-Defined Firewall Policies

Reorder user-defined firewall policies for a specific source/destination zone pair.

##### path Parameters

| siteId  required | string <uuid> |
| --- | --- |

##### query Parameters

| sourceFirewallZoneId  required | string <uuid> |
| --- | --- |
| destinationFirewallZoneId  required | string <uuid> |

##### Request Body schema: application/jsonrequired

| required | object (Ordered firewall policy IDs) |
| --- | --- |

### Request samples

- Payload

### Response samples

- 200

## List Firewall Zones

Retrieve a list of all firewall zones on a site.

Filterable properties (click to expand)

| Name | Type | Allowed functions |
| --- | --- | --- |
| `id` | `UUID` | `eq` `ne` `in` `notIn` |
| `name` | `STRING` | `eq` `ne` `in` `notIn` `like` |
| `metadata.origin` | `STRING` | `eq` `ne` `in` `notIn` |
| `metadata.configurable` | `BOOLEAN` | `eq` `ne` `isNull` `isNotNull` |

##### path Parameters

| siteId  required | string <uuid> |
| --- | --- |

##### query Parameters

| offset | integer <int32> \>= 0  Default:0 |
| --- | --- |
| limit | integer <int32> \[ 0.. 200 \]  Default:25 |
| filter | string |

### Response samples

- 200

## Create Custom Firewall Zone

Create a new custom firewall zone on a site.

##### path Parameters

| siteId  required | string <uuid> |
| --- | --- |

##### Request Body schema: application/jsonrequired

| name  required | string  Name of a firewall zone |
| --- | --- |
| networkIds  required | Array of strings <uuid> \>= 0 items \[ items <uuid > \]  List of Network IDs |

### Request samples

- Payload

### Response samples

- 201

## List Firewall Policies

Retrieve a list of all firewall policies on a site.

Filterable properties (click to expand)

| Name | Type | Allowed functions |
| --- | --- | --- |
| `id` | `UUID` | `eq` `ne` `in` `notIn` |
| `name` | `STRING` | `eq` `ne` `in` `notIn` `like` |
| `source.firewallZoneId` | `UUID` | `eq` `ne` `in` `notIn` |
| `destination.firewallZoneId` | `UUID` | `eq` `ne` `in` `notIn` |
| `metadata.origin` | `STRING` | `eq` `ne` `in` `notIn` |

##### path Parameters

| siteId  required | string <uuid> |
| --- | --- |

##### query Parameters

| offset | integer <int32> \>= 0  Default:0 |
| --- | --- |
| limit | integer <int32> \[ 0.. 200 \]  Default:25 |
| filter | string |

### Response samples

- 200

## Create Firewall Policy

Create a new firewall policy on a site.

##### path Parameters

| siteId  required | string <uuid> |
| --- | --- |

##### Request Body schema: application/jsonrequired

| enabled  required | boolean |
| --- | --- |
| name  required | string non-empty |
| description | string |
| required | object (Firewall policy action)  Defines action for matched traffic. |
| required | object (Firewall policy source) |
| required | object (Firewall policy destination) |
| required | object (Firewall policy IP protocol scope)  Defines rules for matching by IP version and protocol. |
| connectionStateFilter |  |
| ipsecFilter | string  Enum:"MATCH\_ENCRYPTED" "MATCH\_NOT\_ENCRYPTED"  Match on traffic encrypted, or not encrypted by IPsec. If null, matches all traffic. |
| loggingEnabled  required | boolean  Generate syslog entries when traffic is matched. Such entries are sent to a remote syslog server. |
|  | object (Firewall schedule)  Defines date and time when the entity is active. If null, the entity is always active. |

### Request samples

- Payload

### Response samples

- 201

## Access Control (ACL Rules)

Endpoints for creating, listing, and managing ACL (Access Control List) rule that enforce traffic filtering across devices and networks.

## Update ACL Rule

Update an existing user defined ACL rule on a site.

##### path Parameters

| aclRuleId  required | string <uuid> |
| --- | --- |
| siteId  required | string <uuid> |

##### Request Body schema: application/jsonrequired

| type  required | string |
| --- | --- |
| enabled  required | boolean |
| name  required | string non-empty  ACL rule name |
| description | string  ACL rule description |
| action  required | string  Enum:"ALLOW" "BLOCK"  ACL rule action |
|  | object (ACL rule device filter)  IDs of the Switch-capable devices used to enforce the ACL rule. When null, the rule will be provisioned to all switches on the site. |
| index | integer <int32> \>= 0  Deprecated  ACL rule index. This property is deprecated and has no effect. Use the dedicated ACL rule reordering endpoint. |
|  | object  Traffic source filter |
|  | object  Traffic destination filter |
| protocolFilter | Array of strings \[ 1.. 2147483647 \] items unique  ItemsEnum:"TCP" "UDP"  Protocols this ACL rule will be applied to. When null, the rule will be applied to all protocols. |

### Request samples

- Payload

### Response samples

- 200

### Request samples

- Payload

### Response samples

- 200

## List ACL Rules

Retrieve a paginated list of all ACL rules on a site.

Filterable properties (click to expand)

| Name | Type | Allowed functions |
| --- | --- | --- |
| `type` | `STRING` | `eq` `ne` `in` `notIn` |
| `id` | `UUID` | `eq` `ne` `in` `notIn` |
| `enabled` | `BOOLEAN` | `eq` `ne` |
| `name` | `STRING` | `eq` `ne` `in` `notIn` `like` |
| `description` | `STRING` | `isNull` `isNotNull` `eq` `ne` `in` `notIn` `like` |
| `action` | `STRING` | `eq` `ne` `in` `notIn` |
| `index` | `INTEGER` | `eq` `ne` `gt` `ge` `lt` `le` `in` `notIn` |
| `protocolsFilter` | `SET(STRING)` | `isNull` `isNotNull` `contains` `containsAny` `containsAll` `containsExactly` |
| `networkId` | `UUID` | `isNull` `isNotNull` `eq` `ne` `in` `notIn` |
| `enforcingDeviceFilter.deviceIds` | `SET(UUID)` | `isNull` `isNotNull` `contains` `containsAny` `containsAll` `containsExactly` |
| `metadata.origin` | `STRING` | `eq` `ne` `in` `notIn` |
| `sourceFilter.type` | `STRING` | `isNull` `isNotNull` `eq` `ne` `in` `notIn` |
| `sourceFilter.ipAddressesOrSubnets` | `SET(STRING)` | `contains` `containsAny` `containsAll` `containsExactly` |
| `sourceFilter.portsFilter` | `SET(INTEGER)` | `isNull` `isNotNull` `contains` `containsAny` `containsAll` `containsExactly` |
| `sourceFilter.networkIds` | `SET(UUID)` | `contains` `containsAny` `containsAll` `containsExactly` |
| `sourceFilter.macAddresses` | `SET(STRING)` | `contains` `containsAny` `containsAll` `containsExactly` |
| `sourceFilter.prefixLength` | `INTEGER` | `isNull` `isNotNull` `eq` `ne` `gt` `ge` `lt` `le` `in` `notIn` |
| `destinationFilter.type` | `STRING` | `isNull` `isNotNull` `eq` `ne` `in` `notIn` |
| `destinationFilter.ipAddressesOrSubnets` | `SET(STRING)` | `contains` `containsAny` `containsAll` `containsExactly` |
| `destinationFilter.portsFilter` | `SET(INTEGER)` | `isNull` `isNotNull` `contains` `containsAny` `containsAll` `containsExactly` |
| `destinationFilter.networkIds` | `SET(UUID)` | `contains` `containsAny` `containsAll` `containsExactly` |
| `destinationFilter.macAddresses` | `SET(STRING)` | `contains` `containsAny` `containsAll` `containsExactly` |
| `destinationFilter.prefixLength` | `INTEGER` | `isNull` `isNotNull` `eq` `ne` `gt` `ge` `lt` `le` `in` `notIn` |

##### path Parameters

| siteId  required | string <uuid> |
| --- | --- |

##### query Parameters

| offset | integer <int32> \>= 0  Default:0 |
| --- | --- |
| limit | integer <int32> \[ 0.. 200 \]  Default:25 |
| filter | string |

### Response samples

- 200

## Create ACL Rule

Create a new user defined ACL rule on a site.

##### path Parameters

| siteId  required | string <uuid> |
| --- | --- |

##### Request Body schema: application/jsonrequired

| type  required | string |
| --- | --- |
| enabled  required | boolean |
| name  required | string non-empty  ACL rule name |
| description | string  ACL rule description |
| action  required | string  Enum:"ALLOW" "BLOCK"  ACL rule action |
|  | object (ACL rule device filter)  IDs of the Switch-capable devices used to enforce the ACL rule. When null, the rule will be provisioned to all switches on the site. |
| index | integer <int32> \>= 0  Deprecated  ACL rule index. This property is deprecated and has no effect. Use the dedicated ACL rule reordering endpoint. |
|  | object  Traffic source filter |
|  | object  Traffic destination filter |
| protocolFilter | Array of strings \[ 1.. 2147483647 \] items unique  ItemsEnum:"TCP" "UDP"  Protocols this ACL rule will be applied to. When null, the rule will be applied to all protocols. |

### Request samples

- Payload

### Response samples

- 201

## DNS Policies

Endpoints for managing DNS Policies within a site.

## Update DNS Policy

Update an existing DNS policy on a site.

##### path Parameters

| dnsPolicyId  required | string <uuid> |
| --- | --- |
| siteId  required | string <uuid> |

##### Request Body schema: application/jsonrequired

| type  required | string |
| --- | --- |
| enabled  required | boolean |
| domain  required | string \[ 1.. 127 \] characters |
| ipv4Address  required | string |
| ttlSeconds  required | integer <int32> \[ 0.. 604800 \]  Time to live in seconds. |

### Request samples

- Payload

### Response samples

- 200

## List DNS Policies

Retrieve a paginated list of all DNS policies on a site.

Filterable properties (click to expand)

| Name | Type | Allowed functions |
| --- | --- | --- |
| `type` | `STRING` | `eq` `ne` `in` `notIn` |
| `id` | `UUID` | `eq` `ne` `in` `notIn` |
| `enabled` | `BOOLEAN` | `eq` `ne` |
| `domain` | `STRING` | `eq` `ne` `in` `notIn` `like` |
| `ipv4Address` | `STRING` | `eq` `ne` `in` `notIn` `like` |
| `ipv6Address` | `STRING` | `eq` `ne` `in` `notIn` `like` |
| `targetDomain` | `STRING` | `eq` `ne` `in` `notIn` `like` |
| `mailServerDomain` | `STRING` | `eq` `ne` `in` `notIn` `like` |
| `text` | `STRING` | `eq` `ne` `in` `notIn` `like` |
| `serverDomain` | `STRING` | `eq` `ne` `in` `notIn` `like` |
| `ipAddress` | `STRING` | `eq` `ne` `in` `notIn` `like` |
| `ttlSeconds` | `INTEGER` | `eq` `ne` `gt` `ge` `lt` `le` `in` `notIn` |
| `priority` | `INTEGER` | `eq` `ne` `gt` `ge` `lt` `le` `in` `notIn` |
| `service` | `STRING` | `eq` `ne` `in` `notIn` |
| `protocol` | `STRING` | `eq` `ne` `in` `notIn` |
| `port` | `INTEGER` | `eq` `ne` `gt` `ge` `lt` `le` `in` `notIn` |
| `weight` | `INTEGER` | `eq` `ne` `gt` `ge` `lt` `le` `in` `notIn` |

##### path Parameters

| siteId  required | string <uuid> |
| --- | --- |

##### query Parameters

| offset | integer <int32> \>= 0  Default:0 |
| --- | --- |
| limit | integer <int32> \[ 0.. 200 \]  Default:25 |
| filter | string |

### Response samples

- 200

## Create DNS Policy

Create a new DNS policy on a site.

##### path Parameters

| siteId  required | string <uuid> |
| --- | --- |

##### Request Body schema: application/jsonrequired

| type  required | string |
| --- | --- |
| enabled  required | boolean |
| domain  required | string \[ 1.. 127 \] characters |
| ipv4Address  required | string |
| ttlSeconds  required | integer <int32> \[ 0.. 604800 \]  Time to live in seconds. |

### Request samples

- Payload

### Response samples

- 201

## Traffic Matching Lists

Endpoints for managing port and IP address lists used across firewall policy configurations.

## Update Traffic Matching List

Update an exist traffic matching list on a site.

##### path Parameters

| trafficMatchingListId  required | string <uuid> |
| --- | --- |
| siteId  required | string <uuid> |

##### Request Body schema: application/jsonrequired

| type  required | string |
| --- | --- |
| name  required | string non-empty |
| required | Array of objects (Port matching) non-empty |

### Request samples

- Payload

### Response samples

- 200

## List Traffic Matching Lists

Retrieve all traffic matching lists on a site.

Filterable properties (click to expand)

| Name | Type | Allowed functions |
| --- | --- | --- |
| `id` | `UUID` | `eq` `ne` `in` `notIn` |
| `name` | `STRING` | `eq` `ne` `in` `notIn` `like` |

##### path Parameters

| siteId  required | string <uuid> |
| --- | --- |

##### query Parameters

| offset | integer <int32> \>= 0  Default:0 |
| --- | --- |
| limit | integer <int32> \[ 0.. 200 \]  Default:25 |
| filter | string |

### Response samples

- 200

## Create Traffic Matching List

Create a new traffic matching list on a site.

##### path Parameters

| siteId  required | string <uuid> |
| --- | --- |

##### Request Body schema: application/jsonrequired

| type  required | string |
| --- | --- |
| name  required | string non-empty |
| required | Array of objects (Port matching) non-empty |

### Request samples

- Payload

### Response samples

- 201

## Supporting Resources

Contains read-only reference endpoints used to retrieve supporting data such as WAN interfaces, DPI categories, country codes, RADIUS profiles, and device tags.

## List WAN Interfaces

Returns available WAN interface definitions for a given site, including identifiers and names. Useful for network and NAT configuration.

##### path Parameters

| siteId  required | string <uuid> |
| --- | --- |

##### query Parameters

| offset | integer <int32> \>= 0  Default:0 |
| --- | --- |
| limit | integer <int32> \[ 0.. 200 \]  Default:25 |

### Response samples

- 200

## List Site-To-Site VPN Tunnels

Retrieve a paginated list of all site-to-site VPN tunnels on a site.

Filterable properties (click to expand)

| Name | Type | Allowed functions |
| --- | --- | --- |
| `type` | `STRING` | `eq` `ne` `in` `notIn` |
| `id` | `UUID` | `eq` `ne` `in` `notIn` |
| `name` | `STRING` | `eq` `ne` `in` `notIn` `like` |
| `metadata.origin` | `STRING` | `eq` `ne` `in` `notIn` |
| `metadata.source` | `STRING` | `eq` `ne` `in` `notIn` `isNull` `isNotNull` |

##### path Parameters

| siteId  required | string <uuid> |
| --- | --- |

##### query Parameters

| offset | integer <int32> \>= 0  Default:0 |
| --- | --- |
| limit | integer <int32> \[ 0.. 200 \]  Default:25 |
| filter | string |

### Response samples

- 200

## List VPN Servers

Retrieve a paginated list of all VPN servers on a site.

Filterable properties (click to expand)

| Name | Type | Allowed functions |
| --- | --- | --- |
| `type` | `STRING` | `eq` `ne` `in` `notIn` |
| `id` | `UUID` | `eq` `ne` `in` `notIn` |
| `name` | `STRING` | `eq` `ne` `in` `notIn` `like` |
| `enabled` | `BOOLEAN` | `eq` `ne` |
| `metadata.origin` | `STRING` | `eq` `ne` `in` `notIn` |

##### path Parameters

| siteId  required | string <uuid> |
| --- | --- |

##### query Parameters

| offset | integer <int32> \>= 0  Default:0 |
| --- | --- |
| limit | integer <int32> \[ 0.. 200 \]  Default:25 |
| filter | string |

### Response samples

- 200

## List Device Tags

Returns all device tags defined within a site, which can be used for WiFi Broadcast assignments.

Filterable properties (click to expand)

| Name | Type | Allowed functions |
| --- | --- | --- |
| `id` | `UUID` | `eq` `ne` `in` `notIn` |
| `name` | `STRING` | `eq` `ne` `in` `notIn` `like` |
| `deviceIds` | `SET(UUID)` | `contains` `containsAny` `containsAll` `containsExactly` |

##### path Parameters

| siteId  required | string <uuid> |
| --- | --- |

##### query Parameters

| offset | integer <int32> \>= 0  Default:0 |
| --- | --- |
| limit | integer <int32> \[ 0.. 200 \]  Default:25 |
| filter | any (FilterExpression) |

### Response samples

- 200

## List DPI Application Categories

Returns predefined Deep Packet Inspection (DPI) application categories used for traffic identification and filtering.

Filterable properties (click to expand)

| Name | Type | Allowed functions |
| --- | --- | --- |
| `id` | `INTEGER` | `eq` `ne` `in` `notIn` |
| `name` | `STRING` | `eq` `ne` `in` `notIn` `like` |

##### query Parameters

| offset | integer <int32> \>= 0  Default:0 |
| --- | --- |
| limit | integer <int32> \[ 0.. 200 \]  Default:25 |
| filter | string |

### Response samples

- 200

## List DPI Applications

Lists DPI-recognized applications grouped under categories. Useful for firewall or traffic analytics integration.

Filterable properties (click to expand)

| Name | Type | Allowed functions |
| --- | --- | --- |
| `id` | `INTEGER` | `eq` `ne` `in` `notIn` |
| `name` | `STRING` | `eq` `ne` `in` `notIn` `like` |

##### query Parameters

| offset | integer <int32> \>= 0  Default:0 |
| --- | --- |
| limit | integer <int32> \[ 0.. 200 \]  Default:25 |
| filter | string |

### Response samples

- 200

## List Countries

Returns ISO-standard country codes and names, used for region-based configuration or regulatory compliance.

Filterable properties (click to expand)

| Name | Type | Allowed functions |
| --- | --- | --- |
| `code` | `STRING` | `eq` `ne` `in` `notIn` |
| `name` | `STRING` | `eq` `ne` `in` `notIn` `like` |

##### query Parameters

| offset | integer <int32> \>= 0  Default:0 |
| --- | --- |
| limit | integer <int32> \[ 0.. 200 \]  Default:25 |
| filter | string |

### Response samples

- 200