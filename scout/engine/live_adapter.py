"""Connect a checked plan to existing real adapters, without fixture substitution.
No CLI live entrypoint yet. Review gate defaults closed. No new model/framework.
"""
from .tool_loop import execute_plan
from ..local_config import verified_project

def run_live_plan(plan, *, api_key, verified_free_project, ledger_path,
                  safety_reviewed=False, browser_factory=None, client_factory=None):
    # Clarification must not construct browser/client or touch the network.
    if plan.state!='ready':return execute_plan(plan,None,None)
    if not safety_reviewed:
        raise RuntimeError('Live plan execution remains closed pending safety review')
    expected=verified_project()  # local, never committed; None keeps the gate closed
    if not expected or verified_free_project!=expected or not api_key or not ledger_path:
        raise RuntimeError('Exact free-project binding, secure key and ledger required')
    if browser_factory is None:
        from .browser import ReadOnlyBrowser
        browser_factory=ReadOnlyBrowser
    if client_factory is None:
        from .llm import GeminiFree
        client_factory=GeminiFree
    llm=client_factory(api_key,max_calls=plan.budgets['generation_calls'],
        max_input_tokens=12000,max_output_tokens=6000,max_output_per_call=1000,
        ledger_path=ledger_path,free_project_verified=True)
    browser=browser_factory()
    try:return execute_plan(plan,browser,llm)
    finally:browser.close()
