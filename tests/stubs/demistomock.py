_last_run = {}
_params = {}
_args = {}
_command = ""


def params():
    return _params


def args():
    return _args


def command():
    return _command


def debug(*a, **k):
    pass


def info(*a, **k):
    pass


def error(*a, **k):
    print("ERROR:", *a)


def getLastRun():
    return _last_run


def setLastRun(value):
    global _last_run
    _last_run = value
