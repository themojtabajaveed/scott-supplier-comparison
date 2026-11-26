from scout.engine.comparison import bound_delivery_assessment,render_comparison

def fact(value,quote,url='https://fixture.example/p'):
 return {'value':value,'quote':quote,'source_url':url}

def test_separate_regional_basis_cannot_bind_base_rate():
 field={'status':'literal_components_present','facts':{'amount':[fact('3.85','Standard 3.85')],'basis':[fact('per parcel','7.95 per parcel')]}}
 assert bound_delivery_assessment(field)['status']=='incomplete'
 assert 'binding_warning' in field

def test_same_quote_preserves_binding_without_proving_all_conditions():
 q='Charge per box: £5.10 ex VAT (£6.12 inc VAT)'
 field={'status':'incomplete','facts':{'amount':[fact('£5.10',q)],'basis':[fact('per box','per box')]}}
 assert 'binding_warning' not in bound_delivery_assessment(field)
 assert field['status']=='incomplete'

def test_different_source_does_not_bind():
 field={'facts':{'amount':[fact('7','7 per box')],'basis':[fact('per box','7 per box','https://fixture.example/other')]}}
 assert 'binding_warning' in bound_delivery_assessment(field)

def test_readable_output_keeps_both_values_and_unknown():
 field={'status':'source_disagreement','missing':['zone'],'conflicts':{'amount':[]},'facts':{'amount':[fact('£21.30','Price £21.30'),fact('£24','Price £24','https://fixture.example/data')]}}
 text=render_comparison([{'site':'X','atomic_fields':{'price':field}}],'Demo')
 assert '£21.30' in text and '£24' in text and 'missing: zone' in text
 assert 'No cheapest/model-quality verdict' in text and 'https://fixture.example/data' in text
