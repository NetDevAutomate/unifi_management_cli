---
title: "Dream Machine Pro Max - Control Plane"
source: "https://unifi.ui.com/consoles/0CEA1419ADE300000000085C11E90000000008CDD12E0000000066F7D239:1651413211/unifi-api/protect"
author:
published:
created: 2026-01-13
description:
tags:
  - "clippings"
---
## UniFi Protect API (6.2.83)

Download OpenAPI specification:[Download](https://unifi.ui.com/af1846d2-0258-4e0f-a4a5-9991aa565e67)

## Information about application

## Viewer information & management

### Response samples

- 200

Content type

application/json

`{ - "id": "66d025b301ebc903e80003ea", - "modelKey": "viewer", - "state": "CONNECTED", - "name": "string", - "mac": "string", - "liveview": "66d025b301ebc903e80003ea", - "streamLimit": 0 }`

## Patch viewer settings

Patch the settings for a specific viewer

##### path Parameters

| id  required | string (viewerId)  Examples: 66d025b301ebc903e80003ea 672094f900e26303e800062a  The primary key of viewer |
| --- | --- |

##### Request Body schema: application/jsonrequired

| name | string (name)  The name of the model |
| --- | --- |
|  | liveviewId (string) or null |

### Request samples

- Payload

Content type

application/json

`{ - "name": "string", - "liveview": "66d025b301ebc903e80003ea" }`

### Response samples

- 200

Content type

application/json

`{ - "id": "66d025b301ebc903e80003ea", - "modelKey": "viewer", - "state": "CONNECTED", - "name": "string", - "mac": "string", - "liveview": "66d025b301ebc903e80003ea", - "streamLimit": 0 }`

### Response samples

- 200

Content type

application/json

`[ - { 	- "id": "66d025b301ebc903e80003ea", 	- "modelKey": "viewer", 	- "state": "CONNECTED", 	- "name": "string", 	- "mac": "string", 	- "liveview": "66d025b301ebc903e80003ea", 	- "streamLimit": 0 	} ]`

## Live view management

### Response samples

- 200

Content type

application/json

`{ - "id": "66d025b301ebc903e80003ea", - "modelKey": "liveview", - "name": "string", - "isDefault": true, - "isGlobal": true, - "owner": "66d025b301ebc903e80003ea", - "layout": 1, - "slots": [ 	- { 		- "cameras": [ 			- "66d025b301ebc903e80003ea" 			], 		- "cycleMode": "motion", 		- "cycleInterval": 0 		} 	] }`

## Patch live view configuration

Patch the configuration about a specific live view

##### path Parameters

| id  required | string (liveviewId)  Examples: 66d025b301ebc903e80003ea 672094f900e26303e800062a  The primary key of liveview |
| --- | --- |

##### Request Body schema: application/jsonrequired

| id  required | string (liveviewId)  The primary key of liveview |
| --- | --- |
| modelKey  required | string (liveviewModelKey)  The model key of the liveview  Value:"liveview" |
| name  required | string  The name of this live view. |
| isDefault  required | boolean  Whether this live view is the default one for all viewers. |
| isGlobal  required | boolean  Whether this live view is global and available system-wide to all users |
| owner  required | string (userId)  The primary key of user |
| layout  required | number \[ 1.. 26 \]  The number of slots this live view contains. Which as a consequence also affects the layout of the live view. |
| required | Array of objects  List of cameras visible in each given slot. And cycling settings for each slot if it has multiple cameras listed. |

### Request samples

- Payload

Content type

application/json

`{ - "id": "66d025b301ebc903e80003ea", - "modelKey": "liveview", - "name": "string", - "isDefault": true, - "isGlobal": true, - "owner": "66d025b301ebc903e80003ea", - "layout": 1, - "slots": [ 	- { 		- "cameras": [ 			- "66d025b301ebc903e80003ea" 			], 		- "cycleMode": "motion", 		- "cycleInterval": 0 		} 	] }`

### Response samples

- 200

Content type

application/json

`{ - "id": "66d025b301ebc903e80003ea", - "modelKey": "liveview", - "name": "string", - "isDefault": true, - "isGlobal": true, - "owner": "66d025b301ebc903e80003ea", - "layout": 1, - "slots": [ 	- { 		- "cameras": [ 			- "66d025b301ebc903e80003ea" 			], 		- "cycleMode": "motion", 		- "cycleInterval": 0 		} 	] }`

### Response samples

- 200

Content type

application/json

`[ - { 	- "id": "66d025b301ebc903e80003ea", 	- "modelKey": "liveview", 	- "name": "string", 	- "isDefault": true, 	- "isGlobal": true, 	- "owner": "66d025b301ebc903e80003ea", 	- "layout": 1, 	- "slots": [ 		- { 			- "cameras": [ 				- "66d025b301ebc903e80003ea" 				], 			- "cycleMode": "motion", 			- "cycleInterval": 0 			} 		] 	} ]`

## Create live view

Create a new live view

##### Request Body schema: application/jsonrequired

| id  required | string (liveviewId)  The primary key of liveview |
| --- | --- |
| modelKey  required | string (liveviewModelKey)  The model key of the liveview  Value:"liveview" |
| name  required | string  The name of this live view. |
| isDefault  required | boolean  Whether this live view is the default one for all viewers. |
| isGlobal  required | boolean  Whether this live view is global and available system-wide to all users |
| owner  required | string (userId)  The primary key of user |
| layout  required | number \[ 1.. 26 \]  The number of slots this live view contains. Which as a consequence also affects the layout of the live view. |
| required | Array of objects  List of cameras visible in each given slot. And cycling settings for each slot if it has multiple cameras listed. |

### Request samples

- Payload

Content type

application/json

`{ - "id": "66d025b301ebc903e80003ea", - "modelKey": "liveview", - "name": "string", - "isDefault": true, - "isGlobal": true, - "owner": "66d025b301ebc903e80003ea", - "layout": 1, - "slots": [ 	- { 		- "cameras": [ 			- "66d025b301ebc903e80003ea" 			], 		- "cycleMode": "motion", 		- "cycleInterval": 0 		} 	] }`

### Response samples

- 200

Content type

application/json

`{ - "id": "66d025b301ebc903e80003ea", - "modelKey": "liveview", - "name": "string", - "isDefault": true, - "isGlobal": true, - "owner": "66d025b301ebc903e80003ea", - "layout": 1, - "slots": [ 	- { 		- "cameras": [ 			- "66d025b301ebc903e80003ea" 			], 		- "cycleMode": "motion", 		- "cycleInterval": 0 		} 	] }`

## WebSocket updates

## Camera PTZ control & management

## Start a camera PTZ patrol

Start a camera PTZ patrol

##### path Parameters

| id  required | string (cameraId)  Examples: 66d025b301ebc903e80003ea 672094f900e26303e800062a  The primary key of camera |
| --- | --- |
| slot  required | string (activePatrolSlotString)  Examples: 0 1 2 3 4  The slot number (0-4) of the patrol that is currently running, or null if no patrol is running |

### Response samples

Content type

application/json

`{ - "error": "Unexpected API error occurred", - "name": "API_ERROR", - "cause": { 	- "error": "Unexpected functionality error", 	- "name": "UNKNOWN_ERROR" 	} }`

## Stop active camera PTZ patrol

Stop active camera PTZ patrol

##### path Parameters

| id  required | string (cameraId)  Examples: 66d025b301ebc903e80003ea 672094f900e26303e800062a  The primary key of camera |
| --- | --- |

### Response samples

Content type

application/json

`{ - "error": "Unexpected API error occurred", - "name": "API_ERROR", - "cause": { 	- "error": "Unexpected functionality error", 	- "name": "UNKNOWN_ERROR" 	} }`

## Move PTZ camera to preset

Adjust the PTZ camera position to a specified preset

##### path Parameters

| id  required | string (cameraId)  Examples: 66d025b301ebc903e80003ea 672094f900e26303e800062a  The primary key of camera |
| --- | --- |
| slot  required | string  Examples: \-1 0 2 8 9  The slot number (0-4) of the preset to move the camera to |

### Response samples

Content type

application/json

`{ - "error": "Unexpected API error occurred", - "name": "API_ERROR", - "cause": { 	- "error": "Unexpected functionality error", 	- "name": "UNKNOWN_ERROR" 	} }`

## Alarm manager integration

## Send a webhook to the alarm manager

Send a webhook to the alarm manager to trigger configured alarms

##### path Parameters

| id  required | string (alarmTriggerId)  Examples: AnyRandomString  User defined string used to trigger only specific alarms. Alarm should be configured with the same ID to be triggered. |
| --- | --- |

### Response samples

Content type

application/json

`{ - "error": "'id' is required", - "name": "BAD_REQUEST", - "cause": { 	- "error": "Unexpected functionality error", 	- "name": "UNKNOWN_ERROR" 	} }`

## Light information & management

### Response samples

- 200

Content type

application/json

`{ - "id": "66d025b301ebc903e80003ea", - "modelKey": "light", - "state": "CONNECTED", - "name": "string", - "mac": "string", - "lightModeSettings": { 	- "mode": "always", 	- "enableAt": "fulltime" 	}, - "lightDeviceSettings": { 	- "isIndicatorEnabled": true, 	- "pirDuration": 0, 	- "pirSensitivity": 100, 	- "ledLevel": 1 	}, - "isDark": true, - "isLightOn": true, - "isLightForceEnabled": true, - "lastMotion": 0, - "isPirMotionDetected": true, - "camera": "66d025b301ebc903e80003ea" }`

## Patch light settings

Patch the settings for a specific light

##### path Parameters

| id  required | string (lightId)  Examples: 66d025b301ebc903e80003ea 672094f900e26303e800062a  The primary key of light |
| --- | --- |

##### Request Body schema: application/jsonrequired

| name | string (name)  The name of the model |
| --- | --- |
| isLightForceEnabled | boolean (isLightForceEnabled)  Whether the light has its main LED currently force-enabled. |
|  | object (lightModeSettings)  Settings for when and how your light gets activated |
|  | object (lightDeviceSettings)  Hardware settings for light device. |

### Request samples

- Payload

Content type

application/json

`{ - "name": "string", - "isLightForceEnabled": true, - "lightModeSettings": { 	- "mode": "always", 	- "enableAt": "fulltime" 	}, - "lightDeviceSettings": { 	- "isIndicatorEnabled": true, 	- "pirDuration": 0, 	- "pirSensitivity": 100, 	- "ledLevel": 1 	} }`

### Response samples

- 200

Content type

application/json

`{ - "id": "66d025b301ebc903e80003ea", - "modelKey": "light", - "state": "CONNECTED", - "name": "string", - "mac": "string", - "lightModeSettings": { 	- "mode": "always", 	- "enableAt": "fulltime" 	}, - "lightDeviceSettings": { 	- "isIndicatorEnabled": true, 	- "pirDuration": 0, 	- "pirSensitivity": 100, 	- "ledLevel": 1 	}, - "isDark": true, - "isLightOn": true, - "isLightForceEnabled": true, - "lastMotion": 0, - "isPirMotionDetected": true, - "camera": "66d025b301ebc903e80003ea" }`

### Response samples

- 200

Content type

application/json

`[ - { 	- "id": "66d025b301ebc903e80003ea", 	- "modelKey": "light", 	- "state": "CONNECTED", 	- "name": "string", 	- "mac": "string", 	- "lightModeSettings": { 		- "mode": "always", 		- "enableAt": "fulltime" 		}, 	- "lightDeviceSettings": { 		- "isIndicatorEnabled": true, 		- "pirDuration": 0, 		- "pirSensitivity": 100, 		- "ledLevel": 1 		}, 	- "isDark": true, 	- "isLightOn": true, 	- "isLightForceEnabled": true, 	- "lastMotion": 0, 	- "isPirMotionDetected": true, 	- "camera": "66d025b301ebc903e80003ea" 	} ]`

## Camera information & management

### Response samples

- 200

Content type

application/json

`{ - "id": "66d025b301ebc903e80003ea", - "modelKey": "camera", - "state": "CONNECTED", - "name": "string", - "mac": "string", - "isMicEnabled": true, - "osdSettings": { 	- "isNameEnabled": true, 	- "isDateEnabled": true, 	- "isLogoEnabled": true, 	- "isDebugEnabled": true, 	- "overlayLocation": "topLeft" 	}, - "ledSettings": { 	- "isEnabled": true, 	- "welcomeLed": true, 	- "floodLed": true 	}, - "lcdMessage": { 	- "type": "LEAVE_PACKAGE_AT_DOOR", 	- "resetAt": 0, 	- "text": "string" 	}, - "micVolume": 100, - "activePatrolSlot": 0, - "videoMode": "default", - "hdrType": "auto", - "featureFlags": { 	- "supportFullHdSnapshot": true, 	- "hasHdr": true, 	- "smartDetectTypes": [ 		- "person" 		], 	- "smartDetectAudioTypes": [ 		- "alrmSmoke" 		], 	- "videoModes": [ 		- "default" 		], 	- "hasMic": true, 	- "hasLedStatus": true, 	- "hasSpeaker": true 	}, - "smartDetectSettings": { 	- "objectTypes": [ 		- "person" 		], 	- "audioTypes": [ 		- "alrmSmoke" 		] 	} }`

## Patch camera settings

Patch the settings for a specific camera

##### path Parameters

| id  required | string (cameraId)  Examples: 66d025b301ebc903e80003ea 672094f900e26303e800062a  The primary key of camera |
| --- | --- |

##### Request Body schema: application/jsonrequired

| name | string  The name of the camera |
| --- | --- |
|  | object (osdSettings)  On Screen Display settings. |
|  | object (ledSettings)  LED settings. |
|  | lcdMessage (object) or lcdMessage (object) or lcdMessage (object) or lcdMessage (object) (lcdMessage) |
| micVolume | number (micVolume) \[ 0.. 100 \]  Mic volume: a number from 0-100. |
| videoMode | string (videoMode)  Enum:"default" "highFps" "sport" "slowShutter" "lprReflex" "lprNoneReflex"  Current video mode of the camera |
| hdrType | string (videoMode)  Enum:"auto" "on" "off"  High Dynamic Range (HDR) mode setting. |
|  | object (smartDetectSettings)  Smart detection settings for the camera. |

### Request samples

- Payload

Content type

application/json

`{ - "name": "string", - "osdSettings": { 	- "isNameEnabled": true, 	- "isDateEnabled": true, 	- "isLogoEnabled": true, 	- "isDebugEnabled": true, 	- "overlayLocation": "topLeft" 	}, - "ledSettings": { 	- "isEnabled": true, 	- "welcomeLed": true, 	- "floodLed": true 	}, - "lcdMessage": { 	- "type": "DO_NOT_DISTURB", 	- "resetAt": 0 	}, - "micVolume": 100, - "videoMode": "default", - "hdrType": "auto", - "smartDetectSettings": { 	- "objectTypes": [ 		- "person" 		], 	- "audioTypes": [ 		- "alrmSmoke" 		] 	} }`

### Response samples

- 200

Content type

application/json

`{ - "id": "66d025b301ebc903e80003ea", - "modelKey": "camera", - "state": "CONNECTED", - "name": "string", - "mac": "string", - "isMicEnabled": true, - "osdSettings": { 	- "isNameEnabled": true, 	- "isDateEnabled": true, 	- "isLogoEnabled": true, 	- "isDebugEnabled": true, 	- "overlayLocation": "topLeft" 	}, - "ledSettings": { 	- "isEnabled": true, 	- "welcomeLed": true, 	- "floodLed": true 	}, - "lcdMessage": { 	- "type": "LEAVE_PACKAGE_AT_DOOR", 	- "resetAt": 0, 	- "text": "string" 	}, - "micVolume": 100, - "activePatrolSlot": 0, - "videoMode": "default", - "hdrType": "auto", - "featureFlags": { 	- "supportFullHdSnapshot": true, 	- "hasHdr": true, 	- "smartDetectTypes": [ 		- "person" 		], 	- "smartDetectAudioTypes": [ 		- "alrmSmoke" 		], 	- "videoModes": [ 		- "default" 		], 	- "hasMic": true, 	- "hasLedStatus": true, 	- "hasSpeaker": true 	}, - "smartDetectSettings": { 	- "objectTypes": [ 		- "person" 		], 	- "audioTypes": [ 		- "alrmSmoke" 		] 	} }`

### Response samples

- 200

Content type

application/json

`[ - { 	- "id": "66d025b301ebc903e80003ea", 	- "modelKey": "camera", 	- "state": "CONNECTED", 	- "name": "string", 	- "mac": "string", 	- "isMicEnabled": true, 	- "osdSettings": { 		- "isNameEnabled": true, 		- "isDateEnabled": true, 		- "isLogoEnabled": true, 		- "isDebugEnabled": true, 		- "overlayLocation": "topLeft" 		}, 	- "ledSettings": { 		- "isEnabled": true, 		- "welcomeLed": true, 		- "floodLed": true 		}, 	- "lcdMessage": { 		- "type": "LEAVE_PACKAGE_AT_DOOR", 		- "resetAt": 0, 		- "text": "string" 		}, 	- "micVolume": 100, 	- "activePatrolSlot": 0, 	- "videoMode": "default", 	- "hdrType": "auto", 	- "featureFlags": { 		- "supportFullHdSnapshot": true, 		- "hasHdr": true, 		- "smartDetectTypes": [ 			- "person" 			], 		- "smartDetectAudioTypes": [ 			- "alrmSmoke" 			], 		- "videoModes": [ 			- "default" 			], 		- "hasMic": true, 		- "hasLedStatus": true, 		- "hasSpeaker": true 		}, 	- "smartDetectSettings": { 		- "objectTypes": [ 			- "person" 			], 		- "audioTypes": [ 			- "alrmSmoke" 			] 		} 	} ]`

## Create RTSPS streams for camera

Returns RTSPS stream URLs for specified quality levels

##### path Parameters

| id  required | string (cameraId)  Examples: 66d025b301ebc903e80003ea 672094f900e26303e800062a  The primary key of camera |
| --- | --- |

##### Request Body schema: application/jsonrequired

| qualities  required | Array of strings (createdQualities) non-empty  ItemsEnum:"high" "medium" "low" "package"  Array of quality levels of RTSPS streams |
| --- | --- |

### Request samples

- Payload

Content type

application/json

`{ - "qualities": [ 	- "high", 	- "medium" 	] }`

### Response samples

- 200

Content type

application/json

`{ - "high": "rtsps://192.168.1.1:7441/5nPr7RCmueGTKMP7?enableSrtp", - "medium": "rtsps://192.168.1.1:7441/AbUgnDb5IqIEMidk?enableSrtp" }`

## Delete camera RTSPS stream

Remove the RTSPS stream for a specified camera

##### path Parameters

| id  required | string (cameraId)  Examples: 66d025b301ebc903e80003ea 672094f900e26303e800062a  The primary key of camera |
| --- | --- |

##### query Parameters

| required | Array of removedQualities (strings) or channelQuality (string) (removedQualities)  Examples: qualities=high&qualities=medium  The array of quality levels for the RTSPS streams to be removed. |
| --- | --- |

### Response samples

Content type

application/json

`{ - "error": "Unexpected API error occurred", - "name": "API_ERROR", - "cause": { 	- "error": "Unexpected functionality error", 	- "name": "UNKNOWN_ERROR" 	} }`

### Response samples

- 200

Content type

application/json

`{ - "high": "rtsps://192.168.1.1:7441/5nPr7RCmueGTKMP7?enableSrtp", - "medium": "rtsps://192.168.1.1:7441/AbUgnDb5IqIEMidk?enableSrtp", - "low": null, - "package": null }`

## Get camera snapshot

Get a snapshot image from a specific camera

##### path Parameters

| id  required | string (cameraId)  Examples: 66d025b301ebc903e80003ea 672094f900e26303e800062a  The primary key of camera |
| --- | --- |

##### query Parameters

| highQuality | string (forceHighQuality)  Default:"false"  Enum:"true" "false"  Whether to force 1080P or higher resolution snapshot |
| --- | --- |

### Response samples

Content type

application/json

`{ - "error": "Unexpected API error occurred", - "name": "API_ERROR", - "cause": { 	- "error": "Unexpected functionality error", 	- "name": "UNKNOWN_ERROR" 	} }`

## Permanently disable camera microphone

Disable the microphone for a specific camera. This action cannot be undone unless the camera is reset.

##### path Parameters

| id  required | string (cameraId)  Examples: 66d025b301ebc903e80003ea 672094f900e26303e800062a  The primary key of camera |
| --- | --- |

### Response samples

- 200

Content type

application/json

`{ - "id": "66d025b301ebc903e80003ea", - "modelKey": "camera", - "state": "CONNECTED", - "name": "string", - "mac": "string", - "isMicEnabled": true, - "osdSettings": { 	- "isNameEnabled": true, 	- "isDateEnabled": true, 	- "isLogoEnabled": true, 	- "isDebugEnabled": true, 	- "overlayLocation": "topLeft" 	}, - "ledSettings": { 	- "isEnabled": true, 	- "welcomeLed": true, 	- "floodLed": true 	}, - "lcdMessage": { 	- "type": "LEAVE_PACKAGE_AT_DOOR", 	- "resetAt": 0, 	- "text": "string" 	}, - "micVolume": 100, - "activePatrolSlot": 0, - "videoMode": "default", - "hdrType": "auto", - "featureFlags": { 	- "supportFullHdSnapshot": true, 	- "hasHdr": true, 	- "smartDetectTypes": [ 		- "person" 		], 	- "smartDetectAudioTypes": [ 		- "alrmSmoke" 		], 	- "videoModes": [ 		- "default" 		], 	- "hasMic": true, 	- "hasLedStatus": true, 	- "hasSpeaker": true 	}, - "smartDetectSettings": { 	- "objectTypes": [ 		- "person" 		], 	- "audioTypes": [ 		- "alrmSmoke" 		] 	} }`

## Create talkback session for camera

Returns the talkback stream URL and audio configuration for a specific camera

##### path Parameters

| id  required | string (cameraId)  Examples: 66d025b301ebc903e80003ea 672094f900e26303e800062a  The primary key of camera |
| --- | --- |

### Response samples

- 200

Content type

application/json

`{ - "url": "rtp://192.168.1.123:7004", - "codec": "opus", - "samplingRate": 24000, - "bitsPerSample": 16 }`

## Sensor information & management

### Response samples

- 200

Content type

application/json

`{ - "id": "66d025b301ebc903e80003ea", - "modelKey": "sensor", - "state": "CONNECTED", - "name": "string", - "mac": "string", - "mountType": "garage", - "batteryStatus": { 	- "percentage": 0, 	- "isLow": true 	}, - "stats": { 	- "light": { 		- "value": 0, 		- "status": "high" 		}, 	- "humidity": { 		- "value": 0, 		- "status": "high" 		}, 	- "temperature": { 		- "value": 0, 		- "status": "high" 		} 	}, - "lightSettings": { 	- "isEnabled": true, 	- "margin": 0, 	- "lowThreshold": 1, 	- "highThreshold": 0 	}, - "humiditySettings": { 	- "isEnabled": true, 	- "margin": 0, 	- "lowThreshold": 1, 	- "highThreshold": 0 	}, - "temperatureSettings": { 	- "isEnabled": true, 	- "margin": 0, 	- "lowThreshold": -39, 	- "highThreshold": 0 	}, - "isOpened": true, - "openStatusChangedAt": 0, - "isMotionDetected": true, - "motionDetectedAt": 0, - "motionSettings": { 	- "isEnabled": true, 	- "sensitivity": 100 	}, - "alarmTriggeredAt": 0, - "alarmSettings": { 	- "isEnabled": true 	}, - "leakDetectedAt": 0, - "externalLeakDetectedAt": 0, - "leakSettings": { 	- "isInternalEnabled": true, 	- "isExternalEnabled": true 	}, - "tamperingDetectedAt": 0 }`

## Patch sensor settings

Patch the settings for a specific sensor

##### path Parameters

| id  required | string (sensorId)  Examples: 66d025b301ebc903e80003ea 672094f900e26303e800062a  The primary key of sensor |
| --- | --- |

##### Request Body schema: application/jsonrequired

| name | string (name)  The name of the model |
| --- | --- |
|  | object (lightSettings)  Ambient light sensor settings. |
|  | object (humiditySettings)  Relative humidity sensor settings. |
|  | object (temperatureSettings)  Temperature sensor settings. |
|  | object (motionSettings)  Motion sensor settings. |
|  | object (alarmSettings)  Smoke and carbon monoxide alarm sensor settings. |

### Request samples

- Payload

Content type

application/json

`{ - "name": "string", - "lightSettings": { 	- "isEnabled": true, 	- "margin": 0, 	- "lowThreshold": 1, 	- "highThreshold": 0 	}, - "humiditySettings": { 	- "isEnabled": true, 	- "margin": 0, 	- "lowThreshold": 1, 	- "highThreshold": 0 	}, - "temperatureSettings": { 	- "isEnabled": true, 	- "margin": 0, 	- "lowThreshold": -39, 	- "highThreshold": 0 	}, - "motionSettings": { 	- "isEnabled": true, 	- "sensitivity": 100 	}, - "alarmSettings": { 	- "isEnabled": true 	} }`

### Response samples

- 200

Content type

application/json

`{ - "id": "66d025b301ebc903e80003ea", - "modelKey": "sensor", - "state": "CONNECTED", - "name": "string", - "mac": "string", - "mountType": "garage", - "batteryStatus": { 	- "percentage": 0, 	- "isLow": true 	}, - "stats": { 	- "light": { 		- "value": 0, 		- "status": "high" 		}, 	- "humidity": { 		- "value": 0, 		- "status": "high" 		}, 	- "temperature": { 		- "value": 0, 		- "status": "high" 		} 	}, - "lightSettings": { 	- "isEnabled": true, 	- "margin": 0, 	- "lowThreshold": 1, 	- "highThreshold": 0 	}, - "humiditySettings": { 	- "isEnabled": true, 	- "margin": 0, 	- "lowThreshold": 1, 	- "highThreshold": 0 	}, - "temperatureSettings": { 	- "isEnabled": true, 	- "margin": 0, 	- "lowThreshold": -39, 	- "highThreshold": 0 	}, - "isOpened": true, - "openStatusChangedAt": 0, - "isMotionDetected": true, - "motionDetectedAt": 0, - "motionSettings": { 	- "isEnabled": true, 	- "sensitivity": 100 	}, - "alarmTriggeredAt": 0, - "alarmSettings": { 	- "isEnabled": true 	}, - "leakDetectedAt": 0, - "externalLeakDetectedAt": 0, - "leakSettings": { 	- "isInternalEnabled": true, 	- "isExternalEnabled": true 	}, - "tamperingDetectedAt": 0 }`

### Response samples

- 200

Content type

application/json

`[ - { 	- "id": "66d025b301ebc903e80003ea", 	- "modelKey": "sensor", 	- "state": "CONNECTED", 	- "name": "string", 	- "mac": "string", 	- "mountType": "garage", 	- "batteryStatus": { 		- "percentage": 0, 		- "isLow": true 		}, 	- "stats": { 		- "light": { 			- "value": 0, 			- "status": "high" 			}, 		- "humidity": { 			- "value": 0, 			- "status": "high" 			}, 		- "temperature": { 			- "value": 0, 			- "status": "high" 			} 		}, 	- "lightSettings": { 		- "isEnabled": true, 		- "margin": 0, 		- "lowThreshold": 1, 		- "highThreshold": 0 		}, 	- "humiditySettings": { 		- "isEnabled": true, 		- "margin": 0, 		- "lowThreshold": 1, 		- "highThreshold": 0 		}, 	- "temperatureSettings": { 		- "isEnabled": true, 		- "margin": 0, 		- "lowThreshold": -39, 		- "highThreshold": 0 		}, 	- "isOpened": true, 	- "openStatusChangedAt": 0, 	- "isMotionDetected": true, 	- "motionDetectedAt": 0, 	- "motionSettings": { 		- "isEnabled": true, 		- "sensitivity": 100 		}, 	- "alarmTriggeredAt": 0, 	- "alarmSettings": { 		- "isEnabled": true 		}, 	- "leakDetectedAt": 0, 	- "externalLeakDetectedAt": 0, 	- "leakSettings": { 		- "isInternalEnabled": true, 		- "isExternalEnabled": true 		}, 	- "tamperingDetectedAt": 0 	} ]`

## NVR information & management

### Response samples

- 200

Content type

application/json

`{ - "id": "66d025b301ebc903e80003ea", - "modelKey": "nvr", - "name": "string", - "doorbellSettings": { 	- "defaultMessageText": "string", 	- "defaultMessageResetTimeoutMs": 0, 	- "customMessages": [ 		- "string" 		], 	- "customImages": [ 		- { 			- "preview": "string", 			- "sprite": "string" 			} 		] 	} }`

## Device asset file management

## Upload device asset file

Upload a new device asset file

##### path Parameters

| fileType  required | string (assetFileType)  Value:"animations"  Device asset file type |
| --- | --- |

##### Request Body schema: multipart/form-data

string <binary>

A binary file with one of these MIME types: image/gif, image/jpeg, image/png, audio/mpeg, audio/mp4, audio/wave, audio/x-caf}

### Response samples

- 200

Content type

application/json

`{ - "name": "string", - "type": "animations", - "originalName": "string", - "path": "string" }`

### Response samples

- 200

Content type

application/json

`[ - { 	- "name": "string", 	- "type": "animations", 	- "originalName": "string", 	- "path": "string" 	} ]`

## Chime information & management

### Response samples

- 200

Content type

application/json

`{ - "id": "66d025b301ebc903e80003ea", - "modelKey": "chime", - "state": "CONNECTED", - "name": "string", - "mac": "string", - "cameraIds": [ 	- "66d025b301ebc903e80003ea" 	], - "ringSettings": [ 	- { 		- "cameraId": "string", 		- "repeatTimes": 1, 		- "ringtoneId": "string", 		- "volume": 100 		} 	] }`

## Patch chime settings

Patch the settings for a specific chime

##### path Parameters

| id  required | string (chimeId)  Examples: 66d025b301ebc903e80003ea 672094f900e26303e800062a  The primary key of chime |
| --- | --- |

##### Request Body schema: application/jsonrequired

| name | string  The name of the chime |
| --- | --- |
| cameraIds | Array of strings (cameraId)  The list of (doorbell-only) cameras which this chime is paired to. |
|  | Array of objects (ringSettings)  List of custom ringtone settings for (doorbell-only) cameras paired to this chime. |

### Request samples

- Payload

Content type

application/json

`{ - "name": "string", - "cameraIds": [ 	- "66d025b301ebc903e80003ea" 	], - "ringSettings": [ 	- { 		- "cameraId": "string", 		- "repeatTimes": 1, 		- "ringtoneId": "string", 		- "volume": 100 		} 	] }`

### Response samples

- 200

Content type

application/json

`{ - "id": "66d025b301ebc903e80003ea", - "modelKey": "chime", - "state": "CONNECTED", - "name": "string", - "mac": "string", - "cameraIds": [ 	- "66d025b301ebc903e80003ea" 	], - "ringSettings": [ 	- { 		- "cameraId": "string", 		- "repeatTimes": 1, 		- "ringtoneId": "string", 		- "volume": 100 		} 	] }`

### Response samples

- 200

Content type

application/json

`[ - { 	- "id": "66d025b301ebc903e80003ea", 	- "modelKey": "chime", 	- "state": "CONNECTED", 	- "name": "string", 	- "mac": "string", 	- "cameraIds": [ 		- "66d025b301ebc903e80003ea" 		], 	- "ringSettings": [ 		- { 			- "cameraId": "string", 			- "repeatTimes": 1, 			- "ringtoneId": "string", 			- "volume": 100 			} 		] 	} ]`