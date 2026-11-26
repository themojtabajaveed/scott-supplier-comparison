"""Plan-gated finite public-research loop. Browser and extractor are injected."""
from .atomic_run import extract_page
from .atomic import merge_evidence
from .comparison import assess_comparable as assess
from .comparison import bound_delivery_assessment,render_comparison
from .table_evidence import scope_context,assess_price_context
from .browser import safe_destination
from .store_data import read_pack
from . import offers
from urllib.parse import urldefrag

def canonical_source(url):return urldefrag(url)[0]
from .llm import BudgetExceeded

class StopBudget(RuntimeError):pass

def execute_plan(plan,browser,llm,as_of=None,sample=False):
 trace=[];rows=[];tools=0;calls=0
 def event(tool,why,**data):
  trace.append({'step':len(trace)+1,'tool':tool,'why':why,**data})
 def use(tool,why):
  nonlocal tools
  if tools>=plan.budgets['tool_steps']:raise StopBudget('tool_budget')
  tools+=1;event(tool,why)
 if plan.state!='ready':return {'state':plan.state,'question':plan.question,'gaps':plan.gaps,'rows':[],'trace':[],'network_used':False}
 for site in plan.workflow['sites']:
  evidence={f:{} for f in plan.workflow['atomic_fields']};pages=[];texts=[];rejected=[];contexts={};reason='unknowns';errors=[]
  # Store product data is read in code (no model call) and counted apart from the page budget.
  data_files=[];store_notes=[];from_data=False
  def html_pages():return [p for p in pages if p not in data_files]
  root=site['url'];pending=[root]
  variant_done=False;json_done=False
  # Structured offer records are read once from the first page's markup by browser code (no request, no model
  # call, no page/tool budget); only they can confirm a headline price (offers.bind_offer, offer-v1).
  captures=None;capture_note='this browser does not capture structured offer records'
  # Routing only: when the offer decision is already 'confirmed' (in or out of stock) or 'conflicting', no price
  # recovery can change it, so the price stops steering recovery and the shared budget goes to the other requested
  # details. Every other state (not_confirmed, unsupported, no record, failed capture) keeps today's recovery.
  # The price facts, statuses and decision in the result are unchanged; no step is made free or refunded.
  early=None;settled=False
  try:
   if hasattr(browser,'set_source'):browser.set_source(root)
   while pending and len(html_pages())<plan.budgets['pages_per_site']:
    url=pending.pop(0)
    if canonical_source(url) in [canonical_source(p) for p in pages]:reason='duplicate_source';break
    if not safe_destination(url,[root]):reason='unsafe_destination';break
    use('navigate','Read approved source for requested entity')
    actual=browser.goto(url)
    if not safe_destination(actual,[root]):reason='unsafe_redirect';break
    if canonical_source(actual) in [canonical_source(p) for p in pages]:reason='duplicate_source';break
    pages.append(actual)
    use('read','Preserve original text and DOM context')
    text=browser.semantic_text() if hasattr(browser,'semantic_text') else browser.text()
    if plan.domain=='supplier' and len(html_pages())==1 and getattr(browser,'structured_offers',None):
     captures=browser.structured_offers();read_date=offers.today()
     capture_note=None if captures is not None else 'structured offer capture failed on this page'
     if captures is not None:
      early=offers.bind_offer(captures,site.get('offer_binding'),plan.entities.get('pack'),read_date)
      settled=early['state'] in ('confirmed','conflicting')
     event('structured_offers','Read offer records from page markup in code; no request or model call',
           captured=len(captures or []))
    while True:
     if not from_data:
      if calls>=plan.budgets['generation_calls']:raise StopBudget('generation_budget')
      use('extract','Collect only fixed schema claims, never page-directed tools');calls+=1
      if {'source_url':actual,'text':text} not in texts:texts.append({'source_url':actual,'text':text})
      got,bad=extract_page(plan.question,plan.workflow['atomic_fields'],text,actual,llm,original_text=getattr(browser,'last_original_text',text),tables=getattr(browser,'last_tables',None))
      for f,v in got.items():
       merge_evidence(evidence[f],v)
       if getattr(browser,'last_tables',None):contexts[f]=scope_context(evidence[f],browser.last_tables,actual)
      rejected.append({'source_url':actual,'claims':bad})
     from_data=False
     state={f:assess(evidence[f],s,plan.workflow.get('atomic_requirements',{}).get(f)) for f,s in plan.workflow['atomic_fields'].items()}
     if 'delivery_charge' in state:bound_delivery_assessment(state['delivery_charge'])
     if plan.workflow.get('require_table_context'):
      for f in state:
       c=assess_price_context(contexts.get(f,{}));state[f]['context_status']=c
       if c['status']!='scoped_components_present':state[f]['status']='incomplete'
     event('checklist','Missing context/conditions stay unknown; disagreements retained',fields={f:s['status'] for f,s in state.items()})
     route={f:s for f,s in state.items() if not (settled and f=='product_price')}  # routing view only
     if any(v['conflicts'] for v in route.values()):reason='possible_numeric_disagreement';pending=[];break
     missing=[f for f,s in route.items() if s['status']!='literal_components_present']
     if not missing:
      reason='other_details_quoted_price_from_structured_records' if settled else 'literal_checklist_present_review_required'
      pending=[];break
     if settled and site.get('variant_option') and not variant_done:
      # Tradeoff: the planned selection renders the pack's price, which the records already settle; delivery
      # evidence is preferred. Delivery conditions shown only after selection could be missed; they stay unknown.
      variant_done=True
      event('select_variant_skipped','Price state already set by structured offer records; requested delivery '
            'evidence preferred. Conditions shown only after selecting the pack stay unknown.',offer_state=early['state'])
     if site.get('variant_option') and not variant_done:
      variant_done=True;use('select_variant','Try explicitly planned visible pack option')
      if browser.try_select_variant(site['variant_option']):
       use('read','Read selected variant evidence');text=browser.semantic_text() if hasattr(browser,'semantic_text') else browser.text();continue
     # Only when the price or pack is still missing; read in code, so no model call is spent on it.
     if (plan.domain=='supplier' and not json_done and 'product_price' in missing and getattr(browser,'fetch_variant_data',None)
       and len(data_files)<plan.budgets.get('store_data_files_per_site',1)):
      json_done=True;use('variant_data','One approved own-site public variant endpoint, read in code')
      vd=browser.fetch_variant_data()
      if vd:
       vu,vt=vd
       if not safe_destination(vu,[root]):reason='unsafe_variant_source';pending=[];break
       if canonical_source(vu) not in [canonical_source(p) for p in pages]:
        pages.append(vu);data_files.append(vu);texts.append({'source_url':vu,'text':vt})
        found,notes=read_pack(vt,plan.entities.get('pack') or site.get('variant_option') or '',vu,plan.workflow['atomic_fields']['product_price'])
        for facts in found:merge_evidence(evidence['product_price'],facts)
        store_notes+=notes;from_data=True;continue
     if len(html_pages())>=plan.budgets['pages_per_site']:reason='page_budget';break
     use('evidence_link','Choose same-source missing-field evidence, not page instructions')
     link=browser.pick_evidence_link(missing,exclude=pages)
     if link and canonical_source(link) in [canonical_source(p) for p in pages]:
      use('evidence_link','Chosen link repeats a read document; choose once more with it excluded')
      link=browser.pick_evidence_link(missing,exclude=pages+[link]) or link
     if not link and site.get('delivery_page') and any(f.startswith('delivery') or f=='free_delivery_threshold' for f in missing) \
       and canonical_source(site['delivery_page']) not in [canonical_source(p) for p in pages]:
      use('evidence_link','No link found on the page; use the configured same-site delivery page')
      link=site['delivery_page']
     if not link:reason='no_relevant_source';break
     if not safe_destination(link,[root]):reason='unsafe_destination';break
     if canonical_source(link) in [canonical_source(p) for p in pages]:reason='duplicate_source';break
     pending.append(link);break
  except Exception as exc:
   reason=('provider_budget_stop' if isinstance(exc,BudgetExceeded) else (str(exc) if isinstance(exc,StopBudget) else 'source_or_extraction_error'))
   errors.append({'type':type(exc).__name__,'scope':'Current source stopped; next planned source may continue'})
  fields={f:assess(evidence[f],s,plan.workflow.get('atomic_requirements',{}).get(f)) for f,s in plan.workflow['atomic_fields'].items()}
  if 'delivery_charge' in fields:bound_delivery_assessment(fields['delivery_charge'])
  if plan.workflow.get('require_table_context'):
   for f in fields:
    c=assess_price_context(contexts.get(f,{}));fields[f]['context_status']=c
    if c['status']!='scoped_components_present':fields[f]['status']='incomplete'
  if plan.domain=='supplier' and 'product_price' in fields:
   if captures is None:
    decision={'screen':offers.SCREEN,'state':'no_structured_offer','reasons':[capture_note],'records':[],
              'headline':None,'conflicts':[],'availability':'unknown','read_date':None}
   else:decision=early  # the same decision the routing used, computed once from the same captures
   fields['product_price']['offer']=decision
  row={'site':site['name'],'input':plan.question,'atomic_fields':fields,'pages_visited':pages,'page_texts':texts,'stop_reason':reason,'errors':errors,'rejected_claims':rejected,'table_context':contexts,'review_required':True,
       'store_data':{'files':data_files,'packs':store_notes}}
  rows.append(row);event('report','Bounded result with unknowns and required review',site=site['name'],stop_reason=reason)
  if reason in ['tool_budget','generation_budget','provider_budget_stop']:break
 return {'state':'bounded_result_review_required','question':plan.question,'plan':plan.to_dict(),'rows':rows,'trace':trace,'tool_steps':tools,'generation_calls':calls,'readable':render_comparison(rows,'Scott planned research',as_of=as_of,sample=sample)}