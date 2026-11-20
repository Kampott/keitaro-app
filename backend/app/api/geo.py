from fastapi import APIRouter

from app.schemas.catalog import Country
from app.services.catalog_service import get_countries

router = APIRouter(prefix="/geo")


@router.get("", response_model=list[Country])
def list_countries():
    """ISO 3166-1 alpha-2: статический список, общий для frontend и валидации."""
    return list(get_countries())
