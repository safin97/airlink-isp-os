import ipaddress
from typing import Optional, Literal
from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator
from .security import password_valid


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def ip(value):
    if value is None or value == "":
        return None
    address = ipaddress.ip_address(value)
    if address.is_multicast or address.is_unspecified or address.is_loopback or address.is_link_local:
        raise ValueError("Use a unicast management address")
    return str(address)


class Login(Strict):
    username: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=1, max_length=128)


class Setup(Login):
    token: str = Field(min_length=32, max_length=200)
    confirm_password: str
    _strong = field_validator("password")(password_valid)

    @model_validator(mode="after")
    def matches(self):
        if self.password != self.confirm_password:
            raise ValueError("Passwords do not match")
        return self


class UserInput(Login):
    show_snmp_profiles: Optional[bool] = None
    role: Literal["owner", "manager", "technician", "viewer"]
    manager_role_id: Optional[str] = None
    access_role_id: Optional[str] = None
    parent_id: Optional[str] = Field(default=None, min_length=1, max_length=36)
    place_ids: Optional[list[str]] = Field(default=None, max_length=1000)
    _strong = field_validator("password")(password_valid)


class PlaceInput(Strict):
    name: str = Field(min_length=1, max_length=120)

    @field_validator('name')
    @classmethod
    def clean_name(cls, value):
        value = value.strip()
        if not value:
            raise ValueError('Place name is required')
        return value


class TowerInput(Strict):
    name: str = Field(min_length=1, max_length=120)
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    location: str = Field(default="", max_length=250)
    management_ip: Optional[str] = None
    manager_id: Optional[str] = None
    place_id: Optional[str] = None
    api_enabled: Optional[bool] = None
    api_username: Optional[str] = Field(default=None, max_length=128)
    api_password: Optional[str] = Field(default=None, max_length=256)
    api_protocol: Optional[Literal["https", "http", "both"]] = None
    api_port: Optional[int] = Field(default=None, ge=1, le=65535)
    api_verify_tls: Optional[bool] = None
    _ip = field_validator("management_ip")(ip)

    @model_validator(mode="after")
    def coordinate_pair(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Provide both coordinates")
        return self


class SectorInput(Strict):
    tower_id: str
    name: str = Field(min_length=1, max_length=120)
    ssid: str = Field(default="", max_length=120)
    frequency_mhz: Optional[int] = Field(default=None, ge=1, le=100000)
    channel_width_mhz: Optional[int] = Field(default=None, ge=1, le=1000)
    model: str = Field(default="", max_length=120)
    ip_address: Optional[str] = None
    _ip = field_validator("ip_address")(ip)


class DeviceInput(Strict):
    tower_id: str
    sector_id: Optional[str] = None
    name: str = Field(min_length=1, max_length=120)
    ip_address: str
    vendor: Literal["generic", "mikrotik", "mikrotik_switch", "ubiquiti", "ubiquiti_m5", "ubiquiti_ac", "mimosa"] = "generic"
    model: str = Field(default="", max_length=120)
    snmp_profile_id: Optional[str] = None
    poll_interval: int = Field(default=60, ge=15, le=86400)
    connection_timeout: int = Field(default=2, ge=1, le=30)
    retries: int = Field(default=2, ge=0, le=5)
    failure_threshold: int = Field(default=3, ge=1, le=20)
    cpu_threshold: float = Field(default=90, ge=1, le=100)
    enabled: bool = True
    @field_validator("ip_address")
    @classmethod
    def device_ip(cls, value):
        result = ip(value)
        if result is None:
            raise ValueError("Management IP is required")
        return result


class DeviceSNMPAssignment(Strict):
    snmp_profile_id: str = Field(min_length=1, max_length=36)
    tower_id: str = Field(min_length=1, max_length=36)
    expected_ip_address: str
    previous_snmp_profile_id: Optional[str] = Field(max_length=36)
    _ip = field_validator('expected_ip_address')(ip)


class ProfileInput(Strict):
    name: str = Field(min_length=1, max_length=120)
    version: Literal["1", "2c", "3"] = "3"
    community: Optional[str] = Field(default=None, min_length=1, max_length=255)
    username: Optional[str] = Field(default=None, min_length=1, max_length=32)
    auth_key: Optional[str] = Field(default=None, min_length=8, max_length=128)
    priv_key: Optional[str] = Field(default=None, min_length=8, max_length=128)

    auth_protocol: Optional[Literal["SHA1", "SHA256", "MD5"]] = None
    priv_protocol: Optional[Literal["AES128", "DES"]] = None

    @field_validator('version', mode='before')
    @classmethod
    def normalize_version(cls, value):
        return '2c' if value == '2' else value

    @model_validator(mode="after")
    def credentials_for_version(self):
        if self.version == "3":
            if not all((self.username, self.auth_key, self.priv_key)) or self.community is not None:
                raise ValueError("SNMPv3 requires username, authentication and privacy keys")
        elif not self.community or not self.community.strip() or any((self.username, self.auth_key, self.priv_key, self.auth_protocol, self.priv_protocol)):
            raise ValueError("SNMPv1/v2c requires a community string only")
        return self


class LinkInput(Strict):
    source_id: str
    target_id: str
    evidence: str = Field(min_length=10, max_length=500)


class DiscoveryInput(Strict):
    prefix: int = Field(default=24, ge=24, le=32)


class SNMPDiscoveryInput(DiscoveryInput):
    offset: int = Field(default=0, ge=0, le=254)
    profile_id: Optional[str] = Field(default=None, min_length=1, max_length=36)


class SNMPPublicProfileInput(Strict):
    version: Literal['1', '2c']


class SNMPDiscoveryProfileInput(SNMPPublicProfileInput):
    source_profile_id: str = Field(min_length=1, max_length=36)


class SectionAccessInput(Strict):
    sections: list[Literal['dashboard', 'noc', 'towers', 'isp_card', 'monitoring', 'network_map', 'alerts', 'reports', 'software_updates', 'settings', 'roles', 'access_roles']] = Field(max_length=12)
    editable_sections: Optional[list[Literal['dashboard', 'noc', 'towers', 'isp_card', 'monitoring', 'network_map', 'alerts', 'reports', 'software_updates', 'settings', 'roles', 'access_roles']]] = Field(default=None, max_length=12)

    deletable_sections: Optional[list[Literal['dashboard', 'noc', 'towers', 'isp_card', 'monitoring', 'network_map', 'alerts', 'reports', 'software_updates', 'settings', 'roles', 'access_roles']]] = Field(default=None, max_length=12)

    @model_validator(mode='after')
    def edits_require_visibility(self):
        if self.editable_sections is not None and not set(self.editable_sections).issubset(self.sections):
            raise ValueError('Editable sections must also be visible')
        if self.deletable_sections is not None and not set(self.deletable_sections).issubset(self.sections):
            raise ValueError('Delete permissions require read access')
        return self


class ManagerUpdate(Strict):
    show_snmp_profiles: Optional[bool] = None
    role: Optional[Literal["manager", "technician", "viewer"]] = None
    manager_role_id: Optional[str] = None
    access_role_id: Optional[str] = None
    parent_id: Optional[str] = Field(default=None, min_length=1, max_length=36)
    place_ids: Optional[list[str]] = Field(default=None, max_length=1000)
    username: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: Optional[str] = None

    @field_validator("password")
    @classmethod
    def optional_password(cls, value):
        return None if value in (None, "") else password_valid(value)


class PasswordChange(Strict):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=14, max_length=128)
    confirm_password: str = Field(min_length=1, max_length=128)
    _strong = field_validator('new_password')(password_valid)

    @model_validator(mode='after')
    def matches(self):
        if self.new_password != self.confirm_password:
            raise ValueError('New passwords do not match')
        return self


class AccessRoleInput(SectionAccessInput):
    name: str = Field(min_length=1, max_length=64)
    editable_sections: list[Literal['dashboard', 'noc', 'towers', 'isp_card', 'monitoring', 'network_map', 'alerts', 'reports', 'software_updates', 'settings', 'roles', 'access_roles']] = Field(max_length=12)
    deletable_sections: list[Literal['dashboard', 'noc', 'towers', 'isp_card', 'monitoring', 'network_map', 'alerts', 'reports', 'software_updates', 'settings', 'roles', 'access_roles']] = Field(max_length=12)

    @field_validator('name')
    @classmethod
    def clean_name(cls, value):
        value = value.strip()
        if not value:
            raise ValueError('Name is required')
        return value

    @model_validator(mode='after')
    def deletes_require_visibility(self):
        if not set(self.deletable_sections).issubset(self.sections):
            raise ValueError('Delete permissions require read access')
        return self


class ManagerRoleInput(Strict):
    name: str = Field(min_length=1, max_length=64)
    access_role_id: str = Field(min_length=1, max_length=36)
    _clean = field_validator('name')(AccessRoleInput.clean_name.__func__)


class WirelessSSIDInput(Strict):
    menu: Literal['wireless', 'wifi', 'wifiwave2']
    radio_id: str = Field(pattern=r'^\*[0-9A-Fa-f]+$', max_length=32)
    ssid: str = Field(min_length=1, max_length=32)
    previous_ssid: str = Field(max_length=32)

    @model_validator(mode='after')
    def valid_ssid(self):
        if len(self.ssid.encode('utf-8')) > 32 or any(ord(c) < 32 or ord(c) == 127 for c in self.ssid):
            raise ValueError('SSID must be 1–32 UTF-8 bytes without control characters')
        return self
