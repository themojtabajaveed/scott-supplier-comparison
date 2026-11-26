import pytest
from scout.engine.llm import GeminiFree, BudgetExceeded

RESP = {"candidates": [{"content": {"parts": [{"text": "{}"}]}}],
        "usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 20}}

def test_call_cap_fails_closed():
    llm = GeminiFree("k", max_calls=1, transport=lambda op, body: {'totalTokens':100} if op=='countTokens' else RESP)
    llm.generate_json("hi")
    with pytest.raises(BudgetExceeded):
        llm.generate_json("hi")

def test_output_cap_reserves_worst_case():
    llm = GeminiFree("k", max_output_tokens=330, max_output_per_call=300,
                     transport=lambda op, body: {'totalTokens':100} if op=='countTokens' else RESP)
    llm.generate_json("hi")  # reserves 300, reconciles to 20 actual
    llm.generate_json("hi")  # 20+300 <= 330 ok
    with pytest.raises(BudgetExceeded):
        llm.generate_json("hi")  # 40+300 > 330

def test_actual_usage_reconciles_down():
    llm = GeminiFree("k", transport=lambda op, body: {'totalTokens':100} if op=='countTokens' else RESP)
    llm.generate_json("hi")
    assert llm.spent == {"calls": 1, "input": 100, "output": 20}

def test_no_spend_on_cap_breach():
    llm = GeminiFree("k", max_calls=0, transport=lambda op, body: {'totalTokens':100} if op=='countTokens' else RESP)
    with pytest.raises(BudgetExceeded):
        llm.generate_json("hi")
    assert llm.spent == {"calls": 0, "input": 0, "output": 0}

def test_failed_generation_retains_reservation(tmp_path):
 def transport(op,body):
  if op=='countTokens': return {'totalTokens':100}
  raise TimeoutError('unknown external outcome')
 ledger=str(tmp_path/'usage.jsonl')
 llm=GeminiFree('k',max_calls=1,transport=transport,ledger_path=ledger)
 with pytest.raises(TimeoutError): llm.generate_json('test')
 assert llm.spent=={'calls':1,'input':100,'output':1024}
 with pytest.raises(BudgetExceeded): llm.generate_json('test')
 assert 'reserved' in open(ledger).read() and 'failed' in open(ledger).read()

def test_live_requires_billing_binding_and_ledger():
 with pytest.raises(RuntimeError): GeminiFree('k')

def test_missing_usage_retains_full_reservation():
 def transport(op,body):
  if op=='countTokens': return {'totalTokens':100}
  return {'candidates':[{'content':{'parts':[{'text':'{}'}]}}]}
 llm=GeminiFree('k',transport=transport)
 assert llm.generate_json('test')=={}
 assert llm.spent=={'calls':1,'input':100,'output':1024}

def test_preflight_error_recorded_without_generation(tmp_path):
 ledger=str(tmp_path/'ledger.jsonl')
 calls=[]
 def transport(op,body):
  calls.append(op);raise TimeoutError()
 llm=GeminiFree('k',transport=transport,ledger_path=ledger)
 with pytest.raises(TimeoutError):llm.generate_json('q')
 assert calls==['countTokens'] and llm.spent['calls']==0
 assert 'preflight_error' in open(ledger).read()
