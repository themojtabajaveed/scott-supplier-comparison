import pytest
from scout.engine.planner import plan_question
from scout.engine.tool_loop import canonical_source,execute_plan
from scout.engine.comparison import assess_comparable
from tests.test_planner_loop import Browser,LLM,SUP

@pytest.mark.parametrize('name',['Ministral 3 8B','Mistral Large 3','gpt-6.1-sol','Claude Sonnet 5.5'])
def test_all_supported_models_ready(name):
 assert plan_question('Compare '+name+' Standard USD uncached input and output per million tokens').state=='ready'

@pytest.mark.parametrize('extra',['and Llama 4','and Unknown Model','with fast processing','in INR'])
def test_provider_residual_never_drops_entity(extra):
 q='Compare Ministral 3 8B Standard USD uncached input and output per million tokens '+extra
 p=plan_question(q);assert p.state=='needs_clarification' and p.workflow['sites']==[] and p.question==q

def test_fragment_stops_without_second_extraction():
 b=Browser();b.pick_evidence_link=lambda *a,**k:b.u+'#delivery'
 r=execute_plan(plan_question(SUP),b,LLM())
 assert r['generation_calls']==1 and r['rows'][0]['stop_reason']=='duplicate_source'
 assert canonical_source('https://x.example/p#delivery')=='https://x.example/p'

def test_wording_coverage_is_not_confirmed_conflict():
 e={'excluded':[{'value':'Islands'},{'value':'Islands and BFPO'}]}
 r=assess_comparable(e,{'excluded':'excluded'})
 assert not r['conflicts'] and r['status']=='incomplete_literal_variation'
 assert len(r['literal_variations']['excluded'])==2

def test_different_amounts_retained_as_possible_not_confirmed():
 r=assess_comparable({'amount':[{'value':'£21.30'},{'value':'£22.10'}]},{'amount':'price'})
 assert r['status']=='possible_numeric_disagreement' and len(r['conflicts']['amount'])==2
