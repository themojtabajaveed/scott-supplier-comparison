"""Strict component scoring. No substring equivalence and no relaxed partial passes.
A source quote may carry a condition omitted from a short value, but required
components must all appear in value + verbatim quote, with a real source URL.
A conflicted truth cell is excluded from correctness and remains unresolved.
"""
import re
from collections import Counter

def score(rows, rubric):
    by_site = {r['site']: r for r in rows}
    out=[]
    for cell in rubric:
        item=by_site.get(cell['site'],{}).get('fields',{}).get(cell['field'])
        text = ((str(item.get('value',''))+' '+str(item.get('quote',''))) if isinstance(item,dict) else '')
        missing=[name for name,pattern in cell['components'].items() if not re.search(pattern,text,re.I)]
        if cell.get('conflict'):
            status='unresolved_source_conflict'
        elif not item:
            status='missing'
        elif not item.get('quote_verbatim') or not item.get('source_url'):
            status='unsupported'
        elif missing:
            status='partial'
        else:
            status='complete'
        out.append(dict(site=cell['site'],field=cell['field'],required=list(cell['components']),
                        missing=missing,status=status,observed=item))
    return {'counts':dict(Counter(c['status'] for c in out)), 'cells':out}
