import pytest
from sqlalchemy import select
from airlink import recharge_telegram as rt
from airlink.db import SessionLocal
from test_recharge_telegram import receipts, enqueue, deliver
from test_telegram_account import telegram, phone_test_token
from test_api import user

PATH='/api/integrations/recharge-telegram/templates'


def test_edit_preview_save_reset_are_language_and_method_specific(client, owner, receipts):
    initial=client.get(PATH+'/ku/card', headers=owner)
    assert initial.status_code==200 and not initial.json()['customized']
    text='سلاڤ {username}\n{method}\n{details}\n{reference}'
    result=client.post(PATH+'/ku/card/preview', headers=owner, json={'text':text})
    assert result.status_code==200 and 'sample-customer' in result.json()['preview']
    assert not client.get(PATH+'/ku/card', headers=owner).json()['customized']
    result=client.put(PATH+'/ku/card', headers=owner, json={'text':text})
    assert result.status_code==200 and result.json()['text']==text and result.json()['customized']
    assert not client.get(PATH+'/en/card', headers=owner).json()['customized']
    assert not client.get(PATH+'/ku/fib', headers=owner).json()['customized']
    result=client.delete(PATH+'/ku/card', headers=owner)
    assert result.status_code==200 and not result.json()['customized']
    assert result.json()['text']==initial.json()['text']
    assert not [c for c in receipts[0][1] if isinstance(c,tuple) and c[0]=='send']


@pytest.mark.parametrize('invalid',['', ' ', '{password}', '{username.__class__}', '{username[0]}',
    '{username!r}', '{username:>100000}', '{}', '{', '{details}{details}', 'x'*1501, 'Hello\x00'])
def test_invalid_templates_rejected_without_saving(client, owner, invalid):
    for suffix in ('', '/preview'):
        response=client.request('PUT' if not suffix else 'POST',PATH+'/en/card'+suffix, headers=owner,json={'text':invalid})
        assert response.status_code==422
    with SessionLocal() as db:
        assert db.scalar(select(rt.MessageTemplate)) is None


@pytest.mark.parametrize('kind',['card','credit','extend','fib','fastpay'])
def test_custom_template_used_for_actual_queued_receipt(client, owner, receipts, kind):
    event_id=enqueue(receipts,kind)
    text='CUSTOM {method}: {username}\n{details}\nReference {reference}'
    assert client.put(PATH+'/en/'+kind,headers=owner,json={'text':text}).status_code==200
    assert deliver(event_id)[0]=='sent'
    sent=[c[1].message for c in receipts[0][1] if isinstance(c,tuple) and c[0]=='send']
    assert sent[-1].startswith('CUSTOM ')
    assert '20 Mbps' in sent[-1] and '2027-01-01' in sent[-1]
    assert 'PRIVATE' not in sent[-1] and '+964' not in sent[-1]


def test_custom_phone_test_uses_selected_language_and_safe_details(client, owner, receipts):
    assert client.put('/api/integrations/recharge-telegram/language',headers=owner,json={'language':'ar'}).status_code==200
    assert client.put(PATH+'/ar/test',headers=owner,json={'text':'مرحبا {username}، {profile} {reference}'}).status_code==200
    token=phone_test_token(client,owner)
    result=client.post('/api/integrations/telegram-account/users/7/test',headers=owner,json={'test_token':token,'language':'en'})
    assert result.status_code==200
    sent=[c[1].message for c in receipts[0][1] if isinstance(c,tuple) and c[0]=='send']
    assert sent[-1]=='مرحبا customer، 20 Mbps TEST'


def test_templates_owner_only_and_do_not_change_sender_settings(client, owner, receipts):
    _, manager=user(client,owner,'manager')
    for method,suffix,body in [('GET','',None),('DELETE','',None),('PUT','',{'text':'Hello'}),('POST','/preview',{'text':'Hello'})]:
        result=client.request(method,PATH+'/en/card'+suffix,headers=manager,**({'json':body} if body else {}))
        assert result.status_code==403
    before=client.get('/api/integrations/recharge-telegram',headers=owner).json()
    assert client.put(PATH+'/en/card',headers=owner,json={'text':'Hello {username}'}).status_code==200
    assert client.get('/api/integrations/recharge-telegram',headers=owner).json()==before


def test_plain_text_braces_and_currency_preview(client, owner):
    result=client.post(PATH+'/en/fib/preview',headers=owner,json={'text':'{{Receipt}} {amount} {currency} <b>{username}</b>'})
    assert result.status_code==200
    assert result.json()['preview']=='{Receipt} 25000 IQD <b>sample-customer</b>'
    assert client.get(PATH+'/en/unsupported',headers=owner).status_code==422


def test_recharge_cost_replaces_amount_and_preserves_legacy_templates(client, owner):
    with SessionLocal() as db:
        db.add(rt.MessageTemplate(language='en', kind='fib', text='Cost {amount} {currency}; literal {{amount}}'))
        db.commit()
    response=client.get(PATH+'/en/fib',headers=owner).json()
    assert 'recharge_cost' in response['placeholders'] and 'amount' not in response['placeholders']
    assert response['text']=='Cost {recharge_cost} {currency}; literal {{amount}}'
    assert response['preview']=='Cost 25000 IQD; literal {amount}'
    result=client.put(PATH+'/en/fastpay',headers=owner,json={'text':'{amount} {currency}'})
    assert result.status_code==200 and result.json()['text']=='{recharge_cost} {currency}'
    assert result.json()['preview']=='25000 IQD'


@pytest.mark.parametrize('cost', ['2000', '0'])
def test_explicit_recharge_cost_is_rendered_for_card_and_extension(cost):
    from types import SimpleNamespace
    from airlink.models import now
    for kind in ('card', 'credit', 'extend', 'fib', 'fastpay'):
        data={'language':'en','timezone':'Asia/Baghdad','receipt':{'username':'customer','recharge_cost':cost,'amount':'2500','currency':'IQD'}}
        rendered=rt.message(SimpleNamespace(kind=kind,created_at=now()),data)
        assert f'Recharge cost: {cost} IQD' in rendered and '2500' not in rendered
        assert rt.message_values(SimpleNamespace(kind=kind,created_at=now()),data)['recharge_cost']==cost


def test_legacy_payment_amount_is_not_mislabeled_as_manager_cost():
    from types import SimpleNamespace
    from airlink.models import now
    data={'language':'en','timezone':'Asia/Baghdad','receipt':{'username':'customer','amount':'2500','currency':'IQD'}}
    event=SimpleNamespace(kind='fib',created_at=now())
    assert rt.message_values(event,data)['recharge_cost']==''
    assert 'Recharge cost:' not in rt.message(event,data)
