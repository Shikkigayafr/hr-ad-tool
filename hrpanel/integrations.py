"""Обёртки вызовов внешних систем (AD, Saby): считают результат и время для метрик."""
import time

from hrpanel import metrics


def _call(ops, duration, last_success, operation, func, args, kwargs):
    started = time.perf_counter()
    try:
        result = func(*args, **kwargs)
    except Exception:
        ops.labels(operation, "error").inc()                     # нет связи / исключение
        duration.labels(operation).observe(time.perf_counter() - started)
        raise
    # функции ad_utils возвращают (ok, сообщение)
    ok = result[0] if isinstance(result, tuple) else bool(result)
    ops.labels(operation, "ok" if ok else "fail").inc()          # fail — система ответила отказом
    duration.labels(operation).observe(time.perf_counter() - started)
    if ok:
        last_success.labels(operation).set_to_current_time()
    return result


def call_ad(operation: str, func, *args, **kwargs):
    """call_ad("reset_password", ad_utils.reset_password, login, password) — вызов + метрики."""
    return _call(metrics.AD_OPS, metrics.AD_DURATION, metrics.AD_LAST_SUCCESS, operation, func, args, kwargs)


def call_saby(operation: str, func, *args, **kwargs):
    return _call(metrics.SABY_OPS, metrics.SABY_DURATION, metrics.SABY_LAST_SUCCESS, operation, func, args, kwargs)
