"""Owner's encrypted inventory of existing recharge card PINs."""
import hashlib
import hmac
import re
from typing import Optional
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from .config import settings
from .db import get_db
from .models import SavedRechargeCard, RechargeCardReservation, RechargePayment, audit
from .security import owner, cipher
from . import sas4
from .sas4_cards import router as radius_router

router = APIRouter(prefix='/api/card-system', tags=['Card System'])
router.include_router(radius_router)


class CardProfileInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    profile_id: Optional[int] = Field(default=None, ge=1)
    price_iqd: Optional[str] = Field(default=None, max_length=40)

    @model_validator(mode='after')
    def valid_price(self):
        if (self.profile_id is None) != (self.price_iqd is None):
            raise ValueError('Choose a profile and set its card price together')
        if self.price_iqd is not None:
            if not re.fullmatch(r'[0-9]+(?:\.[0-9]{1,2})?', self.price_iqd) or sas4.money(self.price_iqd) <= 0:
                raise ValueError('Enter a positive card price in IQD, with at most two decimal places')
            self.price_iqd = str(sas4.money(self.price_iqd))
        return self


class CardInput(CardProfileInput):
    label: str = Field(default='', max_length=120)
    pin: str = Field(min_length=1, max_length=128)

    @field_validator('pin')
    @classmethod
    def valid_pin(cls, value):
        if any(ord(char) < 32 for char in value):
            raise ValueError('Enter a valid card PIN')
        return value


def public(card, db):
    reservation = db.get(RechargeCardReservation, card.id)
    payment = db.get(RechargePayment, reservation.payment_id) if reservation else None
    state = ('used' if payment and payment.status == 'completed'
             else 'issued' if payment and payment.status == 'pin_ready'
             else 'reserved' if reservation else 'available')
    return {'id': card.id, 'label': card.label, 'profile_id': card.profile_id, 'price_iqd': card.price_iqd,
            'created_at': card.created_at, 'state': state,
            'payment_id': reservation.payment_id if reservation else None}


def owned(db, user, card_id):
    card = db.scalar(select(SavedRechargeCard).where(SavedRechargeCard.id == card_id).with_for_update())
    if card is None or card.user_id != user.id:
        raise HTTPException(404, 'Saved card not found')
    return card


@router.get('')
def list_cards(offset: int = Query(default=0, ge=0), available: bool = False,
               profile_id: Optional[int] = Query(default=None, ge=1), user=Depends(owner), db=Depends(get_db)):
    query = select(SavedRechargeCard).where(SavedRechargeCard.user_id == user.id)
    if profile_id is not None:
        query = query.where(SavedRechargeCard.profile_id == profile_id, SavedRechargeCard.price_iqd.is_not(None))
    if available:
        query = query.where(~select(RechargeCardReservation.card_id).where(
            RechargeCardReservation.card_id == SavedRechargeCard.id).exists())
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(query.order_by(SavedRechargeCard.created_at.desc(), SavedRechargeCard.id).offset(offset).limit(50))
    return {'items': [public(row, db) for row in rows], 'total': total}


@router.get('/profiles')
def profiles(user=Depends(owner), db=Depends(get_db)):
    connection, password = sas4.local_user_connection(db, user)
    try:
        with sas4.sas4_session(connection, password) as (client, headers):
            rows = sas4.response_json(client.get(sas4.DEFAULT_SERVER + sas4.API_PATH + 'list/profile/0', headers=headers)).get('data')
            if not isinstance(rows, list):
                raise sas4.SAS4Error('SAS4 profiles are unavailable')
            return [{'id': row['id'], 'name': row.get('name', str(row['id']))} for row in rows
                    if isinstance(row, dict) and type(row.get('id')) is int and row['id'] > 0]
    except (sas4.SAS4Error, httpx.HTTPError) as exc:
        raise HTTPException(502, 'SAS4 profiles are unavailable. Check your SAS4 connection.') from exc


@router.post('', status_code=201)
def add_card(data: CardInput, user=Depends(owner), db=Depends(get_db)):
    fingerprint = hmac.new(settings.encryption_key.encode(),
                           ('recharge-card:' + user.id + ':' + data.pin).encode(), hashlib.sha256).hexdigest()
    card = SavedRechargeCard(user_id=user.id, label=data.label, profile_id=data.profile_id, price_iqd=data.price_iqd,
        encrypted_pin=cipher().encrypt(data.pin.encode()).decode(), pin_digest=fingerprint)
    db.add(card)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, 'This PIN is already saved')
    audit(db, user, 'card_system.add', card.id)
    db.commit()
    return public(card, db)


@router.put('/{card_id}/profile')
def assign_profile(card_id: str, data: CardProfileInput, user=Depends(owner), db=Depends(get_db)):
    card = owned(db, user, card_id)
    if db.get(RechargeCardReservation, card.id):
        raise HTTPException(409, 'Cards reserved or issued for a payment cannot be changed.')
    card.profile_id, card.price_iqd = data.profile_id, data.price_iqd
    audit(db, user, 'card_system.profile', card.id)
    db.commit()
    return public(card, db)


@router.post('/{card_id}/pin')
def read_pin(card_id: str, user=Depends(owner), db=Depends(get_db)):
    card = owned(db, user, card_id)
    if db.get(RechargeCardReservation, card.id):
        raise HTTPException(409, 'This card is assigned to a payment. Get its PIN from the verified payment.')
    try:
        pin = cipher().decrypt(card.encrypted_pin.encode()).decode()
    except Exception as exc:
        raise HTTPException(409, 'This PIN cannot be read. Add the card again with the original PIN.') from exc
    audit(db, user, 'card_system.read_pin', card.id)
    db.commit()
    return {'pin': pin}


@router.delete('/{card_id}', status_code=204)
def delete_card(card_id: str, user=Depends(owner), db=Depends(get_db)):
    card = owned(db, user, card_id)
    if db.get(RechargeCardReservation, card.id):
        raise HTTPException(409, 'Cards reserved or issued for a payment cannot be removed.')
    audit(db, user, 'card_system.delete', card.id)
    db.delete(card)
    db.commit()
