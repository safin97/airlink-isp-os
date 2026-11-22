"""Customer plan catalog with owner-specified retail prices; never fetch or expose PINs."""
from datetime import date
from zoneinfo import ZoneInfo
from . import sas4, sas4_cards, radius_pin
from .models import now

RETAIL_PRICES_IQD = {
    'AirLink Basic': '20000',
    'AirLink Plus': '25000',
    'AirLink Pro': '32000',
    'AirLink Ultra': '40000',
    'AirLink Max': '50000',
}
PLAN_NAMES = tuple(RETAIL_PRICES_IQD)


def fetch_catalog(connection, password):
    with sas4.sas4_session(connection, password) as (client, headers):
        permissions = sas4.user_permissions(client, headers)
        sas4_cards.require(permissions, 'prm_cards_index')
        profiles = sas4.response_json(client.get(sas4.DEFAULT_SERVER + sas4.API_PATH + 'list/profile/0', headers=headers)).get('data')
        currency = sas4.response_json(client.get(sas4.DEFAULT_SERVER + sas4.API_PATH + 'resources/login', headers=headers)).get('data', {}).get('site_currency')
        if not isinstance(profiles, list) or len(profiles) > 10000 or currency != 'IQD':
            raise sas4.SAS4Error('SAS4 card profiles or IQD prices are unavailable.')
        selected = {row['id']: row['name'] for row in profiles if isinstance(row, dict)
                    and type(row.get('id')) is int and row['id'] > 0 and row.get('name') in PLAN_NAMES}
        prices = {id: set() for id in selected}
        stock = {id: 0 for id in selected}
        unknown_stock = set()
        today = now().astimezone(ZoneInfo('Asia/Baghdad')).date()
        for row in radius_pin.rows(client, headers, 'index/series',
                {'sortBy': 'series_date', 'direction': 'desc', 'search': '', 'parent_id': -1, 'type': 0, 'profile_id': -1}, [12]):
            try:
                profile_id = int(row['profile_id'])
                if profile_id not in selected or str(row['type']) != '0' or sas4.flag(row.get('suspended')) is not False:
                    continue
                if row.get('expiration') and date.fromisoformat(str(row['expiration'])[:10]) <= today:
                    continue
                price = sas4.money(row['value'])
                remaining = radius_pin.series_remaining(row)
                if price <= 0:
                    continue
            except (KeyError, ValueError, TypeError):
                continue
            prices[profile_id].add(price)
            if remaining is None:
                unknown_stock.add(profile_id)
            else:
                stock[profile_id] += remaining
        items = []
        for profile_id, name in sorted(selected.items(), key=lambda item: (PLAN_NAMES.index(item[1]), item[0])):
            values = prices[profile_id]
            items.append({'profile_id': profile_id, 'name': name,
                'price_iqd': RETAIL_PRICES_IQD[name], 'price_source': 'retail',
                'stock_status': 'check_required' if stock[profile_id] or profile_id in unknown_stock else ('sold_out' if values else 'no_cards')})
        return {'items': items, 'currency': currency, 'synced_at': now().isoformat()}
