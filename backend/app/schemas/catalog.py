"""DTO справочников: наружу отдаём только id/name, без служебных полей Keitaro."""
from pydantic import BaseModel, field_validator


class Country(BaseModel):
    code: str
    name: str


class ReferenceItem(BaseModel):
    id: int
    name: str


class DomainItem(ReferenceItem):
    is_ssl: bool = True


class OfferItem(BaseModel):
    id: int
    name: str


class Defaults(BaseModel):
    domain_id: int | None = None
    group_id: int | None = None
    source_id: int | None = None
    google_redirect_url: str


class KeitaroCampaignItem(BaseModel):
    """Кампания для выбора в Edit Campaign: без token и прочих служебных полей."""

    id: int
    name: str
    alias: str
    state: str | None = None


class GroupCreate(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("Имя группы не может быть пустым")
        if len(v) > 255:
            raise ValueError("Имя группы не может быть длиннее 255 символов")
        return v
