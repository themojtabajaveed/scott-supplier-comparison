from scout.engine.atomic_run import make_response_schema, extract_page
from scout.engine.table_evidence import render_tables
from scout.engine.llm import GeminiFree

def test_real_claim_names_in_schema_no_placeholder():
 s=make_response_schema({'delivery':{'amount':'amount','box_count':'packing'}})
 assert set(s['properties']['delivery']['properties'])=={'amount','box_count'}
 assert s['properties']['delivery']['additionalProperties'] is False
 assert 'required' not in s['properties']['delivery'] # missing is allowed

def test_table_row_preserves_model_and_column_association():
 text=render_tables([{'context':'Standard USD per million tokens','headers':['Model','Input','Cached input','Output'],
 'rows':[['Unseen Model Q','$0.71','$0.07','$1.93']]}])
 assert 'Model: Unseen Model Q | Input: $0.71 | Cached input: $0.07 | Output: $1.93' in text
 assert 'Standard USD per million tokens' in text

def test_structured_schema_is_transmitted_and_preflight_content_identical():
 calls=[]
 def transport(op,body):
  calls.append((op,body))
  if op=='countTokens':return {'totalTokens':100}
  return {'candidates':[{'content':{'parts':[{'text':'{}'}]}}], 'usageMetadata':{'promptTokenCount':100,'candidatesTokenCount':2}}
 llm=GeminiFree('k',transport=transport)
 schema=make_response_schema({'price':{'amount':'p'}})
 llm.generate_structured('test',schema)
 assert calls[0][1]['generateContentRequest']==calls[1][1]
 assert calls[1][1]['generationConfig']['responseJsonSchema']==schema

def test_structured_path_gets_exact_key_schema():
 class LLM:
  def generate_structured(self,prompt,schema):
   assert 'amount' in schema['properties']['price']['properties']
   return {'price':{'amount':{'value':'$0.71','quote':'Model Q Input: $0.71'},'model':{'value':'Model Q','quote':'Model Q Input: $0.71'}}}
 facts,bad=extract_page('q',{'price':{'amount':'price','model':'row'}},'Model Q Input: $0.71','https://fixture.example',LLM())
 assert facts['price']['amount']['value']=='$0.71'

def test_generated_row_labels_cannot_be_verbatim_source_quotes():
 class LLM:
  def generate_json(self,prompt):return {'price':{'amount':{'value':'$0.71','quote':'ROW | Input: $0.71'}}}
 facts,bad=extract_page('q',{'price':{'amount':'price'}},'ROW | Input: $0.71','https://fixture.example',LLM(),original_text='Model Q\n$0.71')
 assert not facts['price']
 assert bad['price']['amount']=='value_not_explicitly_supported_by_quote'

def test_original_cells_support_column_association_separately():
 class LLM:
  def generate_json(self,prompt):return {'model_price_output':{'amount':{'value':'$1.93','quote':'$1.93'},'model':{'value':'Model Q','quote':'Model Q'}}}
 facts,bad=extract_page('q',{'model_price_output':{'amount':'price','model':'row'}},'derived row','https://fixture.example',LLM(),original_text='Model Q $0.71 $1.93',tables=[{'headers':['Model','Input','Output'],'rows':[['Model Q','$0.71','$1.93']]}])
 assert facts['model_price_output']['amount']['association'][0]['header']=='Output'
 assert facts['model_price_output']['amount']['quote']=='$1.93'

def test_cached_column_cannot_support_uncached_input():
 class LLM:
  def generate_json(self,prompt):return {'model_price_input':{'amount':{'value':'$0.07','quote':'$0.07'},'model':{'value':'Model Q','quote':'Model Q'}}}
 facts,bad=extract_page('q',{'model_price_input':{'amount':'price','model':'row'}},'derived','https://fixture.example',LLM(),original_text='Model Q $0.71 $0.07 $1.93',tables=[{'headers':['Model','Input','Cached input','Output'],'rows':[['Model Q','$0.71','$0.07','$1.93']]}])
 assert 'amount' not in facts['model_price_input']

def test_schema_tokens_participate_in_preflight_and_cap():
 import pytest,json
 from scout.engine.llm import BudgetExceeded
 calls=[]
 def transport(op,body):
  calls.append(op)
  if op=='countTokens':
   req=body['generateContentRequest']
   assert req['model']=='models/gemini-3.5-flash-lite'
   assert 'responseJsonSchema' in req['generationConfig']
   return {'totalTokens':5000} # schema pushes full request above local input cap
  raise AssertionError('generation must not occur after preflight cap failure')
 llm=GeminiFree('k',transport=transport,max_input_tokens=1000)
 with pytest.raises(BudgetExceeded):llm.generate_structured('short',make_response_schema({'price':{'amount':'p'}}))
 assert calls==['countTokens'] and llm.spent['calls']==0

def test_full_request_mutation_during_count_is_refused():
 import pytest
 def transport(op,body):
  body['generateContentRequest']['generationConfig']['temperature']=1
  return {'totalTokens':100}
 llm=GeminiFree('k',transport=transport)
 with pytest.raises(RuntimeError,match='Full request changed'):llm.generate_structured('q',make_response_schema({'f':{'amount':'p'}}))

def test_visible_region_label_does_not_establish_selected_region():
 from scout.engine.table_evidence import scope_context
 facts={'amount':[{'association':[{'table':0}]}]}
 tables=[{'unit':'Prices /M Tokens','controls':[{'text':'USD','pressed':'true'},{'text':'EUR','pressed':'false'},{'text':'STANDARD','pressed':'true'},{'text':'','label':'REGIONAL INFERENCE','checked':'false'}]}]
 c=scope_context(facts,tables,'https://fixture.example')
 assert c['selected_controls']==['USD','STANDARD']
 assert c['checkboxes']==[{'label':'REGIONAL INFERENCE','checked':'false'}]
 assert 'REGIONAL INFERENCE' not in c['selected_controls']

def test_unit_context_must_come_from_associated_table():
 from scout.engine.table_evidence import scope_context
 c=scope_context({'amount':[{'association':[{'table':1}]}]},[{'unit':'Prices /M Tokens'},{'unit':'Prices /1000 Pages','controls':[]}],'https://fixture.example')
 assert c['unit_label']=='Prices /1000 Pages'

def test_scoped_context_completeness_does_not_infer_global():
 from scout.engine.table_evidence import assess_price_context
 r=assess_price_context({'status':'scoped_dom_observation','unit_label':'Prices /M Tokens','selected_controls':['USD','STANDARD'],'checkboxes':[{'label':'REGIONAL INFERENCE','checked':'false'}]})
 assert r['status']=='scoped_components_present'
 assert r['regional_interpretation']=='regional_not_selected_only'
 assert 'global' not in str(r)

def test_wrong_unit_or_selected_mode_does_not_pass():
 from scout.engine.table_evidence import assess_price_context
 r=assess_price_context({'status':'scoped_dom_observation','unit_label':'Prices /1000 Pages','selected_controls':['USD','BATCH'],'checkboxes':[]})
 assert r['status']=='incomplete'
 assert 'million_token_unit' in r['missing'] and 'selected_Standard' in r['missing']
