from contextlib import contextmanager
from types import SimpleNamespace
import json
import httpx
import pytest
from fastapi import HTTPException
from airlink import client_catalog as catalog, sas4


@pytest.fixture
def remote(monkeypatch):
    state = {'currency':'IQD', 'permissions':['prm_cards_index'],
             'prices':[14000,18200,22400,29400,37800], 'vat':'0.00', 'calls':[], 'mismatch':False, 'used':1}
    profiles=[{'id':97+i, 'name':name} for i,name in enumerate(catalog.PLAN_NAMES)]
    monkeypatch.setattr(sas4,'wire_payload',lambda data:data)
    @contextmanager
    def session(*args):
        def handle(request):
            path=request.url.path.removeprefix(sas4.API_PATH)
            state['calls'].append(path)
            if path=='auth': data={'permissions':state['permissions']}
            elif path=='resources/login': data={'data':{'site_currency':state['currency']}}
            elif path=='list/profile/0': data={'data':list(reversed(profiles))+[{'id':666,'name':'PRIVATE VIP'}]}
            elif path=='index/series':
                page=json.loads(request.content)['page']
                data={'data':[{'profile_id':98,'type':0,'suspended':0,'expiration':'2099-12-31','value':'25000','qty':1,'used':state['used'],
                              'pin':'PRIVATE-PIN', 'owner_details':{'username':'PRIVATE-OWNER'}}],
                      'total':1,'per_page':100,'current_page':page}
            elif path.startswith('profile/'):
                id=int(path.split('/')[1])
                assert 97<=id<=101
                data={'status':200,'data':{**profiles[id-97], 'price':state['prices'][id-97], 'vat':state['vat'],
                       'id':999 if state['mismatch'] else id, 'secret':'PRIVATE'}}
            else: pytest.fail('Unexpected route '+path)
            return httpx.Response(200,json=data)
        with httpx.Client(transport=httpx.MockTransport(handle)) as client:
            yield client,{}
    monkeypatch.setattr(sas4,'sas4_session',session)
    return state


def test_catalog_keeps_retail_prices_while_syncing_profiles_and_stock(remote):
    data=catalog.fetch_catalog(SimpleNamespace(),'secret')
    assert [row['name'] for row in data['items']]==list(catalog.PLAN_NAMES)
    assert [float(row['price_iqd']) for row in data['items']]==[20000,25000,32000,40000,50000]
    assert data['items'][1]['stock_status']=='sold_out'
    assert data['items'][0]['stock_status']=='no_cards'
    assert all(row['price_source']=='retail' for row in data['items'])
    assert 'PRIVATE' not in json.dumps(data)
    assert not any(path.startswith(('index/card/', 'profile/')) for path in remote['calls'])


@pytest.mark.parametrize('kind',['currency','permission'])
def test_invalid_catalog_data_fails_closed(remote,kind):
    if kind=='currency': remote['currency']='USD'
    if kind=='permission': remote['permissions']=[]
    with pytest.raises((sas4.SAS4Error,HTTPException)):
        catalog.fetch_catalog(SimpleNamespace(),'secret')



@pytest.mark.parametrize('used_count',[None,''])
def test_blank_aggregate_is_check_required_not_sold_out(remote,used_count):
    remote['used']=used_count
    data=catalog.fetch_catalog(SimpleNamespace(),'secret')
    assert data['items'][1]['stock_status']=='check_required'
    assert data['items'][1]['price_iqd']=='25000'
