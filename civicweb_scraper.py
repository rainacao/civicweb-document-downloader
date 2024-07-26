import requests
from bs4 import BeautifulSoup
import re
import pandas as pd
from collections import deque
import logging
# from joblib import Memory
import time
from pathlib import Path
from pprint import pprint
import mimetypes
from datetime import datetime
import traceback
import requests_cache