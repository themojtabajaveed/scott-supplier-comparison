import pytest
from scout.engine.live_adapter import run_live_plan
from scout.engine.planner import plan_question
from scout.engine.tool_loop import execute_plan
from scout.engine.llm import BudgetExceeded
from tests.test_planner_loop import SUP,Browser

def test_review_gate_precedes_adapter_construction():
 def forbidden(*a,**k):raise AssertionError('adapter constructed')
 with pytest.raises(RuntimeError,match='closed'):
  run_live_plan(plan_question(SUP),api_key='test-only',verified_free_project='offline-test-project-placeholder',ledger_path='fixture',browser_factory=forbidden,client_factory=forbidden)

def test_needs_clarification_zero_adapters_even_if_reviewed():
 def forbidden(*a,**k):raise AssertionError('adapter constructed')
 r=run_live_plan(plan_question('flour 25kg'),api_key=None,verified_free_project=None,ledger_path=None,safety_reviewed=True,browser_factory=forbidden,client_factory=forbidden)
 assert r['state']=='needs_clarification'

def test_real_adapter_composition_contract_and_cleanup():
 captures={}
 class FakeBrowser(Browser):
  def close(self):captures['closed']=True
 class FakeClient:
  def __init__(self,key,**kwargs):captures.update(kwargs)
  def generate_structured(self,p,s):return {}
 r=run_live_plan(plan_question(SUP),api_key='test-only',verified_free_project='offline-test-project-placeholder',ledger_path='fixture',safety_reviewed=True,browser_factory=FakeBrowser,client_factory=FakeClient)
 # Product page, then the configured same-site delivery page (the fake page offers no link).
 assert r['generation_calls']==2 and captures['closed']
 assert captures['max_calls']==6 and captures['ledger_path']=='fixture'

def test_provider_budget_stop_prevents_next_site():
 p=plan_question('Compare strong white bread flour 16kg delivery')
 class OverBudget:
  calls=0
  def generate_structured(self,p,s):self.calls+=1;raise BudgetExceeded('stop')
 client=OverBudget();r=execute_plan(p,Browser(),client)
 assert len(r['rows'])==1 and client.calls==1
 assert r['rows'][0]['stop_reason']=='provider_budget_stop'

def test_unapproved_supplied_url_needs_clarification():
 p=plan_question(SUP+' https://attacker.example/product')
 assert p.state=='needs_clarification' and 'attacker.example' in p.question

@pytest.mark.parametrize('question',[
 'Compare strong white bread flour 16kg prices at randommill.co.uk',
 'Compare strong white bread flour 16kg from "Random Mill"',
 'Compare Randommill strong white bread flour 16kg prices',
 'Compare Wessex and Random Mill strong white bread flour 16kg',
 'Compare strong white bread flour 16kg "Unknown Supplier"',
 'Compare strong white bread flour 16kg at https://attacker.example/product'])
def test_unparsed_source_or_proper_name_never_defaults(question):
 plan=plan_question(question)
 assert plan.state=='needs_clarification' and plan.question==question
 assert execute_plan(plan,None,None)['trace']==[]

def test_known_bare_domain_is_not_a_new_source():
 p=plan_question('Compare Wessex strong white bread flour 16kg at wessexmill.co.uk')
 assert p.state=='ready' and len(p.workflow['sites'])==1

@pytest.mark.parametrize('preposition',['at','on','from'])
@pytest.mark.parametrize('source',['randommill.co.uk','randommill.unfamiliartld','https://randommill.example/path'])
def test_supplied_domain_without_tld_allowlist_is_inert(preposition,source):
 p=plan_question('Compare strong white bread flour 16kg prices '+preposition+' '+source)
 assert p.state=='needs_clarification' and p.workflow['sites']==[]
