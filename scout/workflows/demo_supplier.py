"""DEMO supplier configuration: INVENTED suppliers on reserved .example addresses, for the offline demo entry points
(scripts/scout_ui_demo.py, scripts/build_demo_scorecard.py) and the public offline tests.

This is a separate, explicitly named demo configuration. It does not replace or change the real supplier
workflow (scout/workflows/supplier.py) or its network-gated connector; nothing selects it silently. Every name
here says "(invented)". None of it is a supplier fact.
"""
ONE, TWO, THREE = 'demo_mill_one', 'demo_mill_two', 'demo_mill_three'
LABELS = {ONE: 'Demo Mill One (invented)', TWO: 'Demo Mill Two (invented)', THREE: 'Demo Mill Three (invented)'}
SITES = [
    {'name': ONE, 'url': 'https://demo-mill-one.example/product/demo-strong-flour-16kg/',
     'delivery_page': 'https://demo-mill-one.example/delivery/',
     'offer_binding': {'product_path': '/product/demo-strong-flour-16kg', 'sku': 'DM1-16', 'pack': '16kg',
                       'single_offer': True}},
    {'name': TWO, 'url': 'https://demo-mill-two.example/products/demo-premium-flour-16kg',
     'delivery_page': 'https://demo-mill-two.example/pages/delivery',
     'offer_binding': {'product_path': '/products/demo-premium-flour-16kg', 'sku': 'DM2-16', 'pack': '16kg'}},
    {'name': THREE, 'url': 'https://demo-mill-three.example/products/demo-canadian-flour',
     'delivery_page': 'https://demo-mill-three.example/pages/delivery',
     'offer_binding': {'product_path': '/products/demo-canadian-flour', 'sku': 'DM3-16', 'pack': '16kg',
                       'required_channels': ['inline_script']},
     'variant_option': '16kg'},
]
SITE = {s['name']: s for s in SITES}
