Dream Machine ProUniFi Network API

Network Statistics

UniFi Device List

Client Device List

Settings (Coming Soon)

Site A

CloudKey+UniFi Network API

Network Statistics

UniFi Device List

Client Device List

Settings (Coming Soon)

Site B

Official UniFi HostingUniFi Network API

Network Statistics

UniFi Device List

Client Device List

Settings (Coming Soon)

Site C

Network Statistics

UniFi Device List

Client Device List

Settings (Coming Soon)

Site D

Site Manager API

Site List

Online Status

Internet Health Metrics

Client Device Counts

Updates Available

## UniFi Network API (9.1.105)

## [](https://192.168.125.254/unifi-api/network#tag/Generic-information)Generic information

## [](https://192.168.125.254/unifi-api/network#schema/Error-response)Error response

| statusCode  |                                                        integer <int32>                                                         |
|-------------|--------------------------------------------------------------------------------------------------------------------------------|
| statusName  |                                                             string                                                             |
|   message   |                                                             string                                                             |
|  timestamp  |                                                       string <date-time>                                                       |
| requestPath |                                                             string                                                             |
|  requestId  | string <uuid>

In case of Internal Server Error (core = 500), request ID can be used to track down the error in the server log |

`{`

-   `"statusCode": 400,`
    
-   `"statusName": "UNAUTHORIZED",`
    
-   `"message": "Missing credentials",`
    
-   `"timestamp": "2024-11-27T08:13:46.966Z",`
    
-   `"requestPath": "/integration/v1/sites/123",`
    
-   `"requestId": "3fa85f64-5717-4562-b3fc-2c963f66afa6"`
    

`}`

## [](https://192.168.125.254/unifi-api/network#tag/Generic-information/Filtering)Filtering

Some `GET` and `DELETE` endpoints support filtering via request parameter `filter`.

Filtering uses a URL-safe syntax, which includes:

-   **Property expressions** using various filtering functions;
-   **Compound expressions**, which combines multiple property, compound and "not" expressions using logical operators like `and` and `or`;
-   **"Not" expressions**, which negate property, compound and "not" expressions.

Property expression syntax is `<property>.<function>(<arguments>)`. Argument values must be separated by comma. Examples:

-   `id.eq(123)` checks if `id` is equal to `123`;
-   `name.isNotNull()` checks if `name` is null;
-   `createdAt.in(2025-01-01, 2025-01-05)` checks if `createdAt` is one of `2025-01-01` or `2025-01-05`

Compound expression syntax is `<logical-operator>(<expressions>)`. Expressions must separated by comma. There must be at least two expressions inside a compound expression. Examples:

-   `and(name.isNull(), createdAt.gt(2025-01-01))` checks if `name` is null **and** `createdAt` is greater than `2025-01-01`;
-   `or(name.isNull(), expired.isNull(), expiresAt.isNull())` check is either of `name`, `expired` or `expiresAt` is null.

"Not" expression syntax is `not(<expression>)`. Example:

-   `not(name.like('guest*'))`

Filterable property type can be one of `STRING`, `NUMBER`, `TIMESTAMP`, `BOOLEAN` and `UUID`. Each type has a distinct literal syntax, which should be used in filter expressions:

-   `STRING` literal must be wrapped in single-quotes. Single-quote must be escaped with another single-quote. For example: `'Hello, ''World''!'`;
-   `NUMBER` literal must start with a digit. Numbers may have optional decimal part, using dot as separator. For example: `123.321`;
-   `TIMESTAMP` literal must be ISO 8601 date or date-time, using standard separators. For example: `2025-01-29`, `2025-01-29T12:39:11Z`;
-   `BOOLEAN` literal is either `true` or `false`;
-   `UUID` literal is a string UUID representation (without any quotes), using the 8-4-4-4-12 format. For example: `550e8400-e29b-41d4-a716-446655440000`.

Below is the table of all supported property filtering functions. Not all property types support all functions. Different functions have different number of arguments. Argument type required for a particular function reference in the filter expression is determined by the property type.

| Function  | Arguments |       Semantics        |   Supported property types   |
|-----------|-----------|------------------------|------------------------------|
|  `isNull`   |     0     |        is null         |          all types           |
| `isNotNull` |     0     |      is not null       |          all types           |
|    `eq`     |     1     |         equals         |          all types           |
|    `ne`     |     1     |       not equals       |          all types           |
|    `gt`     |     1     |      greater than      | `STRING` `NUMBER` `TIMESTAMP` `UUID` |
|    `ge`     |     1     | greater than or equals | `STRING` `NUMBER` `TIMESTAMP` `UUID` |
|    `lt`     |     1     |       less than        | `STRING` `NUMBER` `TIMESTAMP` `UUID` |
|    `le`     |     1     |  less than or equals   | `STRING` `NUMBER` `TIMESTAMP` `UUID` |
|   `like`    |     1     |   matches pattern\*    |            `STRING`            |
|    `in`     | 1 or more |         one of         | `STRING` `NUMBER` `TIMESTAMP` `UUID` |
|   `notIn`   | 1 or more |       not one of       | `STRING` `NUMBER` `TIMESTAMP` `UUID` |

\*`like` allows matching string properties against simple patterns, which comply to the following rules:

-   `.` matches to any 1 character. For example: `type.like('type.')` will match `type1`, but will not match `type100`;
-   `*` matches to any number of any characters. For example: `name.like('guest*')` will match both `guest1` and `guest100`;
-   `\` can be used to escape `.` and `*`.

Endpoints may have certain functions disabled for some properties due to technical or logical limitations. For example, mandatory fields will not support `isNull` and `isNotNull`. Each endpoint supporting filtering will have a detailed documentation of filterable properties, their types and allowed functions.

## [](https://192.168.125.254/unifi-api/network#tag/Hotspot-Vouchers)Hotspot Vouchers

## [](https://192.168.125.254/unifi-api/network#tag/Hotspot-Vouchers/operation/getVouchers)List Vouchers

List Hotspot vouchers (paginated)

Filterable properties (click to expand)

|         Name         |   Type    |         Allowed functions          |
|----------------------|-----------|------------------------------------|
|          `id`          |   `UUID`    |           `eq` `ne` `in` `notIn`           |
|      `createdAt`       | `TIMESTAMP` |         `eq` `ne` `gt` `ge` `lt` `le`          |
|         `name`         |  `STRING`   |        `eq` `ne` `in` `notIn` `like`         |
|         `code`         |  `STRING`   |           `eq` `ne` `in` `notIn`           |
| `authorizedGuestLimit` |  `NUMBER`   | `isNull` `isNotNull` `eq` `ne` `gt` `ge` `lt` `le` |
| `authorizedGuestCount` |  `NUMBER`   |         `eq` `ne` `gt` `ge` `lt` `le`          |
|     `activatedAt`      | `TIMESTAMP` |         `eq` `ne` `gt` `ge` `lt` `le`          |
|      `expiresAt`       | `TIMESTAMP` |         `eq` `ne` `gt` `ge` `lt` `le`          |
|       `expired`        |  `BOOLEAN`  |               `eq` `ne`                |
|   `timeLimitMinutes`   |  `NUMBER`   |         `eq` `ne` `gt` `ge` `lt` `le`          |
| `dataUsageLimitMBytes` |  `NUMBER`   | `isNull` `isNotNull` `eq` `ne` `gt` `ge` `lt` `le` |
|   `rxRateLimitKbps`    |  `NUMBER`   | `isNull` `isNotNull` `eq` `ne` `gt` `ge` `lt` `le` |
|   `txRateLimitKbps`    |  `NUMBER`   | `isNull` `isNotNull` `eq` `ne` `gt` `ge` `lt` `le` |

##### path Parameters

| siteId

required |  |
|------------------|-----|

##### query Parameters

| offset | number <int32> \>= 0

Default: 0 |
|--------|----------------------------------------------|
| limit  | number <int32> \[ 0 .. 1000 \]

Default: 100 |
| filter |                                              |

### Responses

## [](https://192.168.125.254/unifi-api/network#tag/Hotspot-Vouchers/operation/createVouchers)Generate Vouchers

Generate one or more Hotspot vouchers

##### path Parameters

| siteId

required |  |
|------------------|-----|

##### Request Body schema: application/json

required

|           count            | integer <int32> \[ 1 .. 1000 \]

Default: "1"

Number of vouchers to generate |
|----------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| name

required | string

Voucher note, duplicated across all generated vouchers |
|    authorizedGuestLimit    | integer <int64> \>= 1

(Optional) limit for how many different guests can use the same voucher to authorize network access |
| timeLimitMinutes

required | integer <int64> \[ 1 .. 1000000 \]

How long (in minutes) the voucher will provide access to the network since authorization of the first guest. Subsequently connected guests, if allowed, will share the same expiration time. |
|    dataUsageLimitMBytes    | integer <int64> \[ 1 .. 1048576 \]

(Optional) data usage limit in megabytes |
|      rxRateLimitKbps       | integer <int64> \[ 2 .. 100000 \]

(Optional) download rate limit in kilobits per second |
|      txRateLimitKbps       | integer <int64> \[ 2 .. 100000 \]

(Optional) upload rate limit in kilobits per second |

### Responses

### Request samples

-   Payload

Content type

application/json

`{`

-   `"count": "1",`
    
-   `"name": "string",`
    
-   `"authorizedGuestLimit": 1,`
    
-   `"timeLimitMinutes": 1,`
    
-   `"dataUsageLimitMBytes": 1,`
    
-   `"rxRateLimitKbps": 2,`
    
-   `"txRateLimitKbps": 2`
    

`}`

## [](https://192.168.125.254/unifi-api/network#tag/Hotspot-Vouchers/operation/deleteVouchers)Delete Vouchers

Delete Hotspot vouchers by filter

Filterable properties (click to expand)

|         Name         |   Type    |         Allowed functions          |
|----------------------|-----------|------------------------------------|
|          `id`          |   `UUID`    |           `eq` `ne` `in` `notIn`           |
|      `createdAt`       | `TIMESTAMP` |         `eq` `ne` `gt` `ge` `lt` `le`          |
|         `name`         |  `STRING`   |        `eq` `ne` `in` `notIn` `like`         |
|         `code`         |  `STRING`   |           `eq` `ne` `in` `notIn`           |
| `authorizedGuestLimit` |  `NUMBER`   | `isNull` `isNotNull` `eq` `ne` `gt` `ge` `lt` `le` |
| `authorizedGuestCount` |  `NUMBER`   |         `eq` `ne` `gt` `ge` `lt` `le`          |
|     `activatedAt`      | `TIMESTAMP` |         `eq` `ne` `gt` `ge` `lt` `le`          |
|      `expiresAt`       | `TIMESTAMP` |         `eq` `ne` `gt` `ge` `lt` `le`          |
|       `expired`        |  `BOOLEAN`  |               `eq` `ne`                |
|   `timeLimitMinutes`   |  `NUMBER`   |         `eq` `ne` `gt` `ge` `lt` `le`          |
| `dataUsageLimitMBytes` |  `NUMBER`   | `isNull` `isNotNull` `eq` `ne` `gt` `ge` `lt` `le` |
|   `rxRateLimitKbps`    |  `NUMBER`   | `isNull` `isNotNull` `eq` `ne` `gt` `ge` `lt` `le` |
|   `txRateLimitKbps`    |  `NUMBER`   | `isNull` `isNotNull` `eq` `ne` `gt` `ge` `lt` `le` |

##### path Parameters

| siteId

required |  |
|------------------|-----|

##### query Parameters

### Responses

## [](https://192.168.125.254/unifi-api/network#tag/Hotspot-Vouchers/operation/getVoucher)Get Voucher Details

Get details of a specific Hotspot voucher

##### path Parameters

| voucherId

required |  |
|---------------------|-----|
| siteId

required |  |

### Responses

## [](https://192.168.125.254/unifi-api/network#tag/Hotspot-Vouchers/operation/deleteVoucher)Delete Voucher

Delete a specific Hotspot voucher

##### path Parameters

| voucherId

required |  |
|---------------------|-----|
| siteId

required |  |

### Responses

## [](https://192.168.125.254/unifi-api/network#tag/Devices)Devices

## [](https://192.168.125.254/unifi-api/network#tag/Devices/operation/executePortAction)Execute Port Action

Execute an action on a specific port. Request body should contain action name and input arguments, if apply.

##### path Parameters

| portIdx

required |  |
|--------------------|-----|
| siteId

required |  |
| deviceId

required |  |

##### Request Body schema: application/json

required

| action

required |  |
|------------------|-----|

### Responses

## [](https://192.168.125.254/unifi-api/network#tag/Devices/operation/executeDeviceAction)Execute Device Action

Execute an action on a specific adopted device. Request body should contain action name and input arguments, if apply.

##### path Parameters

| siteId

required |  |
|--------------------|-----|
| deviceId

required |  |

##### Request Body schema: application/json

required

| action

required |  |
|------------------|-----|

### Responses

## [](https://192.168.125.254/unifi-api/network#tag/Devices/operation/getDeviceOverviewPage)List Devices

List adopted devices of a site (paginated). Response contains basic information about site's adopted devices.

##### path Parameters

| siteId

required |  |
|------------------|-----|

##### query Parameters

| offset | number <int32> \>= 0

Default: 0 |
|--------|--------------------------------------------|
| limit  | number <int32> \[ 0 .. 200 \]

Default: 25 |

### Responses

## [](https://192.168.125.254/unifi-api/network#tag/Devices/operation/getDeviceDetails)Get Device Details

Get detailed information about a specific adopted device. Response includes more information about a single device, as well as more detailed information about device features, such as switch ports and/or access point radios

##### path Parameters

| siteId

required |  |
|--------------------|-----|
| deviceId

required |  |

### Responses

## [](https://192.168.125.254/unifi-api/network#tag/Devices/operation/getDeviceLatestStatistics)Get Latest Device Statistics

Get latest (live) statistics of a specific adopted device. Response contains latest readings from a single device, such as CPU and memory utilization, uptime, uplink tx/rx rates etc

##### path Parameters

| siteId

required |  |
|--------------------|-----|
| deviceId

required |  |

### Responses

## [](https://192.168.125.254/unifi-api/network#tag/Clients)Clients

## [](https://192.168.125.254/unifi-api/network#tag/Clients/operation/executeConnectedClientAction)Execute Client Action

Execute an action on a specific connected client. Request body should contain action name and input arguments, if apply.

##### path Parameters

| clientId

required |  |
|--------------------|-----|
| siteId

required |  |

##### Request Body schema: application/json

required

| action

required | string

AUTHORIZE\_GUEST\_ACCESS |
|----------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
|   timeLimitMinutes   | integer <int64> \[ 1 .. 1000000 \]

(Optional) how long (in minutes) the guest will be authorized to access the network. If not specified, the default limit is used from the site settings |
| dataUsageLimitMBytes | integer <int64> \[ 1 .. 1048576 \]

(Optional) data usage limit in megabytes |
|   rxRateLimitKbps    | integer <int64> \[ 2 .. 100000 \]

(Optional) download rate limit in kilobits per second |
|   txRateLimitKbps    | integer <int64> \[ 2 .. 100000 \]

(Optional) upload rate limit in kilobits per second |

### Responses

### Request samples

-   Payload

Content type

application/json

Example

AUTHORIZE\_GUEST\_ACCESS

`{`

-   `"action": "AUTHORIZE_GUEST_ACCESS",`
    
-   `"timeLimitMinutes": 1,`
    
-   `"dataUsageLimitMBytes": 1,`
    
-   `"rxRateLimitKbps": 2,`
    
-   `"txRateLimitKbps": 2`
    

`}`

## [](https://192.168.125.254/unifi-api/network#tag/Clients/operation/getConnectedClientOverviewPage)List Connected Clients

List connected clients of a site (paginated). Clients are either physical devices (computers, smartphones, connected by wire or wirelessly), or active VPN connections.

Filterable properties (click to expand)

|       Name        |   Type    |         Allowed functions          |
|-------------------|-----------|------------------------------------|
|        `id`         |   `UUID`    |           `eq` `ne` `in` `notIn`           |
|       `type`        |  `STRING`   |           `eq` `ne` `in` `notIn`           |
|    `macAddress`     |  `STRING`   |  `isNull` `isNotNull` `eq` `ne` `in` `notIn`   |
|     `ipAddress`     |  `STRING`   |  `isNull` `isNotNull` `eq` `ne` `in` `notIn`   |
|    `connectedAt`    | `TIMESTAMP` | `isNull` `isNotNull` `eq` `ne` `gt` `ge` `lt` `le` |
|    `access.type`    |  `STRING`   |           `eq` `ne` `in` `notIn`           |
| `access.authorized` |  `BOOLEAN`  |       `isNull` `isNotNull` `eq` `ne`       |

##### path Parameters

| siteId

required |  |
|------------------|-----|

##### query Parameters

| offset | number <int32> \>= 0

Default: 0 |
|--------|--------------------------------------------|
| limit  | number <int32> \[ 0 .. 200 \]

Default: 25 |
| filter |                                            |

### Responses

## [](https://192.168.125.254/unifi-api/network#tag/Clients/operation/getConnectedClientDetails)Get Connected Client Details

##### path Parameters

| clientId

required |  |
|--------------------|-----|
| siteId

required |  |

### Responses

## [](https://192.168.125.254/unifi-api/network#tag/Sites)Sites

## [](https://192.168.125.254/unifi-api/network#tag/Sites/operation/getSiteOverviewPage)List Local Sites

List local sites managed by this Network application (paginated). Setups using Multi-Site option enabled will return all created sites while if option is disabled it will return just the default site.

Filterable properties (click to expand)

|       Name        |  Type  | Allowed functions |
|-------------------|--------|-------------------|
|        `id`         |  `UUID`  |  `eq` `ne` `in` `notIn`   |
| `internalReference` | `STRING` |  `eq` `ne` `in` `notIn`   |
|       `name`        | `STRING` |  `eq` `ne` `in` `notIn`   |

##### query Parameters

| offset | number <int32> \>= 0

Default: 0 |
|--------|--------------------------------------------|
| limit  | number <int32> \[ 0 .. 200 \]

Default: 25 |
| filter |                                            |

### Responses

## [](https://192.168.125.254/unifi-api/network#tag/About-application)About application

## [](https://192.168.125.254/unifi-api/network#tag/About-application/operation/getInfo)Get Application Info

Get generic information about the Network application

### Responses