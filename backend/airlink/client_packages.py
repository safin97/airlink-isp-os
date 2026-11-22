"""Customer package selection; service changes happen only after verified payment."""
from fastapi import HTTPException
from . import sas4, radius_pin
from .client_catalog import PLAN_NAMES


def validate_package(connection, password, customer_id, profile_id, expected_profile_id, expected_expiration):
    with sas4.sas4_session(connection, password) as (client, headers):
        permissions = sas4.user_permissions(client, headers)
        sas4.require_recharge(permissions, 'card')
        record = sas4.raw_user(client, headers, customer_id)
        if record.get('profile_id') != expected_profile_id or record.get('expiration') != expected_expiration:
            raise HTTPException(409, 'Your subscription changed. Refresh and select the package again.')
        profiles = sas4.response_json(client.get(sas4.DEFAULT_SERVER + sas4.API_PATH + 'list/profile/0', headers=headers)).get('data')
        if not isinstance(profiles, list):
            raise sas4.SAS4Error('Package choices are unavailable. Please try again.')
        plan = next((row for row in profiles if isinstance(row, dict)
                     and type(row.get('id')) is int and row['id'] == profile_id and row.get('name') in PLAN_NAMES), None)
        if plan is None:
            raise HTTPException(422, 'This package is not available for customer checkout.')
        if profile_id != expected_profile_id and not sas4.can_change_current_profile(record, permissions):
            raise HTTPException(403, 'Your provider must enable SAS4 service profile changes before you can buy a different package.')
        return {'profile_id': profile_id, 'name': plan['name']}


def quote(customer_id, profile_id, actor, db):
    connection, password = sas4.local_user_connection(db, actor)
    try:
        current = sas4.fetch_recharge(connection, password, customer_id)
        plan = validate_package(connection, password, customer_id, profile_id, current['profile_id'], current['expiration'])
        card = radius_pin.find_card(connection, password, profile_id, db)
        return {'items': [{k: v for k, v in card.items() if k != 'pin'}] if card else [], 'package': plan}
    except (sas4.SAS4Error, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    except sas4.httpx.HTTPError:
        raise HTTPException(502, 'SAS4 package availability could not be checked. Please try again.') from None


def apply_paid_package(connection, password, order, db):
    """Called by the already-claimed, paid activation only; never retry uncertain writes."""
    previous = order.quote.get('previous_profile_id')
    if previous is None:
        return
    target = order.quote['profile_id']
    validate_package(connection, password, order.sas4_user_id, target, previous, order.quote['expiration'])
    result = sas4.update_user(connection, password, order.sas4_user_id, {'profile_id': target})
    if result.get('saved') is not True:
        raise sas4.SAS4Error('The paid package change was not confirmed. Provider review is required.')
    current = sas4.fetch_recharge(connection, password, order.sas4_user_id)
    if current['profile_id'] != target:
        raise sas4.SAS4Error('The paid package change could not be verified. Provider review is required.')
    # SAS4 may adjust expiration on a profile change. Recharge against the newly verified snapshot.
    order.quote = {**order.quote, 'expiration': current['expiration'], 'profile_change_completed': True}
    db.commit()
