# -*- coding: utf-8 -*-
"""
Protocol configuration TEMPLATE.

Copy this file to `protocol_config.py` and fill in every value:

    cp protocol_config.example.py protocol_config.py

`protocol_config.py` is listed in .gitignore and must never be committed.
Every value can alternatively be supplied through a QO_* environment variable,
which takes precedence over the file.

This repository intentionally ships NO third-party protocol values, endpoints,
application ids, secrets or keys. Obtain them yourself and keep them local.
"""

# Service endpoints
BASE_URL = "https://api.example.com/api"
SMS_URL = "https://sms.example.com/member/sms/sendSecurityCode"

# Client metadata used to build signed requests
APP_VERSION = "0.0.0"
APP_VERSION_CODE = "0"
APP_CHANNEL = 1

# Protocol secrets - leave empty in the template
SIGNING_SALT = ""
HEX_AES_KEY = ""
SMS_APP_ID = ""
SMS_APP_SECRET = ""

# Upstream HTTP timeout in seconds
TIMEOUT = 8.0
