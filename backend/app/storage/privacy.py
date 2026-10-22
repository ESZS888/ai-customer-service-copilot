"""Basic local-demo masking, not a general PII detection service."""
import re


def safe_text(value):
    value = re.sub(r'(?i)(?:Bearer\s+|(?:api[_ -]?key|token|password|密钥)\s*[:=：]\s*)[^\s，。；;]+', '[凭据已隐藏]', value)
    value = re.sub(r'(?i)\bsk-[A-Za-z0-9._-]+', '[凭据已隐藏]', value)
    value = re.sub(r'(?<!\d)1[3-9]\d{9}(?!\d)', '[手机号已隐藏]', value)
    return re.sub(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', '[邮箱已隐藏]', value)


def safe_value(value):
    if isinstance(value, str):
        return safe_text(value)
    if isinstance(value, list):
        return [safe_value(item) for item in value]
    if isinstance(value, dict):
        return {key:safe_value(item) for key,item in value.items()}
    return value
