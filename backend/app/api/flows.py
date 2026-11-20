from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_keitaro
from app.schemas.editor import CampaignDetail
from app.services.keitaro_client import KeitaroClient
from app.services.upload_service import upload_flow

router = APIRouter(prefix="/flows")


class UploadRequest(BaseModel):
    force: bool = False


@router.post("/{flow_id}/upload", response_model=CampaignDetail)
def upload(
    flow_id: int,
    body: UploadRequest | None = None,
    client: KeitaroClient = Depends(get_keitaro),
    session: Session = Depends(get_db),
):
    """Upload выбранного потока в Keitaro (§4.9)."""
    return upload_flow(client, session, flow_id, force=bool(body and body.force))
