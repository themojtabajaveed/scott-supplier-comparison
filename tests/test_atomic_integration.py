"""New synthetic held-out control-flow cases. Not a live-world reliability sample.
These cases use unseen fixture wording and do not reuse prior supplier outputs.
"""
from scout.engine.agent import run
from scout.engine.trace import Trace

class Browser:
 def __init__(self,pages):self.pages=pages
 def goto(self,url):self.url=url;return url
 def text(self):return self.pages[self.url]
 def pick_evidence_link(self,missing,exclude):return None
 def fetch_variant_data(self):return None

class LLM:
 def __init__(self,answers):self.answers=iter(answers)
 def generate_json(self,prompt):return next(self.answers)

def execute(tmp_path,answers,pages=None):
 wf={'atomic_fields':{'fee':{'amount':'charge','box_count':'sacks per box'}},'sites':[{'name':'heldout','url':'https://fixture.example/p'}]}
 tr=Trace(str(tmp_path/'trace.jsonl'))
 try:return run('q',wf,LLM(answers),Browser(pages or {'https://fixture.example/p':'£8 per box. Packing depends on item.'}),tr)[0]
 finally:tr.close()

def test_new_wording_does_not_license_box_count(tmp_path):
 r=execute(tmp_path,[{'fee':{'amount':{'value':'£8','quote':'£8 per box.'},'box_count':{'value':'one sack','quote':'£8 per box.'}}}])
 assert r['atomic_fields']['fee']['status']=='incomplete'
 assert r['atomic_fields']['fee']['missing']==['box_count']
 assert r['rejected_claims'][0]['claims']['fee']['box_count']=='value_not_explicitly_supported_by_quote'

def test_conflict_keeps_both_sources(tmp_path):
 b=Browser({'https://fixture.example/p':'Price £8','https://fixture.example/p.js':'Price £9'})
 b.fetch_variant_data=lambda:('https://fixture.example/p.js','Price £9')
 llm=LLM([{'price':{'amount':{'value':'£8','quote':'Price £8'}}},{'price':{'amount':{'value':'£9','quote':'Price £9'}}}])
 wf={'atomic_fields':{'price':{'amount':'amount'}},'sites':[{'name':'new','url':'https://fixture.example/p'}]}
 tr=Trace(str(tmp_path/'t'))
 try:r=run('q',wf,llm,b,tr)[0]
 finally:tr.close()
 assert r['atomic_fields']['price']['status']=='source_disagreement'
 assert {v['value'] for v in r['atomic_fields']['price']['conflicts']['amount']}=={'£8','£9'}

def test_missing_model_context_does_not_pass(tmp_path):
 r=execute(tmp_path,[{'fee':{'amount':{'value':'£8','quote':'£8 per box.'}}}])
 assert r['atomic_fields']['fee']['review_required']
 assert r['atomic_fields']['fee']['status']!='literal_components_present'

def test_isolated_price_does_not_establish_model_association():
 from scout.engine.atomic_run import extract_page
 llm=LLM([{'input':{'amount':{'value':'$7','quote':'$7'},'model':{'value':'Example Model','quote':'Example Model'}}}])
 facts,rejected=extract_page('q',{'input':{'amount':'price','model':'row'}},'Example Model $7 Other Model $7','https://fixture.example',llm)
 assert 'amount' not in facts['input']
 assert rejected['input']['amount']=='amount_quote_missing_model_row'
