"""Same live runner, provider default. Example: python3 scripts/run_provider_live.py --atomic --site mistral"""
import sys
from run_supplier_live import run_site
import argparse
p=argparse.ArgumentParser();p.add_argument('--site');p.add_argument('--dry-run',action='store_true');p.add_argument('--atomic',action='store_true')
a=p.parse_args();run_site(a.site,domain='provider',atomic=a.atomic,dry_run=a.dry_run)
