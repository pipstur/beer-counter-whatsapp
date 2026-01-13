import re

GROUP_PREFIX = "grupa za pivo"
TIME_REGEX = re.compile(r"\b\d{1,2}:\d{2}\s?(AM|PM|am|pm)?\b")
PLUS_BEER_REGEX = re.compile(r"(?:^|\s)\+(\d{1,2})(?:\s|$)")
USER_DATA_DIR = "./chrome-profile"
