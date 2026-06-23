"""Inspecciona adjuntos de un mensaje Gmail para ver la estructura."""
import sys
import base64
import hashlib
sys.path.insert(0, 'agente/scripts')
from dotenv import load_dotenv
load_dotenv('.env')
from gmail_collector import get_service

svc = get_service("principal")
mid = "19e8d4cc61a54c69"
m = svc.users().messages().get(userId='me', id=mid, format='full').execute()


def walk(parts, depth=0):
    for p in parts:
        fn = p.get('filename', '') or '[no-filename]'
        mt = p.get('mimeType', '')
        att_id = p.get('body', {}).get('attachmentId')
        sz = p.get('body', {}).get('size', 0)
        marker = 'ATT' if att_id else 'inline'
        print(f"{'  '*depth}{fn} | {mt} | size={sz} | {marker}")
        if 'parts' in p:
            walk(p['parts'], depth+1)


walk(m['payload'].get('parts', []))
print()
print("=== headers ===")
for h in m['payload'].get('headers', []):
    if h['name'] in ('Subject', 'From', 'Date'):
        print(h['name'], ':', h['value'])
