# package imports
import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By

from pathlib import Path
import re
import pandas as pd
import logging
import traceback

# from joblib import Memory
import requests_cache
from requests_cache import CachedSession
from collections import deque
import time
from datetime import datetime
import mimetypes
from pprint import pprint

##### CONSTANTS
OUT_FOLDER = Path.cwd() / "out"
HEADERS = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_13_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/84.0.4147.125 Safari/537.36'}

##### LOGGER SETUP
logging.basicConfig(format='%(asctime)s - %(levelname)s:%(message)s', datefmt='%Y-%m-%d %H:%M:%S')
logger = logging.getLogger(__name__)
# logger.setLevel(logging.DEBUG)
logger.setLevel(logging.INFO)

#### FUNCTIONS
def create_cache(name="civicweb_scraper_cache", expire_after=3600*24*14, allowable_codes=[200], **kwargs):
    logger.info(f"Getting cache with name {name} which will expire after {expire_after} seconds.")
    # requests_cache.install_cache(name, backend='sqlite', expire_after=expire_after, **kwargs)
    return CachedSession(name, backend='sqlite', expire_after=expire_after, allowable_codes=allowable_codes, **kwargs)

def remove_url_from_cache(session:CachedSession, urls:list[str]):
    logger.info(f"Removing URLs {urls} from cache {session.cache.cache_name}.")
    session.cache.delete(url=urls)

def clear_cache(session:CachedSession):
    session.cache.clear()

# def fetch_webpage_with_cache(url, session:CachedSession, headers=HEADERS):
#     response = session.get(url, headers=headers)
#     try:
#         response.raise_for_status() # raise exception if response was not successful
#         return response
#     except requests.exceptions.HTTPError as e:
#         raise e

# def fetch_webpage(url, headers=HEADERS):
#     response = requests.get(url, headers=headers)
#     try:
#         response.raise_for_status() # raise exception if response was not successful
#         return response
#     except requests.exceptions.HTTPError as e:
#         raise e

def get_items(response, parent_url:str, parent=[], is_folder=True)->list[dict]:
    ''' 
    Return a list of dictionaries containing information for each item in the current folder. Items are either documents or folders.
    
    Parameters
    ----------
    response: CachedSessions or Requests
        The html object to parse. Should be the documents site for a website under the civicweb.net domain.
    parent_url : str
        The url of the current folder. This is the url appended onto the root of the website, and should start with "/".
    parent : list(str)
        List of the folders on the path to the current item, relative to the root of the website. parent[0] should be the first folder on the path, and parent[-1] is the current folder. parent=[] indicates that the folder belongs to the root.
    is_folder  : bool
        Whether or not the current folder is a folder (True) or a document (False).

    Returns
    -------
    items : list[dict]
        A list of dictionaries containing information for each item in the current folder. Each dictionary contains the following keys:
        - name : The name of the item.
        - url : The url of the item.
        - parent_url : The url of the parent folder.
        - parent : A list of the folders on the path to the current item.
    '''
    logger.debug("folder parent: %s", parent)

    bs = BeautifulSoup(response.content,'html.parser')

    child_items = []
    if is_folder: 
        item_class = "folder-link" 
    else: 
        item_class = "document-link" 

    for item in bs.find_all("a", class_=item_class):
        item_info = {
                "name": item.text.strip(), 
                "url": item.get('href'),
                "parent": parent,
                "parent_url": parent_url
            }
        logger.debug(f"Found {item_class} with name {item_info['name']} (url: {item_info['url']}) in directory at {'/'.join(item_info['parent'])} (url: {parent_url}).")
        child_items.append(item_info)
    return child_items

def get_filetype(response:requests) -> tuple[str, str]:
    ''' 
    Returns the extension and file type (MIME notation) of a response object based on its Content-Type header.
    '''
    header_mimetype = response.headers['Content-Type']

    # remove mimetype parameter if it exists
    if ";" in header_mimetype:
        header_mimetype = header_mimetype.split(";")[0]
    extension = mimetypes.guess_extension(header_mimetype)

    # raise error if file extension cannot be guessed from response
    if extension is None or extension == "":
        logger.warning("Could not determine file type for response")
        raise TypeError(f"Could not determine file type")
    
    return extension, header_mimetype

def download_file(response:requests, filename:str, out_path=Path.cwd() / "out"):
    ''' 
    Downloads a file from the given response.
    
    Parameters
    ----------
    response : requests.Response, cached_requests.CacheSession
        The response object.
    filename : str
        The name of the file being downloaded. Should include the extension.
    
    out_path : Path, optional
        The path where the file should be saved on the disk, as a pathlib Path object. Defaults to a folder in the current working directory named "out". Does not need to exist.
    '''
    out_path.mkdir(parents=True, exist_ok=True) # ensure directories leading up to the output file path exist
    with open(out_path / filename, "wb") as f:
        f.write(response.content)
        f.close()

def download_document(session, document, root_url, subdomain) -> dict:
    ''' 
    Download according to a document information dictionary, and return a dictionary of the download details.
    '''
    error = ""
    file_extension = ""
    file_type = ""

    try:
        response = session.get(url=root_url+document["url"], headers=HEADERS)

        out_path = OUT_FOLDER.joinpath(subdomain, *document["parent"])

        file_extension, file_type = get_filetype(response)
        logger.debug((f"File: {document['name']}{file_extension}"))

        download_file(
        response, 
        filename=document["name"]+file_extension,
        out_path=out_path)
    except Exception as e:
        logger.error(e)
        error += f"{e}"
    finally:
        download_dict = {
                    "name": document["name"]+file_extension,
                    "file_type": file_type,
                    "subdomain": subdomain,
                    "parent_path": "/".join(document["parent"]),
                    "root_url": root_url, 
                    "url": document["url"], 
                    "parent_url": document["parent_url"],
                    "date_scraped": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "error": error
                }
        return download_dict

if __name__ == "__main__":
    pass