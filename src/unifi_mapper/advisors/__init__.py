#!/usr/bin/env python3
"""
Security Advisors for UniFi Port Mapper.

This package provides security and firmware advisory capabilities.
"""

from .firmware_advisor import (
    FirmwareAdvisor,
    FirmwareStatus,
    DeviceFirmwareInfo,
    FirmwareSecurityReport,
)

__all__ = [
    "FirmwareAdvisor",
    "FirmwareStatus",
    "DeviceFirmwareInfo",
    "FirmwareSecurityReport",
]
