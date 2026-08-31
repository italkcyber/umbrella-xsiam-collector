import json  # noqa
from typing import Any, Dict, List, Optional, Tuple  # noqa
from datetime import datetime, timedelta, timezone

SENT = []


class DemistoException(Exception):
    pass


class CommandResults:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


def argToList(value, separator=','):
    if not value:
        return []
    if isinstance(value, list):
        return value
    return [v.strip() for v in str(value).split(separator) if v.strip()]


def arg_to_number(value):
    if value in (None, ''):
        return None
    return int(value)


def argToBoolean(value):
    if isinstance(value, bool):
        return value
    return str(value).lower() in ('true', 'yes', '1')


def arg_to_datetime(value, name='', required=False):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    num, unit = str(value).split()[:2]
    delta = {'day': 1, 'days': 1, 'hour': 1 / 24.0, 'hours': 1 / 24.0}[unit]
    return datetime.utcnow() - timedelta(days=int(num) * delta)


def return_results(x):
    print('RESULTS:', getattr(x, 'kwargs', x))


def return_error(msg):
    raise AssertionError(msg)


def tableToMarkdown(name, data, removeNull=False):
    return f'{name}: {len(data or [])} rows'


def send_events_to_xsiam(events, vendor, product, **kwargs):
    SENT.append((vendor, product, list(events)))


def handle_proxy(proxy_param_name='proxy', checkbox_default_value=False):
    return {}
