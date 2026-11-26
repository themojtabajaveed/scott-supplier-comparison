"""Preserve semantic row/column association without inventing price context.
Input cells and headings are actual DOM text. Output is a labelled derivative
source representation, not a claim that headings necessarily govern all rows.
"""
import re

def render_tables(tables):
    chunks=[]
    for table in tables:
        headers=table.get('headers',[])
        context=table.get('context','').strip()
        if context:chunks.append('Table context (page heading): '+context)
        if table.get('unit'):chunks.append('DOM table unit label: '+table['unit'])
        for c in table.get('controls',[]):
            label=c.get('text') or c.get('label')
            if c.get('pressed')=='true':chunks.append('DOM selected control: '+label)
            if c.get('checked') in ('true','false'):chunks.append('DOM checkbox state: '+label+' = '+c['checked'])
        for row in table.get('rows',[]):
            if not row:continue
            cells=[re.sub(r'\s+',' ',str(c)).strip() for c in row]
            labelled=[]
            for i,cell in enumerate(cells):
                header=headers[i] if i<len(headers) and headers[i] else 'column '+str(i+1)
                labelled.append(str(header)+': '+cell)
            chunks.append('ROW | '+' | '.join(labelled))
    return '\n'.join(chunks)


def scope_context(facts, tables, source_url):
    """Bind only to table indices already associated with the amount/model row.
    Selected controls and unchecked states are explicit structured evidence,
    never quotes forged from visible labels. A false regional checkbox is an
    observed off-state, not a proven synonym for global routing.
    """
    amount=facts.get('amount',[])
    indices={a['table'] for f in amount for a in f.get('association',[])}
    if len(indices)!=1:return {'status':'unknown','reason':'no unique associated table'}
    idx=next(iter(indices));t=tables[idx]
    selected=[c.get('text') for c in t.get('controls',[]) if c.get('pressed')=='true']
    checkboxes=[{'label':c.get('label') or c.get('text'),'checked':c.get('checked')}
                for c in t.get('controls',[]) if c.get('checked') in ('true','false')]
    return {'status':'scoped_dom_observation','table':idx,'unit_label':t.get('unit',''),
            'selected_controls':selected,'checkboxes':checkboxes,'source_url':source_url,
            'review_required':True}


def assess_price_context(context):
    """Exact scoped DOM criteria, not global pricing correctness."""
    missing=[]
    import re
    if context.get('status')!='scoped_dom_observation':return {'status':'incomplete','missing':['unique_table_scope']}
    if not re.search(r'/\s*M\s+Tokens',context.get('unit_label',''),re.I):missing.append('million_token_unit')
    selected=[s.upper() for s in context.get('selected_controls',[]) if s]
    if 'USD' not in selected:missing.append('selected_USD')
    if 'STANDARD' not in selected:missing.append('selected_Standard')
    region=[c for c in context.get('checkboxes',[]) if c['label'].upper()=='REGIONAL INFERENCE']
    if len(region)!=1 or region[0]['checked']!='false':missing.append('observed_regional_off_state')
    return {'status':'scoped_components_present' if not missing else 'incomplete','missing':missing,
            'regional_interpretation':'regional_not_selected_only' if region and region[0]['checked']=='false' else 'unknown',
            'review_required':True}
