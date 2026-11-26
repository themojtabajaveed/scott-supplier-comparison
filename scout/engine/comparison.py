"""Readable cited evidence tables, not an automatic cheapest/model verdict."""
import re


def _mentions(value, text):
    """Literal value inside text, but never as part of a longer number (so £5 is not found in £55 or £5.50)."""
    return bool(value) and re.search(r'(?<![\d.,])'+re.escape(value)+r'(?!\d|[.,]\d)', text or '') is not None


UNLINKED_WARNINGS={'basis':'Rate and charge basis are not linked in the same quoted evidence; do not combine.',
                   'order_condition':'Order condition and charge are not linked in the same quoted evidence; do not combine.'}


def bound_delivery_assessment(field):
    """Conservative co-quote screen; separate quotes cannot prove rate association.
    Does not prove applicability, exhaustiveness, destination or correct tax basis.
    A basis or order condition must be quoted together with the charge it qualifies;
    an unlinked one stays listed as a claim but is reported missing for this rate.
    """
    facts=field.get('facts',{})
    amounts=facts.get('amount',[]);warnings=[]
    for key in ('basis','order_condition'):
        claims=facts.get(key,[])
        if amounts and claims and not all(any(a['source_url']==c['source_url'] and
            (_mentions(a['value'],c.get('quote','')) or _mentions(c['value'],a.get('quote',''))) for c in claims) for a in amounts):
            if key not in field.setdefault('missing',[]):field['missing'].append(key)
            warnings.append(UNLINKED_WARNINGS[key])
    if warnings:
        if field.get('status')=='literal_components_present':field['status']='incomplete'
        field['binding_warning']=' '.join(warnings)
    return field

def safe(value):
    return str(value).replace('|','\\|').replace('\n',' ')

def evidence_line(as_of=None,sample=False):
    """Header sentence saying what kind of evidence this is and when it was read.
    as_of is the date the pages were read; without one the date is reported as unrecorded, never assumed.
    """
    if sample:lead='Sample data invented for this demo, not evidence read from any website.'
    elif as_of:lead='Read-only evidence snapshot, '+str(as_of)+'.'
    else:lead='Read-only evidence snapshot; the read date is not recorded with this result.'
    return lead+' Literal evidence is not a semantic proof or exhaustive extraction. No cheapest/model-quality verdict.'

def render_comparison(rows,title,notes=None,as_of=None,sample=False):
    out=['# '+title,'',evidence_line(as_of,sample),'']
    for row in rows:
        out+=['## '+row['site'],'','Input: '+row.get('input','Named model prices and selected DOM pricing context.'),'',
              '| Field | Observed claims | Status / unknowns |','| --- | --- | --- |']
        for field,v in row['atomic_fields'].items():
            claims=[]
            for key,items in v.get('facts',{}).items():
                for item in items:
                    claims.append(safe(key)+': '+safe(item['value'])+' ([source]('+item['source_url']+'))')
            unknown=v.get('missing',[])
            status=v['status']+('; missing: '+', '.join(unknown) if unknown else '')
            if v.get('binding_warning'):status+='; '+v['binding_warning']
            if v.get('variation_note'):status+='; '+v['variation_note']
            if v.get('conflicts'):status+='; conflicting values retained, no winner selected'
            out+=['| '+safe(field)+' | '+'<br>'.join(claims or ['No accepted claims'])+' | '+safe(status)+' |']
        out+=['','### Evidence trail','']
        for field,v in row['atomic_fields'].items():
            for key,items in v.get('facts',{}).items():
                for item in items:
                    out+=['- '+field+'.'+key+': "'+item.get('quote','')+'" ([source]('+item['source_url']+'))']
        if row.get('context_assessment'):out+=['','Context assessment: '+safe(row['context_assessment'])]
        if notes and row['site'] in notes:out+=['','Manual review: '+notes[row['site']]]
        out+=['','Human review required. Unknowns are final output for this bounded run, not a promise of further research.','']
    return '\n'.join(out)


def assess_comparable(evidence,schema,requirements=None):
    """Preserve literal variation without asserting a confirmed real-world conflict.
    Only differing amount numbers get a possible numeric-disagreement label.
    Differing numbers in any other claim stay a variation, with a note that a human
    must judge whether the meanings match (neither agreement nor conflict is claimed).
    Neither label establishes a price change or matched source context.
    """
    import re
    from .atomic import assess
    out=assess(evidence,schema,requirements)
    variants=out.pop('conflicts')
    out['conflicts']={}
    out['literal_variations']=variants
    if variants:
        amounts=variants.get('amount',[])
        numbers={tuple(re.findall(r'\d+(?:\.\d+)?',x['value'])) for x in amounts}
        if len(numbers)>1:
            out['conflicts']={'amount':amounts};out['status']='possible_numeric_disagreement'
        else:out['status']='incomplete_literal_variation'
        numbered=[k for k,vals in variants.items() if k!='amount' and
                  len({tuple(re.findall(r'\d+(?:\.\d+)?',x['value'])) for x in vals})>1]
        # The wording note is only for claims other than the amount; an amount-only disagreement has its own status.
        if numbered:out['variation_note']='Different numbers quoted for '+', '.join(numbered)+'; human review needed to judge whether the meanings match; not a confirmed contradiction.'
        elif any(k!='amount' for k in variants):out['variation_note']='Different wording/coverage retained; not a confirmed factual contradiction.'
    return out