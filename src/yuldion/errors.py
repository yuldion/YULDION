class YuldionError(Exception):
    """Actionable engine/configuration error; never replaced with a fake performance."""

class ContractError(YuldionError):
    pass

class Cancelled(YuldionError):
    pass

class InferenceFailure(YuldionError):
    def __init__(self, category, http_status=None, retry_after=None):
        self.category=category
        self.http_status=http_status
        self.retryable=category in ('timeout','connection') or http_status in (408,429,500,502,503,504)
        self.retry_after_seconds=retry_after
        super().__init__(category + (f' HTTP {http_status}' if http_status else ''))


def failure_record(error):
    from urllib.error import HTTPError
    status=getattr(error,'http_status',None)
    if isinstance(error,HTTPError):status=error.code
    return {'type':type(error).__name__,'category':getattr(error,'category','validation' if isinstance(error,(ValueError,ContractError)) else 'execution'),
            'http_status':status,'retryable':getattr(error,'retryable',status in (408,429,500,502,503,504)),
            'retry_after_seconds':getattr(error,'retry_after_seconds',None)}
