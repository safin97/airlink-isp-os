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
    role: Literal["owner", "manager", "technician", "viewer"]
    _strong = field_validator("password")(password_valid)


class TowerInput(Strict):
    name: str = Field(min_length=1, max_length=120)
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    location: str = Field(default="", max_length=250)
    management_ip: Optional[str] = None
    manager_id: Optional[str] = None
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
    vendor: Literal["generic", "mikrotik", "ubiquiti", "mimosa"] = "generic"
    model: str = Field(default="", max_length=120)
    snmp_profile_id: Optional[str] = None
    poll_interval: int = Field(default=60, ge=15, le=86400)
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


class ProfileInput(Strict):
    name: str = Field(min_length=1, max_length=120)
    username: str = Field(min_length=1, max_length=32)
    auth_key: str = Field(min_length=12, max_length=128)
    priv_key: str = Field(min_length=12, max_length=128)


class LinkInput(Strict):
    source_id: str
    target_id: str
    evidence: str = Field(min_length=10, max_length=500)
