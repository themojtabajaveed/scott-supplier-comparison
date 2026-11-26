# Offline tool trace

{'step': 1, 'tool': 'navigate', 'why': 'Read approved source for requested entity'}
{'step': 2, 'tool': 'read', 'why': 'Preserve original text and DOM context'}
{'step': 3, 'tool': 'extract', 'why': 'Collect only fixed schema claims, never page-directed tools'}
{'step': 4, 'tool': 'checklist', 'why': 'Missing context/conditions stay unknown; disagreements retained', 'fields': {'product_price': 'literal_components_present', 'delivery_charge': 'incomplete', 'free_delivery_threshold': 'incomplete', 'delivery_time': 'incomplete', 'delivery_geography': 'incomplete'}}
{'step': 5, 'tool': 'evidence_link', 'why': 'Choose same-source missing-field evidence, not page instructions'}
{'step': 6, 'tool': 'navigate', 'why': 'Read approved source for requested entity'}
{'step': 7, 'tool': 'read', 'why': 'Preserve original text and DOM context'}
{'step': 8, 'tool': 'extract', 'why': 'Collect only fixed schema claims, never page-directed tools'}
{'step': 9, 'tool': 'checklist', 'why': 'Missing context/conditions stay unknown; disagreements retained', 'fields': {'product_price': 'literal_components_present', 'delivery_charge': 'incomplete', 'free_delivery_threshold': 'incomplete', 'delivery_time': 'incomplete', 'delivery_geography': 'incomplete'}}
{'step': 10, 'tool': 'report', 'why': 'Bounded result with unknowns and required review', 'site': 'demo_mill_one', 'stop_reason': 'page_budget'}
{'step': 11, 'tool': 'navigate', 'why': 'Read approved source for requested entity'}
{'step': 12, 'tool': 'read', 'why': 'Preserve original text and DOM context'}
{'step': 13, 'tool': 'extract', 'why': 'Collect only fixed schema claims, never page-directed tools'}
{'step': 14, 'tool': 'checklist', 'why': 'Missing context/conditions stay unknown; disagreements retained', 'fields': {'product_price': 'literal_components_present', 'delivery_charge': 'incomplete', 'free_delivery_threshold': 'incomplete', 'delivery_time': 'incomplete', 'delivery_geography': 'incomplete'}}
{'step': 15, 'tool': 'evidence_link', 'why': 'Choose same-source missing-field evidence, not page instructions'}
{'step': 16, 'tool': 'report', 'why': 'Bounded result with unknowns and required review', 'site': 'demo_mill_two', 'stop_reason': 'no_relevant_source'}
{'step': 17, 'tool': 'navigate', 'why': 'Read approved source for requested entity'}
{'step': 18, 'tool': 'read', 'why': 'Preserve original text and DOM context'}
{'step': 19, 'tool': 'extract', 'why': 'Collect only fixed schema claims, never page-directed tools'}
{'step': 20, 'tool': 'checklist', 'why': 'Missing context/conditions stay unknown; disagreements retained', 'fields': {'product_price': 'incomplete', 'delivery_charge': 'incomplete', 'free_delivery_threshold': 'incomplete', 'delivery_time': 'incomplete', 'delivery_geography': 'incomplete'}}
{'step': 21, 'tool': 'select_variant', 'why': 'Try explicitly planned visible pack option'}
{'step': 22, 'tool': 'variant_data', 'why': 'One approved own-site public variant endpoint, read in code'}
{'step': 23, 'tool': 'checklist', 'why': 'Missing context/conditions stay unknown; disagreements retained', 'fields': {'product_price': 'possible_numeric_disagreement', 'delivery_charge': 'incomplete', 'free_delivery_threshold': 'incomplete', 'delivery_time': 'incomplete', 'delivery_geography': 'incomplete'}}
{'step': 24, 'tool': 'report', 'why': 'Bounded result with unknowns and required review', 'site': 'demo_mill_three', 'stop_reason': 'possible_numeric_disagreement'}