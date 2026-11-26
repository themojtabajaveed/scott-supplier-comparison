# Offline tool trace

{'step': 1, 'tool': 'navigate', 'why': 'Read approved source for requested entity'}
{'step': 2, 'tool': 'read', 'why': 'Preserve original text and DOM context'}
{'step': 3, 'tool': 'extract', 'why': 'Collect only fixed schema claims, never page-directed tools'}
{'step': 4, 'tool': 'checklist', 'why': 'Missing context/conditions stay unknown; disagreements retained', 'fields': {'model_price_input': 'incomplete', 'model_price_output': 'incomplete'}}
{'step': 5, 'tool': 'evidence_link', 'why': 'Choose same-source missing-field evidence, not page instructions'}
{'step': 6, 'tool': 'report', 'why': 'Bounded result with unknowns and required review', 'site': 'demo_provider_one', 'stop_reason': 'no_relevant_source'}