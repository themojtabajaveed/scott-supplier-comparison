"""Conservative atomic evidence screen, not a semantic entailment proof.
Fields have a closed set of claim keys. Each atomic value must appear verbatim
inside its own verbatim source quote. No full-row prose is promoted to facts.
Model, variant, currency, unit and processing context are separate claims.
Missing claims and arbitrary additions remain unresolved/rejected.
"""
def validate_atoms(raw, allowed_keys, source_text, source_url):
    facts, rejected={},{}
    if not isinstance(raw,dict):return {'facts':{},'rejected':{'response':'not_object'},'missing':list(allowed_keys)}
    for key,item in raw.items():
        if key not in allowed_keys:
            rejected[key]='unknown_claim_key';continue
        if not isinstance(item,dict):
            rejected[key]='not_atomic_object';continue
        value,quote=item.get('value'),item.get('quote')
        if not isinstance(value,str) or not isinstance(quote,str) or not value or not quote:
            rejected[key]='missing_value_or_quote';continue
        if quote not in source_text or value not in quote:
            rejected[key]='value_not_explicitly_supported_by_quote';continue
        facts[key]={'value':value,'quote':quote,'source_url':source_url,'status':'literal_evidence_only'}
    return {'facts':facts,'rejected':rejected,'missing':[k for k in allowed_keys if k not in facts]}


def merge_evidence(existing, incoming):
    """Preserve all distinct literal values and their sources. Never pick a winner."""
    for key, fact in incoming.items():
        values=existing.setdefault(key,[])
        if not any(v['value']==fact['value'] and v['source_url']==fact['source_url'] for v in values):
            values.append(fact)
    return existing


def assess(evidence, schema, requirements=None):
    missing=[key for key in schema if not evidence.get(key)]
    conflicts={key:values for key,values in evidence.items()
               if len({v['value'].strip().casefold() for v in values})>1}
    import re
    incomplete_components={}
    for key,pattern in (requirements or {}).items():
        values=evidence.get(key,[])
        if values and not all(re.search(pattern,v['value'],re.I) for v in values):
            incomplete_components[key]='literal claim lacks required unit/condition components'
    # Literal disagreement may be formatting or context, so never claim a proven price change.
    status='source_disagreement' if conflicts else ('incomplete' if missing or incomplete_components else 'literal_components_present')
    return {'status':status,'missing':missing,'conflicts':conflicts,'facts':evidence,
            'review_required':True,'incomplete_components':incomplete_components}
