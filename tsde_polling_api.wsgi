#!/usr/bin/python
import sys
import logging
logging.basicConfig(stream=sys.stderr)
sys.path.insert(0,"/var/www/Tsde_polling_api/Tsde_polling_api")

from Tsde_polling_api.polling_api import app as application