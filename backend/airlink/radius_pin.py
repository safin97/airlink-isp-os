"""Select an unused SAS4 refill PIN; local holds never claim to lock SAS4 itself."""
import hashlib
import hmac
import re
from datetime import date, timedelta
from zoneinfo import ZoneInfo
from sqlalchemy import select
from . import sas4, sas4_cards
from .config import settings
from .models import RadiusCardReservation, RechargeCardReservation, SavedRechargeCard, now


def source_key(card_id):
    return hashlib.sha256((sas4.DEFAULT_SERVER + '\0' + str(card_id)).encode()).hexdigest()


def rows(client, headers, route, payload, budget):
    """Bounded scans; preserve server pagination and never assume page one is complete."""
    for page in range(1, 11):
        budget[0] -= 1
        if budget[0] < 0:
            raise sas4.SAS4Error('SAS4 card search limit reached. Narrow the available series.')
        result = sas4.response_json(client.post(sas4.DEFAULT_SERVER + sas4.API_PATH + route,
            headers=headers, json=sas4.wire_payload({**payload, 'page': page, 'count': 100})))
        data = result.get('data')
        if not isinstance(data, list) or len(data) > 100 or any(not isinstance(row, dict) for row in data):
            raise sas4.SAS4Error('SAS4 card inventory is invalid.')
        try:
            total, size = int(result['total']), int(result.get('per_page', 100))
            current = int(result.get('current_page', page))
            if total < 0 or not 1 <= size <= 100 or current != page:
                raise ValueError()
        except (KeyError, ValueError, TypeError) as exc:
            raise sas4.SAS4Error('SAS4 card inventory pagination is invalid.') from exc
        yield from data
        if page * size >= total:
            return
        if not data:
            raise sas4.SAS4Error('SAS4 card inventory is incomplete.')
    raise sas4.SAS4Error('SAS4 inventory is too large to search safely. Narrow the available card series.')


def legacy_held(db, pin):
    reserved = db.execute(select(SavedRechargeCard.user_id, SavedRechargeCard.pin_digest)
        .join(RechargeCardReservation, RechargeCardReservation.card_id == SavedRechargeCard.id)).all()
    return any(hmac.compare_digest(digest, hmac.new(settings.encryption_key.encode(),
        ('recharge-card:' + user_id + ':' + pin).encode(), hashlib.sha256).hexdigest()) for user_id, digest in reserved)


def series_remaining(group):
    """Blank SAS4 aggregate counts require inspecting cards, not assuming exhaustion."""
    quantity = int(group['qty'])
    if quantity < 1:
        raise ValueError('Invalid card quantity')
    raw_used = group.get('used')
    if raw_used in (None, ''):
        return None
    used = int(raw_used)
    if used < 0 or used > quantity:
        raise ValueError('Invalid used-card count')
    return quantity - used


def find_card(connection, password, profile_id, db, card_id=None, series=None, payment_id=None):
    # All connections point at the same SAS4 server; the source key spans local accounts.
    held = set(db.scalars(select(RadiusCardReservation.source_key).where(
        RadiusCardReservation.payment_id != payment_id if payment_id else True)))
    with sas4.sas4_session(connection, password) as (client, headers):
        permissions = sas4.user_permissions(client, headers)
        sas4_cards.require(permissions, 'prm_cards_index')
        sas4_cards.require(permissions, 'prm_cards_download')
        sas4.require_recharge(permissions, 'card')
        currency = sas4.response_json(client.get(sas4.DEFAULT_SERVER + sas4.API_PATH + 'resources/login', headers=headers)).get('data', {}).get('site_currency')
        if currency != 'IQD':
            raise sas4.SAS4Error('SAS4 card values must be in IQD for FIB checkout.')
        budget = [12]
        for group in rows(client, headers, 'index/series', {'sortBy': 'series_date', 'direction': 'desc',
                'search': series or '', 'parent_id': -1, 'type': 0, 'profile_id': profile_id}, budget):
            group_id = str(group.get('series', ''))
            if not re.fullmatch(sas4_cards.SERIES_PATTERN, group_id) or len(group_id) > 128:
                continue
            if series is not None and group_id != series:
                continue
            try:
                if int(group['profile_id']) != profile_id or str(group['type']) != '0' or sas4.flag(group.get('suspended')) is not False:
                    continue
                if series_remaining(group) == 0:
                    continue
                expiration = group['expiration']
                if expiration:
                    # This integration's SAS4 server uses Iraq local dates; allow the full payment window.
                    deadline = (now() + timedelta(minutes=5)).astimezone(ZoneInfo('Asia/Baghdad')).date()
                    if date.fromisoformat(str(expiration)[:10]) <= deadline:
                        continue
                value = sas4.money(group['value'])
                if value <= 0:
                    continue
            except (KeyError, ValueError, TypeError):
                continue
            for card in rows(client, headers, 'index/card/' + group_id, {'sortBy': 'id', 'direction': 'asc',
                    'search': '', 'used_by': -1}, budget):
                remote_id = card.get('id')
                if type(remote_id) is not int or remote_id < 1 or (card_id is not None and remote_id != card_id):
                    continue
                if source_key(remote_id) in held:
                    continue
                if 'used_at' not in card or card['used_at'] not in (None, ''):
                    continue
                if card.get('user_id') not in (None, 0, '0') or card.get('manager_id') not in (None, 0, '0'):
                    continue
                pin = card.get('pin')
                if not isinstance(pin, str) or not pin.strip() or len(pin) > 128 or any(ord(c) < 32 for c in pin):
                    continue
                if legacy_held(db, pin):
                    continue
                return {'id': str(remote_id), 'series': group_id, 'label': 'SAS4 series ' + group_id,
                        'profile_id': profile_id, 'price_iqd': str(value), 'pin': pin}
    return None
