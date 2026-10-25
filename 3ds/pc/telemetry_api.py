"""Bounded device timing samples used by the shared viewer."""
import json
import math


def decode_morrowind(body):
    if not body or len(body) > 1024:
        raise ValueError('Invalid device telemetry size')
    try:
        value = json.loads(body)
    except (ValueError, UnicodeError) as exc:
        raise ValueError('Invalid device telemetry JSON') from exc
    if not isinstance(value, dict):
        raise ValueError('Invalid device telemetry object')
    result = {'map': 'Morrowind', 'source': 'device'}
    limits = {'fps': 1000, 'frameMs': 60000, 'workMs': 60000,
              'cpuMs': 60000, 'gpuMs': 60000, 'linearFreeKb': 1000000,
              'heapUsedKb': 1000000, 'timestampMs': 1e16}
    for name, limit in limits.items():
        number = value.get(name)
        if isinstance(number, bool) or not isinstance(number, (float, int)) or not math.isfinite(number) or not 0 <= number <= limit:
            raise ValueError(f'Invalid device telemetry field: {name}')
        result[name] = number
    return result
