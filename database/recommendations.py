"""長町南の4大オススメ。台の数値を変更せず、週ごとの4機種だけを保存する。"""
from datetime import date, datetime, timedelta
import re

TYPE = '4大オススメ'
DEFAULT = dict(store='nagamachiminami', week='2026-10-26',
    machines=['L 甲鉄城のｶﾊﾞﾈﾘ 海門決戦 XX', 'L戦国乙女5L8', 'L戦国乙女4S3', 'Lﾓﾝｷｰﾀｰﾝ5CE'],
    updated_at='2026-10-24T00:00:00Z', device='pc')

def week(raw):
    if not isinstance(raw, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', raw) or date.fromisoformat(raw).weekday():
        raise ValueError('週開始日は月曜日を指定してください。')
    return raw

def days(first):
    start = date.fromisoformat(week(first))
    return [(start + timedelta(days=i)).isoformat() for i in range(7)]

def normal(name):
    return ''.join(name.replace('+', ' ').lower().split())

def plan(raw):
    if not isinstance(raw, dict) or raw.get('store') != 'nagamachiminami':
        raise ValueError('4機種の店舗が不正です。')
    names = raw.get('machines')
    if not isinstance(names, list) or len(names) != 4 or any(not isinstance(n, str) or not n.strip() or len(n)>300 or re.search(r'[\x00-\x1f]',n) for n in names) or len({normal(n) for n in names}) != 4:
        raise ValueError('異なる4機種を選んでください。')
    week(raw.get('week'))
    at = raw.get('updated_at')
    if not isinstance(at, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})', at):
        raise ValueError('4機種の編集時刻が不正です。')
    datetime.fromisoformat(at.replace('Z','+00:00'))
    return dict(store=raw['store'],week=raw['week'],machines=list(names),updated_at=at,device=raw.get('device') if raw.get('device') in ('pc','android','shared') else 'pc')

def merge(stored=(), incoming=(), strict=True):
    if not isinstance(stored,(list,tuple)) or not isinstance(incoming,(list,tuple)) or len(stored)>3000 or len(incoming)>3000:
        raise ValueError('4機種の週一覧が不正です。')
    out, orphans = {}, []
    for items,check in ((stored,False),(incoming,strict)):
        for raw in items:
            try:
                p=plan(raw); old=out.get(p['week'])
                if old is None or datetime.fromisoformat(p['updated_at'].replace('Z','+00:00')) >= datetime.fromisoformat(old['updated_at'].replace('Z','+00:00')):
                    out[p['week']]=p
            except (ValueError,TypeError,KeyError):
                if check: raise
                orphans.append(raw)
    result=[out[k] for k in sorted(out,reverse=True)]+orphans
    if len(result)>3000: raise ValueError('4機種の週一覧が上限に達しています。')
    return result

def plans(raw=()):
    result=[]
    for p in merge([DEFAULT],raw,False):
        try: result.append(plan(p))
        except (ValueError,TypeError,KeyError): pass
    return result

def saved_name(selected,names):
    if selected in names: return selected
    hits=[n for n in names if normal(n)==normal(selected)]
    return hits[0] if len(hits)==1 else None

def candidates(records,first):
    end=days(first)[-1]
    rows=[r for r in records if r['store']=='nagamachiminami' and r['day']<=end]
    latest=max((r['day'] for r in rows),default=None)
    groups={}
    for r in rows:
        if r['day']==latest: groups.setdefault(r['machine'],set()).add(r['rack'])
    return latest,[(n,len(r)) for n,r in sorted(groups.items()) if len(r)>=7]

def rows(records,first,selected):
    dates=days(first)
    source=[r for r in records if r['store']=='nagamachiminami' and r['day'] in dates]
    names={d:saved_name(selected,{r['machine'] for r in source if r['day']==d}) for d in dates}
    source=[r for r in source if r['machine']==names[r['day']]]
    out=[]
    for rack in sorted({r['rack'] for r in source}):
        cells=[]
        for d in dates:
            hits=[r for r in source if r['rack']==rack and r['day']==d]
            cells.append(hits[0] if len(hits)==1 else None)
        out.append((rack,cells))
    return out

FACES = ['😀','😍','🥶','😌','😇']

def result_key(r):
    return (r['store'],r['week'],r['machine'],r['rack'],r['day'])

def result(raw):
    if not isinstance(raw,dict) or not all(k in raw for k in ('store','week','machine','rack','day','value','updated_at')):raise ValueError('台ごとの顔文字が不正です。')
    p=plan(dict(DEFAULT,**{k:v for k,v in raw.items() if k!='machines'},machines=DEFAULT['machines']))
    if not isinstance(raw.get('machine'),str) or not raw['machine'].strip() or len(raw['machine'])>300 or re.search(r'[\x00-\x1f]',raw['machine']) or type(raw.get('rack')) is not int or not 0<=raw['rack']<=99999 or raw.get('day') not in days(raw['week']) or raw.get('value') not in [None,'',*FACES] or 'value' not in raw:
        raise ValueError('台ごとの顔文字が不正です。')
    return dict(store=p['store'],week=p['week'],machine=raw['machine'],rack=raw['rack'],day=raw['day'],value=raw['value'],updated_at=p['updated_at'],device=p['device'])

def merge_results(stored=(),incoming=(),strict=True):
    if not isinstance(stored,(list,tuple)) or not isinstance(incoming,(list,tuple)) or len(stored)>30000 or len(incoming)>30000:raise ValueError('台ごとの結果一覧が不正です。')
    out,orphans={},[]
    for items,check in ((stored,False),(incoming,strict)):
        for raw in items:
            try:
                r=result(raw);key=result_key(r);old=out.get(key)
                if old is None or datetime.fromisoformat(r['updated_at'].replace('Z','+00:00'))>=datetime.fromisoformat(old['updated_at'].replace('Z','+00:00')):out[key]=r
            except (ValueError,TypeError,KeyError,AttributeError):
                if check:raise
                orphans.append(raw)
    values=[out[k] for k in sorted(out)]+orphans
    if len(values)>30000:raise ValueError('台ごとの結果一覧が上限に達しています。')
    return values

def result_value(results,fields,automatic):
    for r in merge_results(results):
        try:
            valid=result(r)
            if result_key(valid)==result_key(fields):return automatic if valid['value'] is None else valid['value']
        except (TypeError,KeyError,ValueError,AttributeError):pass
    return automatic


def result_index(raw):
    out={}
    for value in merge_results(raw):
        try:
            r=result(value);out[result_key(r)]=r
        except (TypeError,KeyError,ValueError,AttributeError):pass
    return out
