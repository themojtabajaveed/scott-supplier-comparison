"""Narrow deterministic question planner. Not an open-ended reasoning planner."""
from dataclasses import dataclass,asdict
import re
from copy import deepcopy
from scout.workflows import supplier,provider

@dataclass
class Plan:
 question:str
 domain:str|None
 state:str
 gaps:list
 entities:dict
 workflow:dict
 steps:list
 budgets:dict
 def to_dict(self):return asdict(self)

def plan_question(question):
 q=question.casefold();domain=None;gaps=[];entities={};wf={}
 if any(w in q for w in ['flour','sack']):domain='supplier'
 if any(w in q for w in ['token','api pric','mistral','claude','gpt-']):
  if domain:gaps.append('Question mixes the two supported domains')
  else:domain='provider'
 if domain=='supplier':
  wf=deepcopy(supplier.WORKFLOW);wf['atomic_fields']=deepcopy(supplier.ATOMIC_FIELDS)
  pack=re.search(r'\b(\d+(?:\.\d+)?)\s*kg\b',q)
  entities={'pack':pack.group(0) if pack else None,'product': 'wholemeal' if 'wholemeal' in q else ('strong white bread flour' if 'strong white' in q else None)}
  if not pack or float(pack.group(1))!=16:gaps.append('Supported pack is explicit 16kg; supplied pack is preserved above')
  if not entities['product']:gaps.append('Specify strong white bread flour or wholemeal bread flour')
  sites=[s for s in wf['sites'] if s['name'].replace('_mill','').replace('_',' ') in q]
  # A narrow parser must refuse unparsed entity words rather than silently
  # select defaults. Remove only a closed vocabulary and known source labels.
  without_urls=re.sub(r'https?://[^\s]+|\b(?:[a-z0-9-]+\.)+[a-z]{2,}(?:/[^\s]*)?', ' ',q)
  known={'compare','comparison','the','a','an','and','or','of','for','one','sack','sacks','flour','bread','strong','white','wholemeal','16kg','16','kg','delivery','delivered','conditions','condition','price','prices','cost','costs','shipping','facts','supplier','suppliers','mill','mills','uk','standard','wessex','cotswold','shipton','what','which','is','are','cheapest','please','find','show','me','at','from','to','buy','does','much','how','with','including','threshold','free'}
  residual=[w for w in re.findall(r'[a-z0-9]+',without_urls) if w not in known]
  if residual:gaps.append('Unparsed supplied entity/constraint: '+', '.join(residual)+'; no default replacement')
  if re.search(r'\bfrom\b',q) and not sites:gaps.append('Source not recognized; supplied source remains in original question')
  if 'wholemeal' in q:
   if not ('wessex' in q) or any(w in q for w in ['cotswold','shipton']):gaps.append('Wholemeal supported only on Wessex; no other product inferred')
   sites=[deepcopy(supplier.WHOLEMEAL_SITE)]
  elif not sites:sites=wf['sites']
  wf['sites']=sites
 elif domain=='provider':
  wf=deepcopy(provider.WORKFLOW);wf['atomic_fields']=deepcopy(provider.ATOMIC_FIELDS)
  wf['atomic_requirements']=deepcopy(provider.ATOMIC_REQUIREMENTS);wf['require_table_context']=True
  models=provider.SUPPORTED_MODELS
  selected=[(m,s) for m,s in models if m.casefold() in q]
  remaining=q
  for model,_ in selected:remaining=remaining.replace(model.casefold(),' ')
  remaining=re.sub(r'https?://[^\s]+|\b(?:[a-z0-9-]+\.)+[a-z]{2,}(?:/[^\s]*)?', ' ',remaining)
  allowed={'compare','comparison','and','or','the','a','an','for','of','what','is','are','price','prices','pricing','api','standard','usd','uncached','input','output','per','million','tokens','token','cost','costs','please','show','me','at','on','from','text','processing','both'}
  residual=[w for w in re.findall(r'[a-z0-9]+',remaining) if w not in allowed]
  if residual:gaps.append('Unparsed supplied model/context: '+', '.join(residual)+'; no entity dropped')
  entities={'models':[m for m,s in selected],'requested_context':question}
  if not selected:gaps.append('Specify a supported exact model: '+', '.join(m for m,s in models))
  if 'usd' not in q:gaps.append('Specify USD currency; no currency assumed')
  if 'standard' not in q:gaps.append('Specify Standard processing; no pricing mode assumed')
  if 'input' not in q or 'output' not in q:gaps.append('Specify both input and output prices')
  if any(w in q for w in ['batch','priority','cached price','eur','long context']):gaps.append('Requested pricing context is outside this narrow planner')
  wf['sites']=[]
  for m,s in selected:
   site=deepcopy(next(x for x in provider.WORKFLOW['sites'] if x['name']==s))
   site.update(model=m,question=question);wf['sites'].append(site)
 else:gaps.append('Supported domains: 16kg flour supplier facts or named-model API token pricing')
 candidates=[token.strip('\"\'(),;').rstrip('.') for token in question.split()]
 urls=[t for t in candidates if '://' in t or re.fullmatch(r'(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}(?:/[^\s]*)?',t)]
 approved=[s['url'] for s in wf.get('sites',[])]
 from urllib.parse import urlparse
 for u in urls:
  cleaned=u.rstrip('.,;)')
  if cleaned.startswith(('http://','https://')):
   ok=cleaned in approved
  else:ok=cleaned.lower() in [urlparse(x).netloc.lower() for x in approved]
  if not ok:gaps.append('Supplied domain/URL not recognized as approved source: '+cleaned+'; no replacement inferred')
 if gaps:wf['sites']=[]  # Inert clarification plans cannot carry default destinations.
 wf['question']=question
 for s in wf.get('sites',[]):s['question']=question
 wf['max_pages']=2
 return Plan(question,domain,'needs_clarification' if gaps else 'ready',gaps,entities,wf,
  ['Read approved public source','Extract literal evidence','Check fields and context','Recover missing evidence within bounds','Report facts, conflicts and unknowns'],
  {'pages_per_site':2,'store_data_files_per_site':1,'tool_steps':24,'generation_calls':6})