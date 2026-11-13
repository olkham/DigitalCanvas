"""Conversion utilities - type conversions."""


def strtobool(val):
    """Convert string representation of truth to True/False/None.
    
    True values: 'y', 'yes', 't', 'true', 'on', '1'
    False values: 'n', 'no', 'f', 'false', 'off', '0'
    """
    if val is None:
        return None
    
    if not isinstance(val, str):
        raise ValueError("not a string: %r" % (val,))
    
    val = val.lower()
    if val in ('y', 'yes', 't', 'true', 'on', '1'):
        return True
    elif val in ('n', 'no', 'f', 'false', 'off', '0'):
        return False
    else:
        raise ValueError("invalid truth value %r" % (val,))
