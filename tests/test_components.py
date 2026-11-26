from scout.evals.components import score

def test_partial_does_not_pass_amount_alone():
 rubric=[{'site':'x','field':'fee','components':{'amount':r'£6.12','box':r'per box','vat':r'inc VAT'}}]
 row={'site':'x','fields':{'fee':{'value':'£6.12','quote':'£6.12 inc VAT','quote_verbatim':True,'source_url':'https://x.example'}}}
 result=score([row],rubric)['cells'][0]
 assert result['status']=='partial' and result['missing']==['box']

def test_conflict_cannot_become_correct_by_matching_one_price():
 rubric=[{'site':'x','field':'price','components':{'price':'21.30'},'conflict':True}]
 assert score([{'site':'x','fields':{'price':{'value':'21.30'}}}],rubric)['cells'][0]['status']=='unresolved_source_conflict'
