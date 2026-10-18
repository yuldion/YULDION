class YuldionError(Exception):
    """Actionable engine/configuration error; never replaced with a fake performance."""

class ContractError(YuldionError):
    pass

class Cancelled(YuldionError):
    pass
